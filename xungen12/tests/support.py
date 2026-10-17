"""测试公共支持：临时库、样例数据、命令行入口（只用标准库 unittest）。

约定（执行清单 §1.1）：运行时临时库只能放 data/tmp/，测试结束清理；
测试库文件名仍叫 xungen.db，但位于 data/tmp/<唯一目录>/ 下，绝不碰正式库。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PYTHON = os.environ.get("PYTHON", sys.executable)
# 测试绝不调用真实模型：把 Key 从环境里摘掉，问答必定走 unavailable 降级分支
os.environ.pop("DEEPSEEK_API_KEY", None)
SAMPLES = PROJECT_ROOT / "data" / "samples"
WORK_ROOT = PROJECT_ROOT / "data" / "tmp" / f"unittest-{uuid.uuid4().hex[:8]}"


def prepare_database(*, with_samples: bool = True) -> Path:
    """建临时库并（可选）导入样例数据；返回数据库路径。

    幂等：多个测试模块会先后调用它，第二次调用不能再去导入一遍（编号唯一，会被拒）。
    """
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = WORK_ROOT / "xungen.db"
    os.environ["XUNGEN_DB"] = str(db_path)
    if db_path.exists():
        try:
            import sqlite3

            with sqlite3.connect(db_path) as probe:
                if probe.execute("SELECT count(*) FROM evidences").fetchone()[0] > 0:
                    return db_path
        except sqlite3.Error:
            pass  # 库还是空的/结构不全：走下面的初始化
    env = {**os.environ, "XUNGEN_DB": str(db_path)}
    commands = [[PYTHON, str(PROJECT_ROOT / "scripts" / "init_db.py"), "--db", str(db_path)]]
    if with_samples:
        commands.append(
            [PYTHON, str(PROJECT_ROOT / "scripts" / "import_data.py"), str(SAMPLES), "--operator", "C", "--apply"]
        )
    for command in commands:
        completed = subprocess.run(command, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"准备测试库失败：{' '.join(command)}\n{completed.stdout}\n{completed.stderr}")
    return db_path


def cleanup() -> None:
    shutil.rmtree(WORK_ROOT, ignore_errors=True)


def run_script(name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, str(PROJECT_ROOT / "scripts" / name), *args],
        cwd=PROJECT_ROOT,
        env={**os.environ, "XUNGEN_DB": str(WORK_ROOT / "xungen.db")},
        capture_output=True,
        text=True,
    )
