"""长期记忆：让角色记住「你」说过的话。

和 RAG 检索的区别：
- 检索记忆搜的是**原著里的往事**（小说写过什么）
- 这里记的是**你们之间发生过的事**（你说过什么）

三层结构：
1. 抽取 —— 每轮结束后从对话里提炼稳定的、值得长期记住的事实
2. 存储 —— 按角色分文件存 JSON；主题相同则覆盖（这就是冲突消解）
3. 注入 —— 拼进 system prompt，语气上当成"你记得的事"，不是数据条目

为什么用「主题」而不是直接存句子：
同一件事说两次（"我叫小张" / "其实我叫小李"），如果没有主题键，
就会变成两条互相矛盾的事实，角色会左右横跳。有主题键才能覆盖。
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .http import ApiError
from .llm import chat

EXTRACT_SYSTEM = (
    "你是记忆整理助手。你只输出 JSON 数组，不要解释，不要代码块。"
)

EXTRACT_TEMPLATE = """从下面这段对话里，抽取「对方」说的、值得长期记住的事实。

只抽这几类：
- 称呼与身份：名字、希望被怎么叫、职业、年龄、所在地
- 稳定的偏好与厌恶
- 重要的经历或处境
- 和角色的约定、承诺

不要抽：
- 一次性的情绪或感叹
- 关于角色自己的描述（那是角色的事）
- 你自己推测出来的东西

已有的主题（如果能归到其中之一，请复用这个 topic，内容会被覆盖更新）：
{topics}

对话：
对方：{user}
角色：{reply}

输出 JSON 数组，每项 {{"topic": "简短主题", "content": "一句话事实"}}。
没有值得记的就输出 []。
"""

TOPIC_CLEAN_RE = re.compile(r"\s+")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def memory_path(persona_name: str) -> Path:
    safe = re.sub(r"[\\/:*?\"<>|]", "_", persona_name)
    return config.MEMORY_DIR / f"{safe}.json"


def normalize_topic(topic: str) -> str:
    return TOPIC_CLEAN_RE.sub("", (topic or "").strip()).lower()


def load_facts(persona_name: str) -> list[dict]:
    path = memory_path(persona_name)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    facts = data.get("facts") if isinstance(data, dict) else None
    return [f for f in (facts or []) if isinstance(f, dict) and f.get("content")]


def save_facts(persona_name: str, facts: list[dict]) -> Path:
    config.ensure_dirs()
    path = memory_path(persona_name)
    # 只保留最近的一批，避免越攒越多、把 prompt 撑爆
    facts = facts[-config.MEMORY_MAX_FACTS :]
    path.write_text(
        json.dumps({"persona": persona_name, "facts": facts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def upsert_facts(persona_name: str, new_facts: list[dict]) -> dict:
    """写入事实。主题相同视为更新，不同视为新增。"""
    existing = load_facts(persona_name)
    by_topic = {normalize_topic(f.get("topic", "")): f for f in existing}

    added = updated = 0
    now = _now()

    for fact in new_facts:
        content = (fact.get("content") or "").strip()
        topic = (fact.get("topic") or "").strip() or content[:12]
        if not content:
            continue

        key = normalize_topic(topic)
        record = {"topic": topic, "content": content, "updated_at": now}

        if key in by_topic:
            old = by_topic[key]["content"]
            if old != content:
                updated += 1
            by_topic[key] = record
        else:
            added += 1
            by_topic[key] = record

    facts = sorted(by_topic.values(), key=lambda f: f.get("updated_at", ""))
    save_facts(persona_name, facts)
    return {"added": added, "updated": updated, "total": len(facts)}


def clear_facts(persona_name: str) -> bool:
    path = memory_path(persona_name)
    if path.exists():
        path.unlink()
        return True
    return False


def select_for_prompt(facts: list[dict], limit: int | None = None) -> list[dict]:
    """挑出要注入 prompt 的事实：优先最近的。"""
    limit = limit or config.MEMORY_MAX_INJECT
    return facts[-limit:]


def extract_facts(user_message: str, reply: str, existing: list[dict]) -> list[dict]:
    """让模型从这一轮对话里提炼事实。失败时返回空列表，不影响对话。"""
    topics = [f.get("topic", "") for f in existing if f.get("topic")]
    topic_hint = "、".join(topics[-20:]) if topics else "（暂无）"

    raw = chat(
        [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {
                "role": "user",
                "content": EXTRACT_TEMPLATE.format(
                    topics=topic_hint, user=user_message, reply=reply
                ),
            },
        ],
        temperature=0,
    )

    data = _parse_json_array(raw)
    result = []
    for item in data:
        if isinstance(item, dict) and item.get("content"):
            result.append(
                {
                    "topic": str(item.get("topic") or "").strip(),
                    "content": str(item.get("content")).strip(),
                }
            )
    return result


def _parse_json_array(text: str) -> list:
    cleaned = (text or "").strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if match:
        cleaned = match.group(1).strip()

    try:
        data = json.loads(cleaned)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        pass

    start, end = cleaned.find("["), cleaned.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
    return []


def remember(persona_name: str, user_message: str, reply: str) -> dict:
    """一轮对话结束后调用：抽取并写入。任何异常都不应影响主流程。"""
    try:
        existing = load_facts(persona_name)
        facts = extract_facts(user_message, reply, existing)
        if not facts:
            return {"added": 0, "updated": 0, "total": len(existing), "new": []}
        result = upsert_facts(persona_name, facts)
        result["new"] = facts
        return result
    except (ApiError, OSError, ValueError):
        return {"added": 0, "updated": 0, "total": 0, "new": [], "skipped": True}


def render_for_prompt(facts: list[dict]) -> str:
    if not facts:
        return ""
    lines = [f"- {f['content']}" for f in facts]
    return "\n".join(lines)
