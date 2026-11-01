"""切分逻辑的离线单测（只用标准库，不联网、不装包）。

运行：python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.loader import chunk_text, describe_location, normalize, split_by_heading  # noqa: E402


class TestChunkText(unittest.TestCase):
    def test_short_text_not_split(self):
        self.assertEqual(len(chunk_text("很短的一句话。", 512, 64)), 1)

    def test_long_text_is_split(self):
        text = "这是一个用于测试的句子。" * 200
        chunks = chunk_text(text, 200, 40)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 240)

    def test_chunks_cover_all_content(self):
        text = "第一段内容在这里。" * 5 + "第二段内容在这里。" * 5
        chunks = chunk_text(text, 60, 10)
        merged = "".join(chunks)
        # 有重叠，所以合并后长度不小于原文
        self.assertGreaterEqual(len(merged), len(normalize(text)))

    def test_prefers_sentence_boundary(self):
        text = "甲" * 100 + "。" + "乙" * 100
        chunks = chunk_text(text, 120, 10)
        # 第一块应该在句号处断开，而不是从 120 处硬切
        self.assertTrue(chunks[0].endswith("。"))

    def test_empty_text(self):
        self.assertEqual(chunk_text("", 512, 64), [])
        self.assertEqual(chunk_text("   \n\n  ", 512, 64), [])


class TestSplitByHeading(unittest.TestCase):
    def test_with_headings(self):
        md = "# 一、概述\n正文一\n\n## 二、细节\n正文二"
        sections = split_by_heading(md)
        titles = [t for t, _ in sections]
        self.assertIn("一、概述", titles)
        self.assertIn("二、细节", titles)
        self.assertEqual(sections[0][1].strip(), "正文一")

    def test_without_heading(self):
        sections = split_by_heading("只有正文，没有标题。")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0][0], "")


class TestDescribeLocation(unittest.TestCase):
    def test_page_wins(self):
        self.assertEqual(
            describe_location({"source": "a.pdf", "page": 3, "section": ""}),
            "a.pdf 第 3 页",
        )

    def test_section_used_without_page(self):
        self.assertEqual(
            describe_location({"source": "b.md", "page": 0, "section": "套餐"}),
            "b.md · 套餐",
        )

    def test_source_only(self):
        self.assertEqual(describe_location({"source": "c.txt"}), "c.txt")


if __name__ == "__main__":
    unittest.main()
