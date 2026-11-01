"""配置解析的单测。

重点是行尾注释：`.env.example` 里写了 `KEY=12000   # 说明`，
如果注释被当成值的一部分，`int()` 会失败并静默退回默认值。
默认值恰好相同，所以这种 bug 不会报错，只会让配置"改了但不生效"。
"""

import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent / "_tmp"


class TestEnvParser(unittest.TestCase):
    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.dir = TMP_ROOT / uuid.uuid4().hex[:8]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)
        shutil.rmtree(self.dir, ignore_errors=True)

    def load(self, content: str):
        path = self.dir / ".env"
        path.write_text(content, encoding="utf-8")
        for key in ("A", "B", "C", "D", "E"):
            os.environ.pop(key, None)
        config._load_env_file(path)

    def test_inline_comment_stripped(self):
        self.load("A=12000   # 这是注释\n")
        self.assertEqual(os.environ["A"], "12000")

    def test_full_line_comment_ignored(self):
        self.load("# 整行注释\nB=hello\n")
        self.assertNotIn("#", os.environ.get("B", ""))
        self.assertEqual(os.environ["B"], "hello")

    def test_hash_without_space_kept(self):
        # URL 里的 # 前面没有空白，不能被当成注释
        self.load("C=https://example.com/x#frag\n")
        self.assertEqual(os.environ["C"], "https://example.com/x#frag")

    def test_quotes_stripped(self):
        self.load('D="带引号的值"\n')
        self.assertEqual(os.environ["D"], "带引号的值")

    def test_existing_env_wins(self):
        # 命令行临时覆盖应该优先于 .env
        path = self.dir / ".env"
        path.write_text("E=from-file\n", encoding="utf-8")
        os.environ["E"] = "from-shell"
        config._load_env_file(path)
        self.assertEqual(os.environ["E"], "from-shell")

    def test_int_config_parses_cleanly(self):
        self.load("PERSONA_MAX_MATERIAL=9999   # 注释\n")
        self.assertEqual(config._int("PERSONA_MAX_MATERIAL", 12000), 9999)


if __name__ == "__main__":
    unittest.main()
