"""测试公共配置。

必须在导入 app 之前设置环境变量：Settings 是 lru_cache 的，导入后不可改。
CI 不调用任何外部服务，因此这里显式清空模型与向量配置（验证降级路径）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite://"  # 内存库：验证“数据库可用 + 模型缺失”的降级组合
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["EMBEDDING_API_KEY"] = ""
os.environ["EMBEDDING_MODEL"] = ""
os.environ["ADMIN_TOKEN"] = "test-admin-token"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)
