# -*- coding: utf-8 -*-
"""把电脑端（Python 版）的数据导出成一个 JSON，供纯前端版导入。

导出的内容：
  personas  角色卡
  sessions  聊天记录
  memories  长期记忆

不导出：
  chroma/   向量库（手机端用自己的 bigram 向量，重新算更快也更小）
  uploads/  小说原文（手机端自己传一次即可）
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "export-lite.json"


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    personas, sessions, memories = {}, {}, {}

    for f in sorted((DATA / "personas").glob("*.json")):
        card = load_json(f)
        if isinstance(card, dict) and card.get("name"):
            personas[card["name"]] = card

    for f in sorted((DATA / "sessions").glob("*.json")):
        data = load_json(f)
        if not isinstance(data, dict):
            continue
        name = data.get("persona") or f.stem
        msgs = data.get("messages") or []
        clean = [
            {"role": m["role"], "content": m["content"]}
            for m in msgs
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
        ]
        if clean:
            sessions[name] = clean

    for f in sorted((DATA / "memory").glob("*.json")):
        data = load_json(f)
        if not isinstance(data, dict):
            continue
        name = data.get("persona") or f.stem
        facts = data.get("facts") or []
        clean = [
            {"topic": x.get("topic", ""), "content": x.get("content", "")}
            for x in facts
            if isinstance(x, dict) and x.get("content")
        ]
        if clean:
            memories[name] = clean

    payload = {
        "version": 1,
        "exportedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "personas": personas,
        "sessions": sessions,
        "memories": memories,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    size_kb = OUT.stat().st_size / 1024
    print(f"已导出：{OUT}（{size_kb:.1f} KB）")
    print(f"  角色卡   {len(personas)} 个：{'、'.join(personas) or '无'}")
    print(f"  聊天记录 {len(sessions)} 份，共 {sum(len(v) for v in sessions.values())} 条")
    print(f"  长期记忆 {len(memories)} 份，共 {sum(len(v) for v in memories.values())} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
