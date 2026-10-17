"""枚举代码值的唯一来源，与 docs/data-dictionary.md 第 3 节逐条对应。

数据库存左侧代码值，界面显示中文；两者都不允许在别处再写一遍。
新增取值先改数据字典，再改这里，然后才有迁移与接口。
"""

from __future__ import annotations

# 3.1 核对状态：pending 只允许存在于 data/raw/，导入 verified/ 时会被拒绝
VERIFICATION_STATUS = ("pending", "verified", "disputed", "link_stale", "retracted")
PUBLISHABLE_VERIFICATION_STATUS = ("verified", "disputed", "link_stale", "retracted")

# 3.2 其他枚举
EVIDENCE_TYPE = ("earliest_attestation", "commandery", "migration", "other")
CONFIDENCE = ("high", "medium", "low")
SUPPORT_TYPE = ("direct", "circumstantial", "genealogy")
RELATION_TYPE = ("direct", "circumstantial", "genealogy", "conflicting")
RELATION_STATUS = ("agreed", "disputed", "unclear")
ALIAS_TYPE = ("variant", "honorific", "traditional_simplified", "other")
WORK_TYPE = ("official_history", "surname_book", "local_gazetteer", "classic", "other")
LICENSE_STATUS = ("public_domain", "platform_terms_ok", "restricted_excerpt_only", "unknown")
LOCATION_STATUS = ("located", "approximate", "unlocatable")
LINK_STATUS = ("ok", "stale")
SURNAME_CATEGORY = ("single", "compound")
# 姓氏主记录的发布状态：draft 只有语料审计、published 已有可展示证据
SURNAME_STATUS = ("draft", "published")
ANSWER_MODE = ("evidence_grounded", "degraded_no_model", "insufficient_evidence")
INGESTION_STAGE = ("fetch", "clean", "verify", "load", "index")


def sql_in(values: tuple[str, ...]) -> str:
    """把枚举元组转成 CHECK 约束里的 IN 列表，避免各模型手写字符串。"""
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"
