# -*- coding: utf-8 -*-
"""生成 PWA 图标（多方案预览 + 定稿）。

用法：
    python scripts/make_icons.py            # 用 FINAL 指定的方案，输出到 web/icons/
    python scripts/make_icons.py preview    # 三套方案各出一张大图到 web/icons/_preview/
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "icons"
PREVIEW = OUT / "_preview"

# 定稿时用哪套：A / B / C
FINAL = "A"


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_bg(size, top, bottom, radius_ratio=0.225, full_bleed=False):
    img = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(img)
    for y in range(size):
        draw.line([(0, y), (size, y)], fill=lerp(top, bottom, y / max(1, size - 1)))
    if full_bleed:
        return img
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * radius_ratio), fill=255
    )
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def bubble_and_lines(img, size, bubble, line_color, dot_color=None, scale=1.0):
    """对话气泡 + 三条文字线。坐标按 512 设计，再按比例缩放。"""
    s = size / 512 * scale
    off = (size - size * scale) / 2
    d = ImageDraw.Draw(img)

    def P(x, y):
        return (off + x * s, off + y * s)

    bx0, by0, bx1, by1 = 104, 128, 408, 332
    d.rounded_rectangle([P(bx0, by0), P(bx1, by1)], radius=int(46 * s), fill=bubble)
    d.polygon([P(168, 320), P(150, 392), P(232, 326)], fill=bubble)

    for i, w in enumerate((212, 246, 158)):
        y = 196 + i * 46
        d.rounded_rectangle(
            [P(150, y), P(150 + w, y + 20)], radius=int(10 * s), fill=line_color
        )

    if dot_color:
        d.ellipse([P(352, 264), P(384, 296)], fill=dot_color)


VARIANTS = {
    # A：深色底 + 白色气泡，最沉稳
    "A": dict(top=(31, 36, 48), bottom=(43, 49, 64),
              bubble=(255, 255, 255), line=(201, 206, 216), dot=(7, 193, 96)),
    # B：紫渐变 + 白色气泡 + 绿色小点，跟界面配色统一
    "B": dict(top=(108, 92, 231), bottom=(138, 116, 246),
              bubble=(255, 255, 255), line=(196, 186, 246), dot=(7, 193, 96)),
    # C：米白底 + 深紫气泡，反色，最轻
    "C": dict(top=(255, 249, 242), bottom=(255, 240, 226),
              bubble=(75, 63, 199), line=(255, 255, 255), dot=(255, 186, 102)),
}


def build(kind: str, size: int, maskable: bool = False) -> Image.Image:
    v = VARIANTS[kind]
    img = rounded_bg(size, v["top"], v["bottom"], full_bleed=maskable)
    bubble_and_lines(
        img, size,
        bubble=v["bubble"], line_color=v["line"], dot_color=v["dot"],
        scale=0.72 if maskable else 1.0,
    )
    return img


def export_final(kind: str) -> None:
    build(kind, 192).save(OUT / "icon-192.png")
    build(kind, 512).save(OUT / "icon-512.png")
    build(kind, 512, maskable=True).save(OUT / "maskable-512.png")

    # iOS 主屏图标不支持透明通道，压成 RGB
    src = build(kind, 512).resize((180, 180), Image.LANCZOS)
    apple = Image.new("RGB", (180, 180), VARIANTS[kind]["top"])
    apple.paste(src, (0, 0), src)
    apple.save(OUT / "apple-touch-icon.png")

    for f in sorted(OUT.glob("*.png")):
        print(f"{f.name:24} {f.stat().st_size // 1024} KB")


def export_preview() -> None:
    PREVIEW.mkdir(parents=True, exist_ok=True)
    for kind in VARIANTS:
        build(kind, 512).save(PREVIEW / f"option-{kind}.png")
        print(f"option-{kind}.png")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "preview":
        export_preview()
    else:
        export_final(FINAL)
