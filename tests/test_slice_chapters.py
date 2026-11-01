"""章节切片与「知道/不知道」冲突消解的测试。

这两个能力都是为了解决同一个真实问题：
跨越大半生的角色被压成一张卡，导致六岁和二十五岁知道的事混在一起，
甚至同一件事同时出现在 knows 和 does_not_know 里。
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import persona as persona_mod  # noqa: E402

NOVEL = """书名

第一章 化冻
甲内容。

第二章 拾掇
乙内容。

第三章 碾盘
丙内容。
"""


class TestSliceChapters(unittest.TestCase):
    def test_list_chapters(self):
        chapters = persona_mod.list_chapters(NOVEL)
        self.assertEqual(len(chapters), 3)
        self.assertEqual(chapters[0]["index"], 1)
        self.assertIn("第一章", chapters[0]["title"])

    def test_slice_middle_range(self):
        text = persona_mod.slice_chapters(NOVEL, 2, 3)
        self.assertIn("乙内容", text)
        self.assertIn("丙内容", text)
        self.assertNotIn("甲内容", text)

    def test_slice_from_start(self):
        text = persona_mod.slice_chapters(NOVEL, None, 1)
        self.assertIn("甲内容", text)
        self.assertNotIn("乙内容", text)

    def test_no_range_returns_all(self):
        self.assertIn("甲内容", persona_mod.slice_chapters(NOVEL))

    def test_out_of_range_falls_back(self):
        # 范围越界时不应该返回空，否则角色卡会变成空壳
        text = persona_mod.slice_chapters(NOVEL, 99, 200)
        self.assertIn("甲内容", text)

    def test_text_without_chapters_unchanged(self):
        plain = "只有一段正文，没有章节。"
        self.assertEqual(persona_mod.slice_chapters(plain, 1, 2), plain)


class TestResolveConflicts(unittest.TestCase):
    def setUp(self):
        self.persona = persona_mod.normalize_persona(
            {
                "name": "宋小宝",
                "knows": ["魏谦和魏之远的关系", "魏之远被狗咬了"],
                "does_not_know": ["魏之远对魏谦的特殊感情", "老熊和魏谦的谈话内容"],
            }
        )

    def test_drops_conflicting_item(self):
        with mock.patch.object(
            persona_mod, "chat",
            lambda messages, temperature=None: '["魏之远对魏谦的特殊感情"]',
        ):
            result, removed = persona_mod._resolve_conflicts(self.persona)

        self.assertEqual(removed, ["魏之远对魏谦的特殊感情"])
        self.assertNotIn("魏之远对魏谦的特殊感情", result["does_not_know"])
        self.assertIn("老熊和魏谦的谈话内容", result["does_not_know"])
        # knows 不受影响
        self.assertEqual(result["knows"], self.persona["knows"])

    def test_no_conflict_keeps_all(self):
        with mock.patch.object(persona_mod, "chat", lambda messages, temperature=None: "[]"):
            result, removed = persona_mod._resolve_conflicts(self.persona)
        self.assertEqual(removed, [])
        self.assertEqual(result["does_not_know"], self.persona["does_not_know"])

    def test_bad_json_keeps_all(self):
        with mock.patch.object(
            persona_mod, "chat", lambda messages, temperature=None: "不是 JSON"
        ):
            result, removed = persona_mod._resolve_conflicts(self.persona)
        self.assertEqual(removed, [])
        self.assertEqual(len(result["does_not_know"]), 2)

    def test_empty_lists_skip_call(self):
        persona = persona_mod.normalize_persona({"name": "甲", "knows": [], "does_not_know": []})
        with mock.patch.object(persona_mod, "chat", side_effect=AssertionError("不该调用")):
            result, removed = persona_mod._resolve_conflicts(persona)
        self.assertEqual(removed, [])
        self.assertEqual(result, persona)

    def test_fuzzy_match_by_containment(self):
        # 模型可能不完全照抄，只要一端包含另一端也算命中
        with mock.patch.object(
            persona_mod, "chat",
            lambda messages, temperature=None: '["魏之远对魏谦的特殊感情（兄弟情之外）"]',
        ):
            _result, removed = persona_mod._resolve_conflicts(self.persona)
        self.assertEqual(removed, ["魏之远对魏谦的特殊感情"])


if __name__ == "__main__":
    unittest.main()
