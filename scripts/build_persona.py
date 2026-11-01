"""生成角色卡：python -m scripts.build_persona data/samples/修鞋摊.md 老周

流程：读原文 -> 列角色（可选）-> 抽角色卡 -> 存到 data/personas/
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import indexing  # noqa: E402
from app import persona as persona_mod  # noqa: E402
from app.http import ApiError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="小说原文路径（md / txt / pdf）")
    parser.add_argument("name", nargs="?", default="", help="角色名；留空则只列出候选角色")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"找不到文件：{path}")
        return 1

    text = indexing.read_source_text(path)
    print(f"读取 {path.name}，共 {len(text)} 字\n")

    try:
        if not args.name:
            print("未指定角色名，先列出主要角色：\n")
            for item in persona_mod.list_characters(text):
                print(f"  · {item['name']}（{item['role']}）：{item['one_line']}")
            print("\n再执行一次并带上角色名即可生成角色卡。")
            return 0

        persona = persona_mod.extract_persona(text, args.name)
    except ApiError as exc:
        print(f"生成失败：{exc}")
        return 1

    out = persona_mod.save_persona(persona)
    print(f"角色卡已保存：{out}\n")
    print(f"  姓名：{persona['name']}")
    print(f"  身份：{persona['identity']}")
    print(f"  性格：{'、'.join(persona['personality'])}")
    print(f"  说话：{persona['speech_style']}")
    if persona["catchphrases"]:
        print(f"  口头禅：{' / '.join(persona['catchphrases'])}")
    print(f"  原文对白 {len(persona['example_lines'])} 句，取材 {persona['source_chars']} 字")
    if persona["does_not_know"]:
        print(f"  不知道：{'；'.join(persona['does_not_know'][:3])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
