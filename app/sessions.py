"""会话持久化：聊天记录存到磁盘，重开页面能接上。

和长期记忆的分工：
- 会话记录：**原样保存对话流水**，用来恢复界面和给模型提供上下文
- 长期记忆：从对话里**提炼事实**，用来跨越很长的对话

两者都存盘，但用途不同。会话记录会随对话变长而裁剪，长期记忆是精选后的结论。
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import config

MAX_MESSAGES = 400


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def session_path(persona_name: str) -> Path:
    safe = re.sub(r"[\\/:*?\"<>|]", "_", persona_name)
    return config.SESSION_DIR / f"{safe}.json"


def load_session(persona_name: str) -> list[dict]:
    path = session_path(persona_name)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        messages = data.get("messages")
    else:
        messages = data
    if not isinstance(messages, list):
        return []
    return [
        {"role": m["role"], "content": m["content"], "ts": m.get("ts", "")}
        for m in messages
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
    ]


def save_session(persona_name: str, messages: list[dict]) -> Path:
    config.ensure_dirs()
    path = session_path(persona_name)
    trimmed = messages[-MAX_MESSAGES:]
    path.write_text(
        json.dumps({"persona": persona_name, "messages": trimmed}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def append_turn(persona_name: str, user_message: str, assistant_message: str) -> list[dict]:
    """追加一轮对话并落盘，返回完整的会话记录。"""
    messages = load_session(persona_name)
    messages.append({"role": "user", "content": user_message, "ts": _now()})
    messages.append({"role": "assistant", "content": assistant_message, "ts": _now()})
    save_session(persona_name, messages)
    return messages


def clear_session(persona_name: str) -> bool:
    path = session_path(persona_name)
    if path.exists():
        path.unlink()
        return True
    return False


def strip_ts(messages: list[dict]) -> list[dict]:
    """给模型用时去掉时间戳，只留 role/content。"""
    return [{"role": m["role"], "content": m["content"]} for m in messages]
