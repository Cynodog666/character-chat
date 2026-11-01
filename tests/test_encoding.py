"""编码与中文章节识别的单测。

这两个问题是拿真实小说（GBK 编码、`第X章` 章节）跑出来的，不是凭空设计的用例。
临时文件写在 tests/_tmp 下，不碰系统临时目录（某些受限环境不可写）。
"""

import shutil
import sys
import uuid
from pathlib import Path

import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.loader import read_text_auto, split_by_heading  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent / "_tmp"


class TempFileMixin(unittest.TestCase):
    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.dir = TMP_ROOT / uuid.uuid4().hex[:8]
        self.dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name: str, data: bytes) -> Path:
        path = self.dir / name
        path.write_bytes(data)
        return path


class TestReadTextAuto(TempFileMixin):
    def test_reads_utf8(self):
        path = self.write("a.txt", "第一章 化冻\n\n那年的地，是二月末的一天早上化开的。".encode("utf-8"))
        self.assertIn("化冻", read_text_auto(path))

    def test_reads_gbk(self):
        # 中文小说 txt 大量是 GBK；按 UTF-8 读不报错，只会得到一屏乱码
        content = "第一章 化冻\n\n陆卫东蹲在院里劈柴。"
        path = self.write("gbk.txt", content.encode("gb18030"))
        text = read_text_auto(path)
        self.assertIn("陆卫东", text)
        self.assertIn("劈柴", text)

    def test_strips_bom(self):
        # 直接写 BOM 字节，避免 utf-8-sig 编码时重复添加
        path = self.write("bom.txt", b"\xef\xbb\xbf" + "第一章".encode("utf-8"))
        self.assertTrue(read_text_auto(path).startswith("第一章"))


class TestChineseChapterSplit(unittest.TestCase):
    def test_detects_basic_chapters(self):
        text = "第一章 化冻\n正文一。\n\n第二章 拾掇\n正文二。"
        titles = [t for t, _ in split_by_heading(text)]
        self.assertIn("第一章 化冻", titles)
        self.assertIn("第二章 拾掇", titles)

    def test_detects_numbered_prefix(self):
        text = "1、第一章 化冻\n正文一。\n\n2、第二章 拾掇\n正文二。"
        titles = [t for t, _ in split_by_heading(text)]
        self.assertTrue(any("第一章" in t for t in titles))
        self.assertTrue(any("第二章" in t for t in titles))

    def test_detects_volume(self):
        text = "第三卷 风起\n正文。"
        titles = [t for t, _ in split_by_heading(text)]
        self.assertTrue(any("第三卷" in t for t in titles))

    def test_markdown_still_works(self):
        text = "# 书名\n前言。\n\n## 第一章\n正文。"
        titles = [t for t, _ in split_by_heading(text)]
        self.assertIn("书名", titles)
        self.assertIn("第一章", titles)

    def test_inline_chapter_word_not_heading(self):
        # 「第一章」出现在句子中间不算标题；前面那句应归入无标题的前言段
        text = "他翻开那本书的第一章，看了很久。\n\n第二章 化冻\n正文。"
        sections = split_by_heading(text)
        titles = [t for t, _ in sections]
        self.assertEqual(titles, ["", "第二章 化冻"])
        self.assertIn("看了很久", sections[0][1])

    def test_no_heading_returns_single_section(self):
        sections = split_by_heading("只有正文，没有任何章节标题。")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0][0], "")


if __name__ == "__main__":
    unittest.main()
