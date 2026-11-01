"""导出角色卡取样预览：看看模型究竟读到了什么。

抽角色卡只看 12k 字（PERSONA_MAX_MATERIAL），这段取样质量直接决定角色卡质量。
把它导出来，比事后猜"为什么不像"有效得多。

用法：
    python -m scripts.preview 设定/大哥.txt 魏谦
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, loader  # noqa: E402
from app.persona import QUOTE_RE, collect_material, strip_front_matter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("name")
    parser.add_argument("--budget", type=int, default=None)
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"找不到文件：{path}")
        return 1

    raw = loader.read_text_auto(path)
    cleaned = strip_front_matter(raw)
    budget = args.budget or config.PERSONA_MAX_MATERIAL
    material = collect_material(cleaned, args.name, budget=budget)

    sections = loader.split_by_heading(cleaned)
    hit_sections = [t for t, body in sections if args.name in body]
    paragraphs = [p for p in material.split("\n") if p.strip()]
    dialogue = [p for p in paragraphs if QUOTE_RE.search(p)]
    with_name = [p for p in paragraphs if args.name in p]

    print(f"原文      {len(raw)} 字")
    print(f"去掉文案  {len(cleaned)} 字（-{len(raw) - len(cleaned)}）")
    print(f"取样      {len(material)} 字 / 预算 {budget}")
    print(f"段落      {len(paragraphs)} 段，其中含对白 {len(dialogue)} 段，提到「{args.name}」{len(with_name)} 段")
    print(f"章节      {len(sections)} 个，其中出现「{args.name}」的有 {len(hit_sections)} 个")

    out_dir = config.DATA_DIR / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.name}-取样.txt"
    out_path.write_text(material, encoding="utf-8")
    print(f"\n取样已导出：{out_path}")

    print("\n--- 取样开头 200 字 ---")
    print(material[:200])
    print("\n--- 取样结尾 200 字 ---")
    print(material[-200:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
