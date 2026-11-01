"""FastAPI 入口。

启动：uvicorn app.main:app --reload
"""

import shutil
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import config, dialog, indexing, sessions
from . import memory as memory_mod
from . import persona as persona_mod
from .http import ApiError

ALLOWED_SUFFIX = {".pdf", ".md", ".txt"}

app = FastAPI(title="小说角色对话", version="0.1.0")


class SourceBody(BaseModel):
    source: str


class BuildPersonaBody(BaseModel):
    source: str
    name: str
    chapter_from: int | None = None
    chapter_to: int | None = None


class ChatBody(BaseModel):
    name: str
    message: str
    history: list[dict] | None = None
    top_k: int | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.WEB_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, **indexing.stats()}


# ---------------- 文档 ----------------

@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(400, f"只支持 {' / '.join(sorted(ALLOWED_SUFFIX))} 格式")

    config.ensure_dirs()
    dest = config.UPLOAD_DIR / Path(file.filename).name
    with dest.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    try:
        result = indexing.ingest_file(dest)
    except ApiError as exc:
        raise HTTPException(502, str(exc)) from exc

    return {**result, "text_chars": len(indexing.read_source_text(dest))}


@app.get("/documents")
def documents() -> list[dict]:
    return indexing.list_documents()


@app.delete("/documents/{name}")
def delete_document(name: str) -> dict:
    return {"source": name, "deleted": indexing.delete_document(name)}


# ---------------- 角色 ----------------

@app.post("/characters")
def characters(body: SourceBody) -> dict:
    path = config.UPLOAD_DIR / Path(body.source).name
    if not path.exists():
        raise HTTPException(404, f"找不到已上传的文档：{body.source}")
    try:
        items = persona_mod.list_characters(indexing.read_source_text(path))
    except ApiError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"characters": items}


@app.get("/chapters")
def chapters(source: str) -> dict:
    path = config.UPLOAD_DIR / Path(source).name
    if not path.exists():
        raise HTTPException(404, f"找不到已上传的文档：{source}")
    items = persona_mod.list_chapters(indexing.read_source_text(path))
    return {"count": len(items), "chapters": items}


@app.post("/persona")
def build_persona(body: BuildPersonaBody) -> dict:
    path = config.UPLOAD_DIR / Path(body.source).name
    if not path.exists():
        raise HTTPException(404, f"找不到已上传的文档：{body.source}")
    try:
        persona = persona_mod.extract_persona(
            indexing.read_source_text(path), body.name, body.chapter_from, body.chapter_to
        )
    except ApiError as exc:
        raise HTTPException(502, str(exc)) from exc
    persona_mod.save_persona(persona)
    return persona


@app.get("/personas")
def personas() -> list[dict]:
    return persona_mod.list_personas()


@app.get("/persona/{name}")
def get_persona(name: str) -> dict:
    try:
        return persona_mod.load_persona(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.delete("/persona/{name}")
def delete_persona(name: str, purge: bool = False) -> dict:
    """删除角色卡。purge=true 时连带聊天记录和长期记忆一起删。"""
    try:
        path = persona_mod.persona_path(name)
    except Exception as exc:  # pragma: no cover - 名字异常时直接拒绝
        raise HTTPException(400, str(exc)) from exc

    existed = path.exists()
    if existed:
        path.unlink()

    purged = {"session": False, "memory": False}
    if purge:
        purged["session"] = sessions.clear_session(name)
        purged["memory"] = memory_mod.clear_facts(name)

    if not existed:
        raise HTTPException(404, f"角色卡不存在：{name}")
    return {"persona": name, "deleted": True, "purged": purged}


# ---------------- 长期记忆 ----------------

@app.get("/memory/{name}")
def get_memory(name: str) -> dict:
    facts = memory_mod.load_facts(name)
    return {"persona": name, "count": len(facts), "facts": facts}


@app.delete("/memory/{name}")
def clear_memory(name: str) -> dict:
    return {"persona": name, "cleared": memory_mod.clear_facts(name)}


# ---------------- 对话 ----------------

@app.post("/chat")
def chat(body: ChatBody) -> dict:
    try:
        persona = persona_mod.load_persona(body.name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    # 没显式传历史时，从磁盘读上次的对话——这就是"打开就接上"的关键
    history = body.history if body.history is not None else sessions.load_session(body.name)

    try:
        result = dialog.reply(persona, body.message, sessions.strip_ts(history), body.top_k)
    except ApiError as exc:
        raise HTTPException(502, str(exc)) from exc

    sessions.append_turn(body.name, body.message, result["reply"])
    result["history_turns"] = (len(history) + 2) // 2
    return result


# ---------------- 会话记录 ----------------

@app.get("/session/{name}")
def get_session(name: str) -> dict:
    messages = sessions.load_session(name)
    return {"persona": name, "count": len(messages), "messages": messages}


@app.delete("/session/{name}")
def clear_session(name: str) -> dict:
    return {"persona": name, "cleared": sessions.clear_session(name)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
