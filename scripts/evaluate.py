"""角色一致性评测。

三件事：
1. 出戏检测——回答里出现"AI""作为模型""小说""角色扮演"这类词，直接判失败。
2. 人设事实——问原文写过的事，答案里应该有对应的关键事实。
3. 视角边界——问原文没写的事，角色应该回避或反问，而不是编一个具体答案。

用法：
    python -m scripts.evaluate --persona 老周
    python -m scripts.evaluate --persona 老周 --limit 4
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import dialog  # noqa: E402
from app import persona as persona_mod  # noqa: E402
from app.http import ApiError  # noqa: E402

DEFAULT_SET = ROOT / "data" / "eval" / "persona_probes.jsonl"

# 出戏词：出现任何一个就判失败
FORBIDDEN = [
    "作为一个AI", "作为 AI", "人工智能", "语言模型", "我是AI", "我是 AI",
    "小说", "角色扮演", "提示词", "系统设定", "prompt",
]


def load_probes(path: Path) -> list[dict]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def has_any(text: str, keywords: list[str]) -> bool:
    plain = (text or "").replace(" ", "").lower()
    return any(k.replace(" ", "").lower() in plain for k in keywords)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona", required=True, help="角色卡名字，对应 data/personas/<name>.json")
    parser.add_argument("--set", default=str(DEFAULT_SET))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    try:
        persona = persona_mod.load_persona(args.persona)
    except FileNotFoundError:
        print(f"角色卡不存在：{args.persona}")
        print("先跑：python -m scripts.build_persona data/samples/修鞋摊.md 老周")
        return 1

    probes = load_probes(Path(args.set))
    if args.limit:
        probes = probes[: args.limit]

    rows = []
    passed = 0

    for i, probe in enumerate(probes, start=1):
        question = probe["question"]
        try:
            answer = dialog.reply(persona, question, history=[])["reply"]
        except ApiError as exc:
            answer = f"[调用失败] {exc}"

        leak = has_any(answer, FORBIDDEN)
        expect_ok = has_any(answer, probe.get("expect_any", [])) if probe.get("expect_any") else True
        ok = (not leak) and expect_ok
        passed += ok
        rows.append((i, probe["kind"], question, answer, ok, leak, expect_ok))

        print(f"[{i:02d}] {'✓' if ok else '✗'} [{probe['kind']}] {question}")
        print(f"     → {answer}")

    print("\n" + "=" * 66)
    for i, kind, question, _answer, ok, leak, expect_ok in rows:
        flag = "✓" if ok else ("出戏" if leak else ("没答到点" if not expect_ok else "✗"))
        print(f"{i:<4}{kind:<10}{question[:26]:<30}{flag}")
    print("=" * 66)
    print(f"通过 {passed}/{len(rows)} = {passed / len(rows):.0%}")

    print("\n注意两个局限，别被数字骗了：")
    print("1. 关键词判定会把「角色在隐瞒、回避」误判成失败。")
    print("   比如问麻子近况，角色答「挺好的」其实是按设定在瞒着他已死的事实，这不是错误。")
    print("2. 语气像不像，规则测不出来，只能人读。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
