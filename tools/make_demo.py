"""Tạo vài trang truyện mẫu (ảnh gốc + ảnh đã dịch) để chụp ảnh giao diện khi build tự động.

python tools/make_demo.py <thư_mục_ra>   ->  <ra>/demo/*.png và <ra>/demo_out/*.png
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.block import TextBlock  # noqa: E402
from core.typeset import clean_page, find_default_font, render_page  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo_build")
(out / "demo").mkdir(parents=True, exist_ok=True)
(out / "demo_out").mkdir(parents=True, exist_ok=True)
font_path = find_default_font()
W, H = 800, 1150
for n in range(1, 7):
    img = Image.new("RGB", (W, H), (236, 238, 245))
    d = ImageDraw.Draw(img)
    hue = [(255, 205, 210), (200, 220, 255), (210, 245, 220), (255, 235, 200), (230, 210, 255), (200, 240, 245)][n - 1]
    d.rectangle([30, 30, W - 30, 560], fill=hue, outline=(40, 40, 60), width=5)
    d.rectangle([30, 590, W - 30, H - 30], fill=(250, 250, 252), outline=(40, 40, 60), width=5)
    for k in range(9):  # vài nét "nhân vật" cho có hình
        d.ellipse([120 + k * 60, 300 - (k % 3) * 30, 180 + k * 60, 360 - (k % 3) * 30], outline=(60, 60, 90), width=4)
    d.ellipse([80, 70, 470, 300], fill="white", outline="black", width=4)
    d.ellipse([430, 640, 760, 860], fill="white", outline="black", width=4)
    blocks = [TextBlock.from_lines([[150, 140, 400, 175], [150, 190, 340, 225]], vertical=False),
              TextBlock.from_lines([[500, 720, 690, 755]], vertical=False)]
    f = ImageFont.load_default()
    for b in blocks:
        for r in b.lines:
            d.rectangle(r, fill=(30, 30, 30))  # thay chữ gốc bằng khối đen giả
    blocks[0].translation = f"Trang {n}: hắn phải tranh thủ thời gian rồi, không thể chần chừ thêm nữa."
    blocks[1].translation = "Ngươi vừa nói cái gì vậy hả?"
    src = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(out / "demo" / f"{n:02d}.png"), src)
    res = render_page(clean_page(src, blocks), blocks, font_path, False, src, 0.8)
    cv2.imwrite(str(out / "demo_out" / f"{n:02d}.png"), res)
print("demo ->", out)
