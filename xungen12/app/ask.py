"""证据问答（任务 C-13）：先取证据，再（可选）调用模型；模型不可用返回 unavailable。

硬要求（执行清单 §三.9、§四.1.6、AGENTS.md 铁律 3）：
  - 先按姓氏/证据编号取出结构化证据，模型只是"总结已检索到的证据"；
  - 模型不可用（未配置 Key 或调用失败）时返回结构化证据 + unavailable，**不返回 5xx**，不泄露 Key 或报错细节；
  - 回答里出现的 [EV-xxx] 必须都在 citations 里；出现新事实或没有编号就弃答；
  - 证据不足时固定文案「当前资料不足以确认」。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.error
import urllib.request

from . import contract, db, search
from .queries import VISIBLE, evidence_rows, resolve_surname

ABSTAIN_TEXT = "当前资料不足以确认"
CITATION = re.compile(r"\[(EV-[A-Z-]+-\d{3})\]")
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_TIMEOUT = 20
TOP_K_DEFAULT = 8
TOP_K_MAX = 20


def model_config() -> dict:
    """只从环境变量读；不打印、不返回 Key 本身。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    return {
        "configured": bool(key),
        "model": os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "base_url": os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        "_key": key,
    }


def _citation(item: dict) -> dict:
    return {
        "evidence_id": item["evidence_id"],
        "verification_status": item["verification_status"],
        "verification_status_label": item["verification_status_label"],
        "confidence": item["confidence"],
        "source_title": item["source"]["title"],
        "volume_or_section": item["volume_or_section"],
        "original_excerpt": item["original_excerpt"],
        "source_url": item["source"]["url"],
    }


def _retrieve(
    connection: sqlite3.Connection, surname: str | None, question: str, evidence_ids: list[str], top_k: int
) -> tuple[list[dict], str | None]:
    """取证据：优先按调用方指定的编号，其次按问题检索，最后退到该姓氏的全部证据。"""
    items: list[dict] = []
    if evidence_ids:
        placeholders = ",".join("?" * len(evidence_ids))
        rows = db.query_all(
            connection,
            f"{search._EVIDENCE_SELECT} AND e.evidence_id IN ({placeholders}) ORDER BY {search._ORDER_BY}",
            [*VISIBLE, *evidence_ids],
        )
        items = [contract.evidence_item(row) for row in rows]
        missing = sorted(set(evidence_ids) - {item["evidence_id"] for item in items})
        note = None
        if missing:
            note = f"以下编号没有可展示的证据（不存在或仍是待核对状态）：{'、'.join(missing)}"
        return items[:top_k], note

    if question.strip():
        found = search.search(connection, question, raw_surname=surname, page=1, page_size=top_k)
        items = found["data"] or []
    if not items and surname:
        row, _, _ = resolve_surname(connection, surname)
        if row is not None:
            items = [contract.evidence_item(item) for item in evidence_rows(connection, row["id"])[:top_k]]
    return items[:top_k], None


def _build_prompt(surname: str | None, question: str, items: list[dict]) -> list[dict]:
    evidence_lines = []
    for item in items:
        evidence_lines.append(
            f"[{item['evidence_id']}] {item['claim_text']}｜出处：{item['source']['title']}"
            f"·{item['volume_or_section']}｜原文：{item['original_excerpt']}"
            f"｜状态：{item['verification_status_label']}"
        )
    system = (
        "你是姓氏研究工具的摘要助手。只能总结下面给出的证据，禁止补充任何未出现的事实；"
        "每句结论后必须附 [证据编号]；证据不足以回答时只回答：当前资料不足以确认。"
    )
    user = f"姓氏：{surname or '未指定'}\n问题：{question}\n\n可用证据：\n" + "\n".join(evidence_lines)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _call_model(config: dict, messages: list[dict]) -> tuple[str, str | None]:
    """调用 DeepSeek（标准库 urllib）；返回 (回答, 错误原因)。失败不抛异常。"""
    payload = json.dumps({"model": config["model"], "messages": messages, "temperature": 0}).encode("utf-8")
    request = urllib.request.Request(
        f"{config['base_url'].rstrip('/')}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {config['_key']}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=DEEPSEEK_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
        answer = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return answer.strip(), None if answer.strip() else "模型返回空内容"
    except urllib.error.HTTPError as exc:
        return "", f"模型接口返回 HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return "", f"模型接口不可达：{type(exc).__name__}"
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        return "", f"模型响应无法解析：{type(exc).__name__}"


def ask(
    connection: sqlite3.Connection,
    *,
    question: str,
    surname: str | None = None,
    evidence_ids: list[str] | None = None,
    top_k: int = TOP_K_DEFAULT,
) -> dict:
    """回答一个问题；任何异常都转成可解释的状态，绝不返回 5xx。"""
    if not question.strip():
        raise contract.ApiProblem(422, contract.VALIDATION_ERROR, "问题不能为空", {"field": "question"})
    if not 1 <= top_k <= TOP_K_MAX:
        raise contract.ApiProblem(
            422, contract.VALIDATION_ERROR, f"top_k 必须在 1—{TOP_K_MAX} 之间", {"field": "top_k", "value": top_k}
        )

    items, retrieve_note = _retrieve(connection, surname, question, evidence_ids or [], top_k)
    citations = [_citation(item) for item in items]
    audit = contract.audit_block(
        coverage="in_corpus" if items else "not_in_corpus", counts={"retrieved": len(items)},
        total_results=len(items),
    )
    audit["retrieval"] = {"question": question, "surname": surname, "top_k": top_k, "evidence_ids": evidence_ids or []}

    if not items:
        return contract.ok(
            {
                "answer": ABSTAIN_TEXT,
                "answer_mode": "insufficient_evidence",
                "abstained": True,
                "abstain_reason": "no_evidence",
                "citations": [],
                "model": {"provider": "deepseek", "used": False, "model": None},
            },
            audit,
            retrieve_note or "没有检索到可用的证据，无法基于证据回答。",
        )

    config = model_config()
    if not config["configured"]:
        # 降级：仍把检索到的证据完整返回，前端可用结构化证据回答用户
        return contract.ok(
            {
                "answer": ABSTAIN_TEXT,
                "answer_mode": "unavailable",
                "abstained": True,
                "abstain_reason": "model_unavailable",
                "citations": citations,
                "model": {"provider": "deepseek", "used": False, "model": config["model"]},
            },
            audit,
            retrieve_note or "智能摘要暂不可用（服务器未配置模型 Key）；结构化证据仍可正常查询。",
        )

    answer, failure = _call_model(config, _build_prompt(surname, question, items))
    if failure:
        return contract.ok(
            {
                "answer": ABSTAIN_TEXT,
                "answer_mode": "unavailable",
                "abstained": True,
                "abstain_reason": "model_unavailable",
                "citations": citations,
                "model": {"provider": "deepseek", "used": False, "model": config["model"]},
            },
            audit,
            f"智能摘要暂不可用（{failure}）；结构化证据仍可正常查询。",
        )

    cited = set(CITATION.findall(answer))
    known = {item["evidence_id"] for item in items}
    if not cited:
        return contract.ok(
            {
                "answer": ABSTAIN_TEXT,
                "answer_mode": "insufficient_evidence",
                "abstained": True,
                "abstain_reason": "ungrounded_answer",
                "citations": citations,
                "model": {"provider": "deepseek", "used": True, "model": config["model"]},
            },
            audit,
            "模型回答没有引用证据编号，按规则不作为结论展示。",
        )
    unknown = sorted(cited - known)
    if unknown:
        return contract.ok(
            {
                "answer": ABSTAIN_TEXT,
                "answer_mode": "insufficient_evidence",
                "abstained": True,
                "abstain_reason": "unknown_citation",
                "citations": citations,
                "model": {"provider": "deepseek", "used": True, "model": config["model"]},
            },
            audit,
            f"模型引用了不存在的证据编号：{'、'.join(unknown)}，按规则弃答。",
        )

    used = [citation for citation in citations if citation["evidence_id"] in cited]
    return contract.ok(
        {
            "answer": answer,
            "answer_mode": "evidence_grounded",
            "abstained": False,
            "abstain_reason": None,
            "citations": used,
            "model": {"provider": "deepseek", "used": True, "model": config["model"]},
        },
        audit,
        retrieve_note,
    )
