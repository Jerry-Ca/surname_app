"""兼容性护栏（任务 C-07）：保证代码不偷偷依赖台服务器 Python 版本更高的语法或标准库成员。

生产服务器是 **Python 3.10.12**（Ubuntu 22.04 自带），本机开发是 3.12。
3.12 上写得跑得通、3.10 上 import 就炸的东西必须在这里拦住：
  1. 语法：用 ast.parse(feature_version=(3, 10)) 校验每个源文件；
  2. 标准库成员：3.11+/3.12+ 才有的名字一律不许出现（黑名单见下）；
  3. ruff 目标版本：必须保持在 py38/py310 —— 设成 py312 时 pyupgrade 会把
     timezone.utc 自动"升级"成 datetime.UTC（3.11+），兼容改动会被悄悄改回去（真实踩过）。
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted(
    [path for path in (PROJECT_ROOT / "app").glob("*.py")]
    + [path for path in (PROJECT_ROOT / "scripts").glob("*.py")]
    + [path for path in (PROJECT_ROOT / "tests").glob("*.py")]
    + [PROJECT_ROOT / "app" / "server.py"]
)

# 3.11+ / 3.12+ 才有的标准库成员（出现在代码里就等于放弃 3.10 兼容）
FORBIDDEN_PATTERNS = {
    r"\bdatetime\.UTC\b": "datetime.UTC 是 3.11+，请用 datetime.timezone.utc",
    r"from datetime import[^\n]*\bUTC\b": "datetime.UTC 是 3.11+，请用 datetime.timezone.utc",
    r"\btomllib\b": "tomllib 是 3.11+",
    r"\bExceptionGroup\b": "ExceptionGroup 是 3.11+",
    r"\bStrEnum\b": "StrEnum 是 3.11+",
    r"itertools\.batched": "itertools.batched 是 3.12+",
    r"hashlib\.file_digest": "hashlib.file_digest 是 3.11+",
    r"typing\.Self|\bSelf\b(?!\.)": "typing.Self 是 3.11+，用字符串注解代替",
    r"@override\b": "typing.override 是 3.12+",
    r"\.walk\(\)": "Path.walk 是 3.12+",
    r"zip\([^)]*strict=": "zip(strict=) 是 3.10+（能用，但本仓库统一不用，避免混淆）",
}


class SyntaxVersionTest(unittest.TestCase):
    def test_all_sources_parse_as_python_310(self) -> None:
        failures = []
        for path in SOURCES:
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 10))
            except SyntaxError as exc:  # pragma: no cover - 失败时给出可读定位
                failures.append(f"{path.relative_to(PROJECT_ROOT)}:{exc.lineno} {exc.msg}")
        self.assertEqual(failures, [], f"有语法在 Python 3.10 上不合法：{failures}")

    def test_all_sources_parse_as_python_38(self) -> None:
        """比目标更低一档：留出降级空间（最低要求写在 README 里）。"""
        failures = []
        for path in SOURCES:
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 8))
            except SyntaxError as exc:  # pragma: no cover
                failures.append(f"{path.relative_to(PROJECT_ROOT)}:{exc.lineno} {exc.msg}")
        self.assertEqual(failures, [], f"有语法在 Python 3.8 上不合法：{failures}")


# 本文件自身写着这些"禁止出现的模式"，扫描时要跳过它，否则会自己命中自己
MEMBER_SCAN_SOURCES = [path for path in SOURCES if path.name != "test_compat.py"]


class StdlibMemberTest(unittest.TestCase):
    def test_no_members_newer_than_python_310(self) -> None:
        violations = []
        for path in MEMBER_SCAN_SOURCES:
            text = path.read_text(encoding="utf-8")
            for pattern, message in FORBIDDEN_PATTERNS.items():
                for match in re.finditer(pattern, text):
                    line = text[: match.start()].count("\n") + 1
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{line} {message}")
        self.assertEqual(violations, [], "发现只在 3.11+/3.12+ 存在的标准库用法：\n" + "\n".join(violations))


class RuffTargetTest(unittest.TestCase):
    def test_ruff_target_version_stays_old_enough(self) -> None:
        config = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'target-version\s*=\s*"py(\d)(\d+)"', config)
        self.assertIsNotNone(match, "pyproject.toml 里必须写死 ruff 的 target-version")
        version = (int(match.group(1)), int(match.group(2)))
        self.assertLessEqual(
            version, (3, 10),
            "ruff 目标版本不得高于 py310：设成 py312 时 pyupgrade 会把 timezone.utc 升回 datetime.UTC（3.11+），"
            "兼容改动会被自动改回去",
        )


if __name__ == "__main__":
    unittest.main()
