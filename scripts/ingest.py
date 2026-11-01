"""命令行入库：python -m scripts.ingest data/samples/修鞋摊.md"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import indexing  # noqa: E402
from app.http import ApiError  # noqa: E402

SUFFIX = {".md", ".txt", ".pdf"}


def main(argv: list[str]) -> int:
    if not argv:
        print("用法: python -m scripts.ingest <文件或目录> [更多文件...]")
        return 1

    targets: list[Path] = []
    for arg in argv:
        path = Path(arg)
        if path.is_dir():
            targets.extend(sorted(p for p in path.rglob("*") if p.suffix.lower() in SUFFIX))
        elif path.is_file():
            targets.append(path)
        else:
            print(f"跳过：{arg} 不存在")

    if not targets:
        print("没有找到可入库的文件")
        return 1

    total = 0
    for path in targets:
        try:
            result = indexing.ingest_file(path)
        except ApiError as exc:
            print(f"[失败] {path.name}: {exc}")
            continue
        total += result["added"]
        print(f"[完成] {result['source']}: {result['chunks']} 块，写入 {result['added']} 条")

    print(f"\n共写入 {total} 个片段")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
