"""回答生成：把检索到的片段拼进 Prompt，约束模型只依据资料作答。"""

from . import config
from .http import ApiError, post_json


SYSTEM_PROMPT = (
    "你是文档问答助手。请严格依据用户提供的【资料】回答问题。\n"
    "规则：\n"
    "1. 只能使用资料中的信息，不得引入资料以外的知识。\n"
    "2. 资料中没有答案时，直接回答「资料中没有提到相关内容」，不要猜测。\n"
    "3. 回答简洁准确；如涉及多个要点，用列表分条呈现。\n"
    "4. 不要在回答里自己编造出处编号，出处由系统统一展示。"
)


def chat(messages: list[dict], temperature: float | None = None) -> str:
    payload = {
        "model": config.CHAT_MODEL,
        "messages": messages,
        "temperature": config.CHAT_TEMPERATURE if temperature is None else temperature,
        "stream": False,
    }
    data = post_json(
        config.CHAT_API_URL,
        payload,
        config.CHAT_API_KEY,
        service="对话模型",
    )
    choices = data.get("choices") or []
    if not choices:
        raise ApiError("对话模型没有返回 choices")
    return (choices[0].get("message") or {}).get("content", "").strip()


def build_context(hits) -> str:
    """把检索结果编号后拼成资料块。"""
    lines = []
    for i, hit in enumerate(hits, start=1):
        meta = hit.metadata or {}
        location = meta.get("location") or meta.get("source", "未知文档")
        lines.append(f"[{i}] 出处：{location}\n{hit.text}")
    return "\n\n".join(lines)


def answer_with_context(question: str, hits) -> str:
    context = build_context(hits)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"【资料】\n{context}\n\n【问题】\n{question}"},
    ]
    return chat(messages)


def answer_without_context(question: str) -> str:
    """对照组：不带检索直接问模型，用于评测 RAG 到底有没有用。"""
    messages = [
        {"role": "system", "content": "你是一个乐于助人的中文助手，回答尽量简洁。"},
        {"role": "user", "content": question},
    ]
    return chat(messages)
