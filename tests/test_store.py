"""检索层单测：用假向量 + 内存实现，完全离线。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.embedder import fake_embed  # noqa: E402
from app.loader import Chunk  # noqa: E402
from app.store import MemoryStore  # noqa: E402


def make_chunks() -> list[Chunk]:
    return [
        Chunk("苹果是红色的果子。", {"source": "水果.md", "chunk_index": 0}),
        Chunk("香蕉是黄色的果子。", {"source": "水果.md", "chunk_index": 1}),
        Chunk("云盘免费版提供 5 GB 空间。", {"source": "云盘.md", "chunk_index": 2}),
    ]


class TestMemoryStore(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        chunks = make_chunks()
        self.store.add(chunks, [fake_embed(c.text) for c in chunks])

    def test_count(self):
        self.assertEqual(self.store.count(), 3)

    def test_search_returns_most_similar(self):
        query = fake_embed("云盘免费版提供 5 GB 空间。")
        hits = self.store.search(query, top_k=1)
        self.assertEqual(len(hits), 1)
        self.assertIn("5 GB", hits[0].text)
        self.assertAlmostEqual(hits[0].score, 1.0, places=5)

    def test_search_respects_top_k(self):
        hits = self.store.search(fake_embed("任意文本"), top_k=2)
        self.assertEqual(len(hits), 2)

    def test_sources_grouped(self):
        sources = {item["source"]: item["chunks"] for item in self.store.sources()}
        self.assertEqual(sources["水果.md"], 2)
        self.assertEqual(sources["云盘.md"], 1)

    def test_delete_source(self):
        removed = self.store.delete_source("水果.md")
        self.assertEqual(removed, 2)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.sources(), [{"source": "云盘.md", "chunks": 1}])

    def test_delete_missing_source(self):
        self.assertEqual(self.store.delete_source("不存在.md"), 0)

    def test_add_same_chunk_twice_does_not_duplicate(self):
        # 与 Chroma 的 upsert 语义对齐：同 id 覆盖而不是追加
        chunk = Chunk("云盘免费版提供 5 GB 空间。", {"source": "云盘.md", "chunk_index": 2})
        self.store.add([chunk], [fake_embed(chunk.text)])
        self.assertEqual(self.store.count(), 3)
        self.assertEqual(self.store.search(fake_embed(chunk.text), top_k=1)[0].text, chunk.text)


if __name__ == "__main__":
    unittest.main()
