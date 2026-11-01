"""向量库：默认 Chroma，另带一个纯 Python 的内存实现用于离线测试。

为什么留两个实现：
- Chroma 是简历上要写的工程部分，但它依赖重、还要写盘；
- 测试只关心「检索逻辑对不对」，用内存实现能完全离线跑，CI 里不需要装 Chroma。
"""

import math
from typing import Iterable

from . import config
from .loader import Chunk


class SearchHit:
    def __init__(self, text: str, metadata: dict, score: float):
        self.text = text
        self.metadata = metadata
        self.score = score

    def to_dict(self) -> dict:
        return {"text": self.text, "metadata": self.metadata, "score": round(self.score, 4)}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class MemoryStore:
    """纯 Python 实现，适合小数据量和测试。"""

    def __init__(self):
        self._items: list[dict] = []

    def add(self, chunks: Iterable[Chunk], vectors: list[list[float]]) -> int:
        # 与 Chroma 的 upsert 语义保持一致：同 id 覆盖，不产生重复片段
        position = {item["id"]: i for i, item in enumerate(self._items)}
        added = 0
        for chunk, vector in zip(chunks, vectors):
            chunk_id = f"{chunk.metadata.get('source')}#{chunk.metadata.get('chunk_index')}"
            entry = {
                "id": chunk_id,
                "text": chunk.text,
                "metadata": chunk.metadata,
                "vector": vector,
            }
            if chunk_id in position:
                self._items[position[chunk_id]] = entry
            else:
                position[chunk_id] = len(self._items)
                self._items.append(entry)
            added += 1
        return added

    def search(self, vector: list[float], top_k: int = 4) -> list[SearchHit]:
        scored = [
            SearchHit(item["text"], item["metadata"], _cosine(vector, item["vector"]))
            for item in self._items
        ]
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:top_k]

    def delete_source(self, source: str) -> int:
        before = len(self._items)
        self._items = [i for i in self._items if i["metadata"].get("source") != source]
        return before - len(self._items)

    def sources(self) -> list[dict]:
        summary: dict[str, int] = {}
        for item in self._items:
            name = item["metadata"].get("source", "未知")
            summary[name] = summary.get(name, 0) + 1
        return [{"source": k, "chunks": v} for k, v in sorted(summary.items())]

    def count(self) -> int:
        return len(self._items)


class ChromaStore:
    def __init__(self):
        try:
            import chromadb  # 延迟导入
        except ImportError as exc:
            raise RuntimeError(
                "没有安装 chromadb。请执行 pip install -r requirements.txt；"
                "只想先试跑的话，设置环境变量 STORE_BACKEND=memory（数据不落盘）。"
            ) from exc

        config.ensure_dirs()
        self._client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        self._collection = self._client.get_or_create_collection(
            name=config.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, chunks: Iterable[Chunk], vectors: list[list[float]]) -> int:
        ids, documents, metadatas = [], [], []
        for chunk, _vector in zip(chunks, vectors):
            ids.append(f"{chunk.metadata.get('source')}#{chunk.metadata.get('chunk_index')}")
            documents.append(chunk.text)
            metadatas.append(
                {
                    "source": chunk.metadata.get("source", ""),
                    "page": int(chunk.metadata.get("page") or 0),
                    "section": chunk.metadata.get("section") or "",
                    "chunk_index": int(chunk.metadata.get("chunk_index") or 0),
                }
            )
        if not ids:
            return 0
        self._collection.upsert(ids=ids, documents=documents, embeddings=vectors, metadatas=metadatas)
        return len(ids)

    def search(self, vector: list[float], top_k: int = 4) -> list[SearchHit]:
        result = self._collection.query(
            query_embeddings=[vector],
            n_results=max(1, top_k),
            include=["documents", "metadatas", "distances"],
        )
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        hits = []
        for text, meta, dist in zip(docs, metas, dists):
            # chroma 用余弦距离，转成相似度更直观
            hits.append(SearchHit(text, meta or {}, 1.0 - float(dist)))
        return hits

    def delete_source(self, source: str) -> int:
        existing = self._collection.get(where={"source": source}, include=[])
        ids = existing.get("ids") or []
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def sources(self) -> list[dict]:
        data = self._collection.get(include=["metadatas"])
        summary: dict[str, int] = {}
        for meta in data.get("metadatas") or []:
            name = (meta or {}).get("source", "未知")
            summary[name] = summary.get(name, 0) + 1
        return [{"source": k, "chunks": v} for k, v in sorted(summary.items())]

    def count(self) -> int:
        return self._collection.count()


_STORE = None


def get_store(force_backend: str | None = None):
    """获取全局存储实例。force_backend='memory' 时跳过 Chroma（测试用）。"""
    global _STORE
    backend = force_backend or config._str("STORE_BACKEND", "chroma")
    if _STORE is None or force_backend:
        _STORE = MemoryStore() if backend == "memory" else ChromaStore()
    return _STORE
