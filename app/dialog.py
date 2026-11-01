"""对话编排：检索记忆 -> 组装人设 Prompt -> 生成回复。"""

from . import config, embedder, llm
from . import memory as memory_mod
from . import persona as persona_mod
from .embedder import EmbedError
from .http import ApiError
from .store import get_store

ROLE_WHITELIST = {"user", "assistant"}


def retrieve_memories(message: str, top_k: int | None = None) -> tuple[list, str]:
    """检索与当前话题相关的原文片段。检索失败不应该让对话直接中断。

    这里要同时接住两类错误：
    - ApiError：向量接口返回了错误
    - EmbedError：压根没配 key（最容易踩的一种，直接打 500 会很难查）
    """
    store = get_store()
    if store.count() == 0:
        return [], ""

    try:
        query_vector = embedder.embed_query(message)
    except (ApiError, EmbedError) as exc:
        return [], str(exc)

    return store.search(query_vector, top_k or config.MEMORY_TOP_K), ""


def reply(
    persona: dict,
    message: str,
    history: list[dict] | None = None,
    top_k: int | None = None,
    temperature: float | None = None,
) -> dict:
    message = (message or "").strip()
    if not message:
        return {
            "reply": "……",
            "name": persona.get("name", ""),
            "memories": [],
            "memory_error": "",
            "remembered": [],
            "memory_total": 0,
        }

    memories, memory_error = retrieve_memories(message, top_k)

    # 长期记忆：对方以前说过的事（跨会话保留）
    name = persona.get("name", "")
    facts = memory_mod.select_for_prompt(memory_mod.load_facts(name))

    system_prompt = persona_mod.build_system_prompt(persona, memories, facts)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # 只保留最近若干轮，防止上下文无限增长
    trimmed = (history or [])[-config.HISTORY_TURNS * 2 :]
    for turn in trimmed:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ROLE_WHITELIST and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": message})

    text = llm.chat(messages, temperature=temperature)

    # 回复已经拿到了，再从这一轮里提炼值得记住的事。失败不影响对话。
    remembered = {"added": 0, "updated": 0, "new": []}
    if config.MEMORY_EXTRACT:
        remembered = memory_mod.remember(name, message, text)

    return {
        "reply": text,
        "name": name,
        "memories": [
            {
                "text": hit.text[:160] + ("…" if len(hit.text) > 160 else ""),
                "location": (hit.metadata or {}).get("location", ""),
                "score": round(hit.score, 4),
            }
            for hit in memories
        ],
        "memory_error": memory_error,
        "remembered": remembered.get("new", []),
        "memory_total": len(memory_mod.load_facts(name)),
    }
