"""项目内的固定路径（执行清单 §1.1：数据库只能是 data/xungen.db）。

所有脚本都从本模块取路径，不依赖当前工作目录——在共享服务器上从哪个目录调用它都能跑对。
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
# 生产环境固定 data/xungen.db；XUNGEN_DB 只给契约测试与恢复演练指向 data/tmp/ 里的临时副本用
DB_PATH = Path(os.environ["XUNGEN_DB"]) if os.environ.get("XUNGEN_DB") else DATA_DIR / "xungen.db"
TMP_DIR = DATA_DIR / "tmp"
SAMPLES_DIR = DATA_DIR / "samples"
SCHEMA_VERSION_FILE = DATA_DIR / "schema_version.txt"

LOGS_DIR = PROJECT_ROOT / "logs"
RUN_DIR = PROJECT_ROOT / "run"
BACKUPS_DIR = PROJECT_ROOT / "backups"
PID_FILE = RUN_DIR / "server.pid"
APP_LOG = LOGS_DIR / "app.log"

# D 的构建产物放这里；没有这个目录时静态资源一律 404，不做目录浏览
STATIC_DIR = PROJECT_ROOT / "static"

# 当前 schema 版本（执行清单 §1.2）
SCHEMA_VERSION = "1"


def ensure_dirs() -> None:
    """确保运行期目录存在（logs/run/backups/data/tmp）。"""
    for directory in (DATA_DIR, TMP_DIR, LOGS_DIR, RUN_DIR, BACKUPS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
