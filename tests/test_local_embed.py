"""本地 bigram 向量的单测。

它存在的意义只有一个：没有 embedding 接口时让流程能跑。
所以要验的不是"准"，而是"稳定"和"至少有点词面相似度"。
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.embedder import backend, local_embed, local_embed_texts  # noqa: E402


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class TestLocalEmbed(unittest.TestCase):
    def test_deterministic(self):
        # 跨进程必须一致，否则存进向量库的在下次启动时就对不上了
        a = local_embed("魏谦蹲在院里劈柴")
        b = local_embed("魏谦蹲在院里劈柴")
        self.assertEqual(a, b)

    def test_unit_norm(self):
        vec = local_embed("那年的地，是二月末的一天早上化开的。")
        norm = math.sqrt(sum(v * v for v in vec))
        self.assertAlmostEqual(norm, 1.0, places=6)

    def test_empty_text(self):
        vec = local_embed("")
        self.assertEqual(len(vec), 2048)
        self.assertEqual(sum(vec), 0.0)

    def test_similar_texts_closer_than_unrelated(self):
        base = local_embed("魏谦蹲在院里劈柴，斧子起落")
        near = local_embed("魏谦在院子里劈柴")
        far = local_embed("今天的天气很好，适合出去走走")
        self.assertGreater(cosine(base, near), cosine(base, far))

    def test_batch_matches_single(self):
        texts = ["第一段", "第二段"]
        batch = local_embed_texts(texts)
        self.assertEqual(batch[0], local_embed(texts[0]))
        self.assertEqual(batch[1], local_embed(texts[1]))


class TestBackendSelection(unittest.TestCase):
    def test_explicit_local(self):
        from app import config

        old = config.EMBED_BACKEND
        try:
            config.EMBED_BACKEND = "local"
            self.assertEqual(backend(), "local")
        finally:
            config.EMBED_BACKEND = old

    def test_explicit_api(self):
        from app import config

        old = config.EMBED_BACKEND
        try:
            config.EMBED_BACKEND = "api"
            self.assertEqual(backend(), "api")
        finally:
            config.EMBED_BACKEND = old


if __name__ == "__main__":
    unittest.main()
