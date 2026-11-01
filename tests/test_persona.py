"""角色卡相关逻辑的离线单测（不联网）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import persona as persona_mod  # noqa: E402


SAMPLE_PERSONA = {
    "name": "老周",
    "identity": "镇口的修鞋匠",
    "age_range": "六十出头",
    "personality": ["沉默", "认死理", "嘴硬心软"],
    "speech_style": "句子短，爱用反问，不主动多说",
    "catchphrases": ["急什么，鞋又不会跑"],
    "relationships": [
        {"who": "林小满", "relation": "常来修鞋的年轻老师", "attitude": "嘴上不热络，心里记着"},
        {"who": "", "relation": "空关系应被过滤", "attitude": ""},
    ],
    "knows": ["自己摆了二十三年摊", "儿子在南边修船"],
    "does_not_know": ["儿子的具体地址", "林小满为什么来镇上"],
    "example_lines": ["急什么，鞋又不会跑。", "该多少是多少。"],
    "taboos": ["儿子的事"],
}


class TestNormalizePersona(unittest.TestCase):
    def test_strings_become_lists(self):
        raw = {"name": "甲", "personality": "沉默", "knows": None}
        result = persona_mod.normalize_persona(raw)
        self.assertEqual(result["personality"], ["沉默"])
        self.assertEqual(result["knows"], [])

    def test_relationships_filtered(self):
        result = persona_mod.normalize_persona(SAMPLE_PERSONA)
        self.assertEqual(len(result["relationships"]), 1)
        self.assertEqual(result["relationships"][0]["who"], "林小满")

    def test_missing_fields_get_defaults(self):
        result = persona_mod.normalize_persona({"name": "甲"})
        for key in ("aliases", "personality", "catchphrases", "knows", "does_not_know",
                    "example_lines", "taboos"):
            self.assertEqual(result[key], [])
        self.assertEqual(result["identity"], "")


class TestBuildSystemPrompt(unittest.TestCase):
    def setUp(self):
        self.persona = persona_mod.normalize_persona(SAMPLE_PERSONA)
        self.prompt = persona_mod.build_system_prompt(self.persona)

    def test_contains_identity(self):
        self.assertIn("老周", self.prompt)
        self.assertIn("修鞋匠", self.prompt)

    def test_contains_example_lines(self):
        self.assertIn("急什么，鞋又不会跑。", self.prompt)

    def test_contains_style_rules(self):
        self.assertIn("第一人称", self.prompt)
        self.assertIn("不许提", self.prompt)

    def test_full_knowledge_mode_by_default(self):
        # 默认 full：角色知道全书发生的事，能聊任何情节
        self.assertIn("你对这一切的了解", self.prompt)
        self.assertIn("从头到尾你都知道", self.prompt)
        self.assertNotIn("【你不知道的事】", self.prompt)

    def test_book_only_unknowns_still_mentioned(self):
        # 书里完全没写的事仍要说明"只能推测"
        self.assertIn("林小满为什么来镇上", self.prompt)
        self.assertIn("只能按你的性子推测", self.prompt)

    def test_perspective_mode_restores_boundary(self):
        from app import config

        old = config.KNOWLEDGE_MODE
        try:
            config.KNOWLEDGE_MODE = "perspective"
            prompt = persona_mod.build_system_prompt(self.persona)
            self.assertIn("【你不知道的事】", prompt)
            self.assertIn("按你的性子带过去或反问", prompt)
        finally:
            config.KNOWLEDGE_MODE = old

    def test_memories_injected(self):
        class Hit:
            text = "他儿子在南边修船。"

        prompt = persona_mod.build_system_prompt(self.persona, [Hit()])
        self.assertIn("他儿子在南边修船。", prompt)

    def test_no_memories_section_when_empty(self):
        self.assertNotIn("你记得的这些事", self.prompt)


class TestCollectMaterial(unittest.TestCase):
    def test_prioritises_paragraphs_with_name(self):
        # 单层取样下只比分数：提到角色的段落优先于更短的无关段落
        text = "\n".join([
            "与角色无关的废话一。",
            "老周坐在马扎上，手里捏着鞋底。",
            "又一段无关的描写。",
        ])
        material = persona_mod.collect_material(text, "老周", budget=20, strata=1)
        self.assertIn("老周", material)
        self.assertNotIn("无关的废话", material)

    def test_respects_budget(self):
        text = "\n".join("老周说话第%d段。" % i for i in range(50))
        material = persona_mod.collect_material(text, "老周", budget=200)
        self.assertLessEqual(len(material), 220)

    def test_keeps_original_order(self):
        text = "\n".join(["老周甲句。", "老周乙句。", "老周丙句。"])
        material = persona_mod.collect_material(text, "老周", budget=500)
        self.assertLess(material.index("甲句"), material.index("乙句"))
        self.assertLess(material.index("乙句"), material.index("丙句"))

    def test_stratified_sampling_reaches_the_end(self):
        # 角色只在前两段被提到，后面全是无关内容。
        # 单层取样会把预算全花在开头；分层后必须能从靠后的位置也取到内容。
        paragraphs = ["老周甲。", "老周乙。"] + [f"很远的地方第{i}段。" for i in range(60)]
        material = persona_mod.collect_material("\n".join(paragraphs), "老周", budget=300)
        tail_hit = any(f"很远的地方第{i}段" in material for i in range(40, 60))
        self.assertTrue(tail_hit, f"取样没有覆盖到后段：{material[:80]}…")

    def test_empty_text(self):
        self.assertEqual(persona_mod.collect_material("", "老周"), "")


class TestStripFrontMatter(unittest.TestCase):
    def test_removes_short_untitled_prefix(self):
        text = "《某某》作者：某某\n文案：这是一个关于……\n\n第一章 开场\n正文开始。"
        cleaned = persona_mod.strip_front_matter(text)
        self.assertNotIn("文案", cleaned)
        self.assertIn("第一章 开场", cleaned)

    def test_keeps_text_without_headings(self):
        text = "只有一段正文，没有任何章节标题。"
        self.assertEqual(persona_mod.strip_front_matter(text), text)

    def test_keeps_long_prefix(self):
        # 前言很长时说明它本身就是正文内容，不能删
        body = "正文内容。" * 400
        text = body + "\n\n第一章 开场\n正文。"
        self.assertTrue(persona_mod.strip_front_matter(text).startswith("正文内容。"))


class TestParseJson(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(persona_mod._parse_json('{"a": 1}'), {"a": 1})

    def test_code_fence(self):
        raw = '```json\n{"a": 1}\n```'
        self.assertEqual(persona_mod._parse_json(raw), {"a": 1})

    def test_with_leading_text(self):
        raw = '好的，结果如下：\n{"a": 1}\n以上。'
        self.assertEqual(persona_mod._parse_json(raw), {"a": 1})

    def test_array(self):
        self.assertEqual(persona_mod._parse_json('[{"name": "甲"}]'), [{"name": "甲"}])

    def test_invalid_raises(self):
        from app.http import ApiError

        with self.assertRaises(ApiError):
            persona_mod._parse_json("完全不是 JSON")


if __name__ == "__main__":
    unittest.main()
