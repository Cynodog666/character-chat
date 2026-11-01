"""长期记忆的单测：抽取解析、去重覆盖、存取、注入裁剪。

重点验冲突消解：同一主题说两次，不能变成两条互相矛盾的事实，
否则角色会左右横跳。
"""

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, memory  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent / "_tmp"


class TestNormalizeTopic(unittest.TestCase):
    def test_strips_whitespace_and_lower(self):
        self.assertEqual(memory.normalize_topic(" 我的 名字 "), "我的名字")
        self.assertEqual(memory.normalize_topic("User Name"), "username")


class TestUpsertAndStore(unittest.TestCase):
    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.dir = TMP_ROOT / uuid.uuid4().hex[:8]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.old = config.MEMORY_DIR
        config.MEMORY_DIR = self.dir
        self.name = "测试角色"

    def tearDown(self):
        config.MEMORY_DIR = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_adds_new_facts(self):
        result = memory.upsert_facts(self.name, [
            {"topic": "称呼", "content": "对方叫小张"},
            {"topic": "职业", "content": "对方做前端"},
        ])
        self.assertEqual(result["added"], 2)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(memory.load_facts(self.name)), 2)

    def test_same_topic_overwrites(self):
        memory.upsert_facts(self.name, [{"topic": "称呼", "content": "对方叫小张"}])
        result = memory.upsert_facts(self.name, [{"topic": "称呼", "content": "对方改叫小李"}])

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["added"], 0)
        self.assertEqual(result["total"], 1)
        self.assertEqual(memory.load_facts(self.name)[0]["content"], "对方改叫小李")

    def test_same_content_not_counted_as_update(self):
        memory.upsert_facts(self.name, [{"topic": "称呼", "content": "对方叫小张"}])
        result = memory.upsert_facts(self.name, [{"topic": "称呼", "content": "对方叫小张"}])
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["added"], 0)

    def test_blank_content_skipped(self):
        result = memory.upsert_facts(self.name, [{"topic": "空", "content": "   "}])
        self.assertEqual(result["added"], 0)
        self.assertEqual(memory.load_facts(self.name), [])

    def test_clear(self):
        memory.upsert_facts(self.name, [{"topic": "称呼", "content": "对方叫小张"}])
        self.assertTrue(memory.clear_facts(self.name))
        self.assertEqual(memory.load_facts(self.name), [])
        self.assertFalse(memory.clear_facts(self.name))

    def test_isolated_per_persona(self):
        memory.upsert_facts("甲", [{"topic": "称呼", "content": "甲记得的事"}])
        memory.upsert_facts("乙", [{"topic": "称呼", "content": "乙记得的事"}])
        self.assertEqual(memory.load_facts("甲")[0]["content"], "甲记得的事")
        self.assertEqual(memory.load_facts("乙")[0]["content"], "乙记得的事")

    def test_missing_file_returns_empty(self):
        self.assertEqual(memory.load_facts("不存在的角色"), [])

    def test_corrupted_file_returns_empty(self):
        path = memory.memory_path(self.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ 这不是 json", encoding="utf-8")
        self.assertEqual(memory.load_facts(self.name), [])

    def test_store_capped(self):
        old = config.MEMORY_MAX_FACTS
        config.MEMORY_MAX_FACTS = 5
        try:
            facts = [{"topic": f"主题{i}", "content": f"内容{i}"} for i in range(20)]
            memory.upsert_facts(self.name, facts)
            self.assertEqual(len(memory.load_facts(self.name)), 5)
        finally:
            config.MEMORY_MAX_FACTS = old


class TestSelectForPrompt(unittest.TestCase):
    def test_limits_and_prefers_recent(self):
        facts = [{"content": f"第{i}条", "updated_at": f"2026-01-{i:02d}"} for i in range(1, 21)]
        picked = memory.select_for_prompt(facts, limit=3)
        self.assertEqual(len(picked), 3)
        self.assertEqual([f["content"] for f in picked], ["第18条", "第19条", "第20条"])


class TestParseJsonArray(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(
            memory._parse_json_array('[{"topic":"a","content":"b"}]'),
            [{"topic": "a", "content": "b"}],
        )

    def test_code_fence(self):
        raw = '```json\n[{"topic":"a","content":"b"}]\n```'
        self.assertEqual(memory._parse_json_array(raw), [{"topic": "a", "content": "b"}])

    def test_with_prefix_text(self):
        raw = '好的：\n[{"topic":"a","content":"b"}]\n以上。'
        self.assertEqual(memory._parse_json_array(raw), [{"topic": "a", "content": "b"}])

    def test_empty_array(self):
        self.assertEqual(memory._parse_json_array("[]"), [])

    def test_garbage_returns_empty(self):
        self.assertEqual(memory._parse_json_array("完全不是 JSON"), [])

    def test_object_instead_of_array(self):
        self.assertEqual(memory._parse_json_array('{"a":1}'), [])


class TestRenderForPrompt(unittest.TestCase):
    def test_renders_bullets(self):
        text = memory.render_for_prompt([{"content": "对方叫小张"}, {"content": "对方做前端"}])
        self.assertIn("- 对方叫小张", text)
        self.assertIn("- 对方做前端", text)

    def test_empty(self):
        self.assertEqual(memory.render_for_prompt([]), "")


if __name__ == "__main__":
    unittest.main()
