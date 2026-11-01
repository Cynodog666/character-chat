# -*- coding: utf-8 -*-
"""生成 PWA 图标：紫色圆角方块 + 白色「角」字。

输出到 web/icons/：
  icon-192.png / icon-512.png      普通图标（圆角）
  maskable-512.png                 Android 自适应图标（满版，内容留安全区）
  apple-touch-icon.png             iOS 主屏图标（180，不带透明通道）
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "web" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

BG_TOP = (124, 92, 255)
BG_BOTTOM = (94, 66, 214)
FG = (255, 255, 255)
FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"


def gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    return img


def draw_glyph(img: Image.Image, size: int, scale: float = 1.0) -> None:
    draw = ImageDraw.Draw(img)
    font_size = int(size * 0.56 * scale)
    font = ImageFont.truetype(FONT_PATH, font_size)
    text = "角"
    box = draw.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    draw.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1] - size * 0.02),
              text, font=font, fill=FG)


def rounded(img: Image.Image, size: int, radius_ratio: float = 0.22) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * radius_ratio), fill=255
    )
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def build_rounded(size: int) -> Image.Image:
    img = gradient(size)
    draw_glyph(img, size)
    return rounded(img, size)


def build_maskable(size: int) -> Image.Image:
    # 满版背景，字形缩到安全区（直径 80%）内，避免被系统裁掉
    img = gradient(size)
    draw_glyph(img, size, scale=0.72)
    return img


def build_apple(size: int) -> Image.Image:
    # iOS 不支持透明通道，必须用 RGB
    img = gradient(size)
    draw_glyph(img, size)
    return img


if __name__ == "__main__":
    build_rounded(192).save(OUT / "icon-192.png")
    build_rounded(512).save(OUT / "icon-512.png")
    build_maskable(512).save(OUT / "maskable-512.png")
    build_apple(180).convert("RGB").save(OUT / "apple-touch-icon.png")
    for f in sorted(OUT.iterdir()):
        print(f"{f.name:24} {f.stat().st_size // 1024} KB")
