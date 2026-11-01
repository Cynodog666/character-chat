"""入库：解析 -> 切分 -> 向量化 -> 存库。"""

from pathlib import Path

from . import config, embedder, loader
from .store import get_store


def ingest_file(path: str | Path) -> dict:
    path = Path(path)
    chunks = loader.load_file(path, config.CHUNK_SIZE, config.CHUNK_OVERLAP)
    if not chunks:
        return {"source": path.name, "chunks": 0, "added": 0, "replaced": 0, "skipped": True}

    for chunk in chunks:
        chunk.metadata["location"] = loader.describe_location(chunk.metadata)

    vectors = embedder.embed_texts([c.text for c in chunks])
    store = get_store()

    # 同一份文件重复上传时先清掉旧的，避免出现重复片段
    replaced = store.delete_source(path.name)
    added = store.add(chunks, vectors)

    return {
        "source": path.name,
        "chunks": len(chunks),
        "added": added,
        "replaced": replaced,
    }


def read_source_text(path: str | Path) -> str:
    """读取整篇原文，用于抽取角色卡（不需要切分）。"""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return "\n\n".join(text for _page, text in loader.read_pdf(path))
    return loader.read_text_auto(path)


def list_documents() -> list[dict]:
    return get_store().sources()


def delete_document(source: str) -> int:
    return get_store().delete_source(source)


def stats() -> dict:
    store = get_store()
    return {
        "chunks": store.count(),
        "documents": len(store.sources()),
        "chunk_size": config.CHUNK_SIZE,
        "chunk_overlap": config.CHUNK_OVERLAP,
        "memory_top_k": config.MEMORY_TOP_K,
        "embed_model": config.EMBED_MODEL,
        "chat_model": config.CHAT_MODEL,
    }
