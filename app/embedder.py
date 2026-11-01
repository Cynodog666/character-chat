"""向量化：调用 OpenAI 兼容的 embeddings 接口。

用标准库 urllib 而不是 requests，少一个依赖；出问题时把服务端的错误原文带出来，
不然只会看到一句 "400 Bad Request"，排查很痛苦。
"""

import hashlib
import math
import re
import zlib

from . import config
from .http import ApiError, post_json

LOCAL_DIM = 2048


class EmbedError(RuntimeError):
    pass


def backend() -> str:
    """决定用哪个向量后端。

    auto：配了 EMBED_API_KEY 就走接口，没配就退化为本地 bigram。
    这样只配一个对话模型的 key 也能把整个流程跑起来，先看效果再决定要不要接真模型。
    """
    explicit = (config.EMBED_BACKEND or "auto").lower()
    if explicit in ("api", "local"):
        return explicit
    return "api" if config.EMBED_API_KEY else "local"


def local_embed(text: str, dim: int = LOCAL_DIM) -> list[float]:
    """零依赖的本地向量：中文字符 bigram 哈希 + 计数归一化。

    这不是语义向量，它是「词面相似」——共用很多二字组合的文本会靠得近。
    对中文检索来说比随机哈希好得多，但明显弱于 bge 这类真模型。
    用途只有一个：没配 embedding 接口时让流程跑得起来。
    """
    vec = [0.0] * dim
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return vec

    for i in range(len(compact) - 1):
        gram = compact[i : i + 2]
        # 用 crc32 而不是内置 hash()：hash 受 PYTHONHASHSEED 影响，跨进程不稳定
        vec[zlib.crc32(gram.encode("utf-8")) % dim] += 1.0

    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def local_embed_texts(texts: list[str]) -> list[list[float]]:
    return [local_embed(t) for t in texts]


def _post_json(url: str, payload: dict, api_key: str, timeout: int = 60) -> dict:
    try:
        return post_json(url, payload, api_key, service="向量接口", timeout=timeout)
    except ApiError as exc:
        raise EmbedError(str(exc)) from exc


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化，按 EMBED_BATCH 分批，避免单次请求过大。"""
    if not texts:
        return []

    if backend() == "local":
        return local_embed_texts(texts)

    if not config.EMBED_API_KEY:
        raise EmbedError("缺少 EMBED_API_KEY，请在 .env 中填写")

    vectors: list[list[float]] = []
    batch_size = max(1, config.EMBED_BATCH)

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        payload = {"model": config.EMBED_MODEL, "input": batch}
        data = _post_json(config.EMBED_API_URL, payload, config.EMBED_API_KEY)
        items = data.get("data") or []
        if len(items) != len(batch):
            raise EmbedError(
                f"向量数量不匹配：请求 {len(batch)} 条，返回 {len(items)} 条"
            )
        vectors.extend(item["embedding"] for item in items)

    return vectors


def embed_query(text: str) -> list[float]:
    vectors = embed_texts([text])
    if not vectors:
        raise EmbedError("向量接口没有返回结果")
    return vectors[0]


def fake_embed(text: str, dim: int = 64) -> list[float]:
    """确定性的假向量，仅供离线测试用（把文本哈希散列到固定维度）。"""
    vec = [0.0] * dim
    for i in range(0, len(text), 2):
        token = text[i : i + 2]
        digest = hashlib.md5(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "big") % dim
        vec[idx] += 1.0 if digest[2] % 2 == 0 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def fake_embed_texts(texts: list[str]) -> list[list[float]]:
    return [fake_embed(t) for t in texts]
