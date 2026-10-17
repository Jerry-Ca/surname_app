"""时间处理：数据库统一存**朴素 UTC**，接口统一输出 ISO 8601 UTC 字符串。

为什么不在库里存带时区的时间：SQLite 与 PostgreSQL 对带时区时间的读写行为不同，
朴素 UTC 加一个显式序列化函数是两种数据库都稳定的最小方案。
契约要求的时间格式见 docs/api-contract.md 第 1 节（如 2026-10-17T03:21:00Z）。
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """当前时间的朴素 UTC 表示，用于数据库列的 Python 端默认值。"""
    return datetime.now(UTC).replace(tzinfo=None)


def to_iso8601(value: datetime | None) -> str | None:
    """把库里的朴素 UTC 时间输出成契约要求的 ISO 8601 UTC 字符串。"""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso8601(text: str | None) -> datetime | None:
    """解析 CSV 中的 ISO 8601 UTC 时间（如 2026-10-17T03:21:00Z），失败返回 None。

    这里不做宽容解析：格式不对的错误由导入校验给出可读提示，不在这里猜。
    """
    if not text:
        return None
    candidate = text.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed
