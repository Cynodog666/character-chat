"""会话持久化的单测：写入、读取、清空、裁剪、损坏容错。"""

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, sessions  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent / "_tmp"


class TestSessions(unittest.TestCase):
    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.dir = TMP_ROOT / uuid.uuid4().hex[:8]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.old = config.SESSION_DIR
        config.SESSION_DIR = self.dir
        self.name = "测试角色"

    def tearDown(self):
        config.SESSION_DIR = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_empty_at_start(self):
        self.assertEqual(sessions.load_session(self.name), [])

    def test_append_and_reload(self):
        sessions.append_turn(self.name, "你好", "你好啊")
        messages = sessions.load_session(self.name)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "你好")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertTrue(messages[0]["ts"])

    def test_multiple_turns_accumulate(self):
        sessions.append_turn(self.name, "第一句", "第一答")
        sessions.append_turn(self.name, "第二句", "第二答")
        messages = sessions.load_session(self.name)
        self.assertEqual([m["content"] for m in messages], ["第一句", "第一答", "第二句", "第二答"])

    def test_clear(self):
        sessions.append_turn(self.name, "你好", "你好啊")
        self.assertTrue(sessions.clear_session(self.name))
        self.assertEqual(sessions.load_session(self.name), [])
        self.assertFalse(sessions.clear_session(self.name))

    def test_isolated_per_persona(self):
        sessions.append_turn("甲", "甲的话", "甲的答")
        sessions.append_turn("乙", "乙的话", "乙的答")
        self.assertEqual(sessions.load_session("甲")[0]["content"], "甲的话")
        self.assertEqual(sessions.load_session("乙")[0]["content"], "乙的话")

    def test_trims_old_messages(self):
        old = sessions.MAX_MESSAGES
        sessions.MAX_MESSAGES = 4
        try:
            for i in range(5):
                sessions.append_turn(self.name, f"问{i}", f"答{i}")
            messages = sessions.load_session(self.name)
            self.assertEqual(len(messages), 4)
            # 保留最后两条问答
            self.assertEqual(messages[0]["content"], "问3")
        finally:
            sessions.MAX_MESSAGES = old

    def test_corrupted_file_returns_empty(self):
        path = sessions.session_path(self.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{坏掉的 json", encoding="utf-8")
        self.assertEqual(sessions.load_session(self.name), [])

    def test_ignores_bad_entries(self):
        path = sessions.session_path(self.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"messages": [
                {"role": "user", "content": "正常"},
                {"role": "system", "content": "不该出现"},
                {"role": "assistant", "content": ""},
                "不是字典",
            ]}, ensure_ascii=False),
            encoding="utf-8",
        )
        messages = sessions.load_session(self.name)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "正常")

    def test_strip_ts(self):
        sessions.append_turn(self.name, "问", "答")
        stripped = sessions.strip_ts(sessions.load_session(self.name))
        self.assertEqual(stripped, [{"role": "user", "content": "问"}, {"role": "assistant", "content": "答"}])


if __name__ == "__main__":
    unittest.main()
