# -*- coding: utf-8 -*-
"""
挂件布局预览（开发用）
================================================
把「立绘几何 + 气泡变换」按挂件客户端的同一套数学渲染成一张 PNG，
用来在不打开浏览器的情况下检查：气泡有没有盖住脸、尾巴有没有指向角色。

    py -3.12 tools/preview_layout.py --image assets/characters/luotianyi-v5.png \
        --img-w 46.7 --img-h 68 --img-right 2 --img-bottom 0 \
        --bubble-scale 0.92 --bubble-dx 12 --bubble-dy -2 --out preview.png

坐标系说明（与 lib/index.js 的 CSS 一致）：
  · 挂件根方框是 S×S
  · 气泡元素 width=100%(=S)、height=S*700/1026，SVG viewBox 0 0 1026 700 等比铺满
  · 气泡整体变换：transform-origin 50% 100%，先 scale 再按元素尺寸的百分比平移
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

SVG_W, SVG_H = 1026.0, 700.0
# 气泡外轮廓（SVG 圆弧近似成椭圆）+ 两个尾巴椭圆 + 文字中心
BODY = (454.0, 247.0, 373.0, 232.0)
TAILS = [(352.0, 561.0, 37.5, 26.0), (442.0, 646.0, 24.5, 18.0)]
TEXT_CENTER = (454.0, 266.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--img-w", type=float, default=62.0)
    ap.add_argument("--img-h", type=float, default=62.0)
    ap.add_argument("--img-right", type=float, default=2.0)
    ap.add_argument("--img-bottom", type=float, default=0.0)
    ap.add_argument("--bubble-scale", type=float, default=1.0)
    ap.add_argument("--bubble-dx", type=float, default=0.0)
    ap.add_argument("--bubble-dy", type=float, default=0.0)
    ap.add_argument("--box", type=int, default=400)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    s = args.box
    canvas = Image.new("RGBA", (s, s), (232, 238, 250, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")

    # ---- 立绘 ----
    ch = Image.open(args.image).convert("RGBA")
    w = max(1, int(round(s * args.img_w / 100.0)))
    h = max(1, int(round(s * args.img_h / 100.0)))
    ch = ch.resize((w, h), Image.LANCZOS)
    x = int(round(s - w - s * args.img_right / 100.0))
    y = int(round(s - h - s * args.img_bottom / 100.0))
    canvas.alpha_composite(ch, (x, y))

    # ---- 气泡几何 ----
    u = s / SVG_W                     # SVG 单位 → 像素
    bw, bh = s, s * SVG_H / SVG_W     # 气泡元素尺寸
    ox, oy = 0.5 * bw, bh             # transform-origin: 50% 100%
    sc = args.bubble_scale

    def tx(px: float, py: float):
        return ox + (px * u - ox) * sc + args.bubble_dx / 100.0 * bw

    def ty(px: float, py: float):
        return oy + (py * u - oy) * sc + args.bubble_dy / 100.0 * bh

    def ellipse(cx, cy, rx, ry, outline, fill=None, width=2):
        x0 = tx(cx - rx, cy - ry)
        y0 = ty(cx - rx, cy - ry)
        x1 = tx(cx + rx, cy + ry)
        y1 = ty(cx + rx, cy + ry)
        draw.ellipse([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], outline=outline, fill=fill, width=width)

    # 气泡主体（半透明填充，方便看清下面的立绘）
    ellipse(BODY[0], BODY[1], BODY[2], BODY[3], (32, 49, 112, 255), (255, 255, 255, 150), 2)
    for t in TAILS:
        ellipse(t[0], t[1], t[2], t[3], (32, 49, 112, 255), (255, 255, 255, 150), 2)

    # 文字块（label/amount/hint 三行的近似外框）
    cx, cy = tx(TEXT_CENTER[0], TEXT_CENTER[1]), ty(TEXT_CENTER[0], TEXT_CENTER[1])
    half_w = 280 * u * sc
    half_h = 150 * u * sc
    draw.rectangle([cx - half_w, cy - half_h, cx + half_w, cy + half_h], outline=(224, 67, 63, 255), width=1)
    draw.line([cx - 8, cy, cx + 8, cy], fill=(224, 67, 63, 255), width=1)
    draw.line([cx, cy - 8, cx, cy + 8], fill=(224, 67, 63, 255), width=1)

    # 立绘外框 + 根方框 + 菜单按钮位置
    draw.rectangle([x, y, x + w, y + h], outline=(47, 162, 76, 255), width=1)
    draw.rectangle([0, 0, s - 1, s - 1], outline=(120, 130, 160, 255), width=1)
    btn_top = 0.4055 * s + 4
    draw.rectangle([s - 4 - 26, btn_top, s - 4, btn_top + 26], outline=(32, 49, 112, 255), width=1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out)
    print(str(out))


if __name__ == "__main__":
    main()
