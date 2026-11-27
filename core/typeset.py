"""Xoá chữ gốc và vẽ chữ tiếng Việt vào khung thoại."""
import os
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

APP_DIR = Path(__file__).resolve().parent.parent
_WIN_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
_FONT_CANDIDATES = [
    _WIN_FONTS / "arialbd.ttf", _WIN_FONTS / "arial.ttf", _WIN_FONTS / "tahomabd.ttf",
    _WIN_FONTS / "tahoma.ttf", _WIN_FONTS / "segoeuib.ttf", _WIN_FONTS / "segoeui.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]
_font_cache = {}


def find_default_font() -> str:
    """Ưu tiên font mặc định kèm app (Be Vietnam Pro đậm), rồi font khác trong fonts/, rồi font Windows."""
    fonts_dir = APP_DIR / "fonts"
    if (fonts_dir / "BeVietnamPro-Bold.ttf").exists():
        return str(fonts_dir / "BeVietnamPro-Bold.ttf")
    if fonts_dir.is_dir():
        found = sorted(list(fonts_dir.glob("*.ttf")) + list(fonts_dir.glob("*.otf")))
        if found:
            return str(found[0])
    for p in _FONT_CANDIDATES:
        if p.exists():
            return str(p)
    return ""


def get_font(path: str, size: int):
    # mỗi luồng vẽ có bộ font riêng (FreeType không an toàn khi dùng chung giữa các luồng)
    key = (path, size, threading.get_ident())
    if key not in _font_cache:
        font = None
        if path:
            try:
                font = ImageFont.truetype(path, size)
            except Exception:  # noqa: BLE001
                font = None
        if font is None:
            try:
                font = ImageFont.load_default(size=size)
            except TypeError:  # Pillow cũ
                font = ImageFont.load_default()
        _font_cache[key] = font
    return _font_cache[key]


# ---------------- xoá chữ gốc ----------------
def clean_page(img, blocks, inpainter=None):
    """Xoá chữ gốc. Bóng thoại nền phẳng -> tô thẳng màu nền (giữ nguyên viền bóng, sạch tuyệt đối).
    Chữ nằm trên hình / nền lưới chấm -> AI LaMa (inpainter) nếu có, không thì OpenCV inpaint.
    Ô 'giữ nguyên' không bị xoá."""
    out = img.copy()
    H, W = img.shape[:2]
    kernel = np.ones((5, 5), np.uint8)
    ai_mask = np.zeros((H, W), np.uint8) if inpainter is not None else None
    for b in blocks:
        if getattr(b, "keep", False):
            continue
        cs = b.char_size()
        pad = max(2, int(cs * 0.15))
        m = max(10, int(cs * 0.6))
        rx0, ry0 = max(0, b.x0 - m), max(0, b.y0 - m)
        rx1, ry1 = min(W, b.x1 + m), min(H, b.y1 + m)
        roi = out[ry0:ry1, rx0:rx1]
        if roi.size == 0:
            continue
        mask = np.zeros(roi.shape[:2], np.uint8)
        for x0, y0, x1, y1 in b.lines:
            cv2.rectangle(mask, (x0 - rx0 - pad, y0 - ry0 - pad),
                          (x1 - rx0 + pad, y1 - ry0 + pad), 255, -1)
        ring = cv2.bitwise_and(cv2.dilate(mask, kernel, iterations=2), cv2.bitwise_not(mask))
        vals = roi[ring > 0]
        if len(vals) > 10 and vals.std(axis=0).max() < 22:
            roi[mask > 0] = np.median(vals, axis=0).astype(np.uint8)
        elif ai_mask is not None:
            ai_mask[ry0:ry1, rx0:rx1] |= mask
        else:
            roi[:] = cv2.inpaint(roi, mask, max(3, int(cs * 0.3)), cv2.INPAINT_TELEA)
    if ai_mask is not None and ai_mask.any():
        try:
            out = inpainter.inpaint(out, ai_mask)
        except Exception:  # noqa: BLE001  (hết VRAM...) -> quay về OpenCV
            out = cv2.inpaint(out, ai_mask, 5, cv2.INPAINT_TELEA)
    return out


# ---------------- tìm bóng thoại ----------------
KIND_VI = {"speech": "Thoại", "thought": "Suy nghĩ", "shout": "Hét", "narration": "Dẫn truyện",
           "free": "Chữ trên hình", "sfx": "SFX"}


def classify_shape(comp) -> str:
    """Đoán loại bóng từ hình dạng vùng lòng bóng (uint8 0/1):
    narration = hộp chữ nhật; shout = viền nhiều gai nhọn; thought = viền gợn tròn kiểu đám mây;
    còn lại là bóng thoại thường."""
    cnts, _ = cv2.findContours((comp > 0).astype(np.uint8) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return "speech"
    cnt = max(cnts, key=cv2.contourArea)
    area = cv2.contourArea(cnt)
    if area < 50:
        return "speech"
    hull_area = max(cv2.contourArea(cv2.convexHull(cnt)), 1.0)
    solidity = area / hull_area
    _, _, bw, bh = cv2.boundingRect(cnt)
    rect_fill = area / max(1.0, bw * bh)
    # viền lồi lõm: đếm chỗ lõm đáng kể (đuôi bóng thoại chỉ tạo 1–2 chỗ lõm)
    try:
        defects = cv2.convexityDefects(cnt, cv2.convexHull(cnt, returnPoints=False))
    except cv2.error:
        defects = None
    root = np.sqrt(area)
    depths = np.array([]) if defects is None else defects.reshape(-1, 4)[:, 3] / 256.0
    deep = depths[depths > 0.03 * root]
    if len(deep) >= 6:
        # gai hét lõm sâu (viền răng cưa); mây suy nghĩ chỉ gợn nông giữa các cung tròn
        return "shout" if np.median(deep) > 0.09 * root else "thought"
    if rect_fill > 0.9 and solidity > 0.95:
        return "narration"
    return "speech"


def _bg_gray(gray_roi, b, ox, oy):
    """Màu nền (xám) tại chỗ chữ gốc sau khi đã xoá chữ."""
    reg = gray_roi[b.y0 - oy:b.y1 - oy, b.x0 - ox:b.x1 - ox]
    return int(np.median(reg)) if reg.size else 255


def _on_art(gray_raw, b) -> bool:
    """Chữ nằm trên hình / nền lưới chấm? (nền chỗ chữ – đã xoá chữ – không đồng màu)."""
    reg = gray_raw[b.y0:b.y1, b.x0:b.x1]
    if reg.size == 0:
        return True
    return reg.std() > 30 or cv2.medianBlur(reg, 5).std() > 20


def find_bubble(clean, b):
    """Lấy đúng HÌNH lòng bóng thoại quanh khung chữ.
    Chịu được nhiễu JPEG, lưới chấm và viền bóng bị hở (chặn bằng viền được làm dày dần).
    Vùng tìm tự nới dần (chữ nhỏ trong bóng to). Trả về (mask bool, ox, oy, loại bóng)
    hoặc None nếu chữ không nằm trong bóng kín."""
    H, W = clean.shape[:2]
    cs = b.char_size()
    gray_all = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY)
    if _on_art(gray_all, b):
        return None
    for factor in (1.2, 2.5, 4.5):
        ext = int(max(b.w, b.h) * factor + 3 * cs)
        rx0, ry0 = max(0, b.x0 - ext), max(0, b.y0 - ext)
        rx1, ry1 = min(W, b.x1 + ext), min(H, b.y1 + ext)
        found = _flood_bubble(gray_all[ry0:ry1, rx0:rx1], b, rx0, ry0, cs)
        if found is not None:
            m, kind = found
            if m.sum() > 0.45 * W * H:  # rộng gần nửa trang -> là lề trang, không phải bóng
                return None
            return m, rx0, ry0, kind
        if rx0 == 0 and ry0 == 0 and rx1 == W and ry1 == H:
            break
    return None


def _flood_bubble(gray_roi, b, rx0, ry0, cs):
    h, w = gray_roi.shape[:2]
    gray = cv2.medianBlur(gray_roi, 3)  # nhẹ: lọc nhiễu JPEG nhưng giữ chấm lưới (làm hàng rào)
    reg = gray[b.y0 - ry0:b.y1 - ry0, b.x0 - rx0:b.x1 - rx0]
    if reg.size == 0:
        return None
    bg = int(np.median(reg))
    near = (np.abs(gray.astype(np.int16) - bg) <= 30).astype(np.uint8)
    barrier = (1 - near).astype(np.uint8)
    sy, sx = (b.y0 + b.y1) // 2 - ry0, (b.x0 + b.x1) // 2 - rx0
    for gap in (0, 2, 4, 7, 11):  # viền bóng hở <= 2*gap px vẫn chặn được
        area = near.copy()
        if gap:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * gap + 1, 2 * gap + 1))
            area[cv2.dilate(barrier, k) > 0] = 0
        # mặt nạ chữ gốc luôn thuộc vùng trong
        area[max(0, b.y0 - ry0):b.y1 - ry0, max(0, b.x0 - rx0):b.x1 - rx0] = 1
        n, lab = cv2.connectedComponents(area, connectivity=4)
        comp = (lab == lab[sy, sx]).astype(np.uint8)
        ys, xs = np.nonzero(comp)
        if len(xs) == 0:
            continue
        if xs.min() == 0 or ys.min() == 0 or xs.max() == w - 1 or ys.max() == h - 1:
            continue  # tràn ra ngoài -> thử chặn viền dày hơn
        if gap:
            comp = cv2.dilate(comp, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * gap + 1, 2 * gap + 1)))
            comp &= near | comp  # không lấn ra ngoài vùng sáng
        kind = classify_shape(comp)
        m = cv2.morphologyEx(comp, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        bh_, bw_ = ys.max() - ys.min(), xs.max() - xs.min()
        margin = int(max(4, cs * 0.35, 0.12 * min(bw_, bh_)))
        m = cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin + 1, 2 * margin + 1)))
        if m.any():
            return m > 0, kind
    return None


def safe_rect(clean, b):
    """Không tìm được bóng kín (bóng hở, chữ trên nền trơn...): nới khung chữ ra từng
    chút MIỄN LÀ vẫn là nền trơn cùng màu – không bao giờ lấn sang hình vẽ."""
    H, W = clean.shape[:2]
    cs = b.char_size()
    raw = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(raw, 3) if min(H, W) > 5 else raw
    reg = gray[b.y0:b.y1, b.x0:b.x1]
    x0, y0, x1, y1 = b.x0, b.y0, b.x1, b.y1
    if reg.size == 0 or _on_art(raw, b):
        # chữ nằm trên hình (không có viền bóng để tràn ra): chữ Việt dài hơn chữ Hán/Nhật
        # nên cho rộng hơn khung chữ gốc một chút, chữ có viền tương phản nên vẫn dễ đọc
        cx_, cy_ = (x0 + x1) / 2, (y0 + y1) / 2
        hw = max(b.w * 0.75, b.h * 0.6 if b.vertical else 0, cs * 2.5)
        hh = max(b.h * 0.65, cs)
        return (int(max(0, cx_ - hw)), int(max(0, cy_ - hh)), int(min(W, cx_ + hw)), int(min(H, cy_ + hh)))
    bg = int(np.median(reg))
    step = max(2, cs // 4)
    lim = int(max(b.w, b.h) * 0.8 + cs)
    grow = {"l": True, "r": True, "t": True, "b": True}

    def ok(strip):
        return strip.size and (np.abs(strip.astype(np.int16) - bg) <= 30).mean() > 0.985

    while any(grow.values()):
        if grow["l"]:
            nx = max(0, x0 - step)
            grow["l"] = nx < x0 and b.x0 - nx <= lim and ok(gray[y0:y1, nx:x0])
            if grow["l"]:
                x0 = nx
        if grow["r"]:
            nx = min(W, x1 + step)
            grow["r"] = nx > x1 and nx - b.x1 <= lim and ok(gray[y0:y1, x1:nx])
            if grow["r"]:
                x1 = nx
        if grow["t"]:
            ny = max(0, y0 - step)
            grow["t"] = ny < y0 and b.y0 - ny <= lim and ok(gray[ny:y0, x0:x1])
            if grow["t"]:
                y0 = ny
        if grow["b"]:
            ny = min(H, y1 + step)
            grow["b"] = ny > y1 and ny - b.y1 <= lim and ok(gray[y1:ny, x0:x1])
            if grow["b"]:
                y1 = ny
    # chừa lề, nhưng không nhỏ hơn khung chữ gốc
    mg = max(3, int(cs * 0.3))
    x0, x1 = min(b.x0, x0 + mg), max(b.x1, x1 - mg)
    y0, y1 = min(b.y0, y0 + mg), max(b.y1, y1 - mg)
    return x0, y0, x1, y1


def _row_spans(mask, cx):
    """Với mỗi hàng: khoảng [trái, phải] liền mạch của mask chứa cột cx (-1 nếu không có)."""
    h, w = mask.shape
    L = np.full(h, -1, np.int32)
    R = np.full(h, -1, np.int32)
    cx = int(min(max(cx, 0), w - 1))
    for r in range(h):
        row = mask[r]
        if not row[cx]:
            continue
        zl = np.flatnonzero(~row[:cx])
        zr = np.flatnonzero(~row[cx:])
        L[r] = zl[-1] + 1 if len(zl) else 0
        R[r] = cx + zr[0] - 1 if len(zr) else w - 1
    return L, R


def layout_region(clean, b):
    """Vùng đặt chữ: (L, R, ox, oy, cx, cy, loại) – độ rộng từng hàng theo đúng hình bóng thoại;
    không có bóng kín thì dùng vùng nền trơn quanh chữ gốc (safe_rect)."""
    found = find_bubble(clean, b)
    if found is not None:
        m, ox, oy, kind = found
        ys, xs = np.nonzero(m)
        # tâm: lấy tâm khung chữ gốc kéo về tâm bóng (bóng có đuôi thì tâm hình bị lệch)
        cx = int(round(0.5 * xs.mean() + 0.5 * ((b.x0 + b.x1) / 2 - ox)))
        cy = int(round(0.5 * ys.mean() + 0.5 * ((b.y0 + b.y1) / 2 - oy)))
        if not (0 <= cy < m.shape[0] and 0 <= cx < m.shape[1]) or not m[cy, cx]:
            cx, cy = int(xs.mean()), int(ys.mean())
        L, R = _row_spans(m, cx)
        return L, R, ox, oy, cx, cy, kind
    x0, y0, x1, y1 = safe_rect(clean, b)
    h = max(1, y1 - y0)
    L = np.zeros(h, np.int32)
    R = np.full(h, max(1, x1 - x0 - 1), np.int32)
    H, W = clean.shape[:2]
    big = b.w * b.h > 0.02 * W * H
    kind = "sfx" if big and len((b.text or "").replace(" ", "")) <= 8 else "free"
    return L, R, x0, y0, (x1 - x0) // 2, h // 2, kind


# ---------------- dàn chữ ----------------
def _greedy(words, font, widths):
    """Xếp từ vào các dòng có độ rộng cho trước. None nếu không đủ chỗ."""
    lines, i = [], 0
    for wmax in widths:
        cur = ""
        while i < len(words):
            cand = words[i] if not cur else cur + " " + words[i]
            if font.getlength(cand) <= wmax:
                cur = cand
                i += 1
            else:
                break
        if not cur:
            return None
        lines.append(cur)
        if i == len(words):
            break
    return lines if i == len(words) and len(lines) == len(widths) else None


def line_metrics(font, size):
    """(chiều cao 1 dòng, độ lệch đỉnh glyph) đo trên chữ có dấu cao/thấp nhất tiếng Việt."""
    try:
        x0, y0, x1, y1 = font.getbbox("ẤỖỸjgyạậ")
    except Exception:  # noqa: BLE001
        y0, y1 = 0, size
    gh = y1 - y0
    return max(1, int(round(max(gh * 0.94, size)))), y0  # dấu dòng dưới được sát chân dòng trên


def fit_in_shape(text, font_path, L, R, cy, max_size, min_size):
    """Tìm cỡ chữ LỚN NHẤT (≤ max_size) mà cả câu – kể cả dấu và viền chữ – nằm gọn
    trong hình bóng thoại. Trả về (font, size, sw, [(dòng, x_giữa, y_đỉnh), ...], y_off)."""
    words = text.split()
    n_rows = len(L)
    for size in range(max_size, min_size - 1, -1):
        font = get_font(font_path, size)
        lh, yoff = line_metrics(font, size)
        sw = max(1, size // 12)
        lh += sw
        for k in range(1, min(len(words), 40) + 1):
            total = k * lh
            top = int(round(cy - total / 2))
            if top < 0 or top + total > n_rows:
                break
            spans, ok = [], True
            for i in range(k):
                a, z = top + i * lh, top + (i + 1) * lh
                sl, sr = L[a:z], R[a:z]
                if (sl < 0).any():
                    ok = False
                    break
                spans.append((int(sl.max()), int(sr.min())))
            if not ok:
                break  # cao hơn nữa cũng tràn khỏi bóng
            widths = [r - l - 2 * sw for l, r in spans]
            if min(widths) <= size:
                continue
            # chia đều: mỗi dòng nhận phần chữ tỉ lệ với độ rộng của nó (tránh dòng 1 chữ lẻ loi)
            total_len = font.getlength(" ".join(words))
            sw_sum = float(sum(widths))
            balanced = [min(w, total_len * w / sw_sum * 1.12 + size) for w in widths]
            cands = [_greedy(words, font, balanced), _greedy(words, font, widths)] if k > 1 \
                else [_greedy(words, font, widths)]
            lines = None
            for c in cands:
                if not c:
                    continue
                lens = [font.getlength(x) for x in c]
                # bỏ cách xếp có dòng quá ngắn (1 chữ lẻ loi) khi câu còn nhiều chữ
                if len(c) > 1 and len(words) > 3 and min(lens) < 0.3 * max(lens):
                    continue
                lines = c
                break
            if lines:
                return font, size, sw, [(ln, (l + r) / 2, top + i * lh + sw)
                                        for i, (ln, (l, r)) in enumerate(zip(lines, spans))], yoff
    return None


def wrap_text(text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        cand = word if not cur else cur + " " + word
        if font.getlength(cand) <= max_w:
            cur = cand
            continue
        if cur:
            lines.append(cur)
            cur = ""
        if font.getlength(word) <= max_w:
            cur = word
        else:  # từ quá dài -> ngắt theo ký tự
            piece = ""
            for ch in word:
                if not piece or font.getlength(piece + ch) <= max_w:
                    piece += ch
                else:
                    lines.append(piece)
                    piece = ch
            cur = piece
    if cur:
        lines.append(cur)
    return lines


def _fallback_layout(text, font_path, L, R, cx, cy, size):
    """Chữ quá dài so với bóng: cỡ nhỏ nhất, ngắt theo độ rộng hàng giữa bóng."""
    font = get_font(font_path, size)
    lh, yoff = line_metrics(font, size)
    sw = max(1, size // 12)
    r = int(min(max(cy, 0), len(L) - 1))
    w = max(20, int(R[r] - L[r]) if L[r] >= 0 else 40)
    lines = wrap_text(text, font, w - 2 * sw)
    top = cy - len(lines) * lh / 2
    return font, size, sw, [(ln, cx, top + i * lh) for i, ln in enumerate(lines)], yoff


def render_page(cleaned_bgr, blocks, font_path, uppercase=False, src_bgr=None, font_scale=0.7,
                text_only=False, restore_src=True):
    """Vẽ bản dịch lên ảnh đã xoá chữ. Cỡ chữ gần bằng chữ gốc và tự thu nhỏ cho vừa
    đúng hình bóng thoại. Khung nào chưa có bản dịch / giữ nguyên thì dán lại chữ gốc.
    text_only=True: trả về lớp chữ RGBA nền trong suốt (cho file PSD nhiều lớp)."""
    if not font_path or not Path(font_path).exists():
        font_path = find_default_font()
    base = cleaned_bgr.copy()
    H, W = base.shape[:2]
    if src_bgr is not None and src_bgr.shape[:2] == (H, W) and not text_only and restore_src:
        for b in blocks:
            if b.keep or not (b.translation or "").strip():
                m = max(4, b.char_size() // 2)
                x0, y0 = max(0, b.x0 - m), max(0, b.y0 - m)
                x1, y1 = min(W, b.x1 + m), min(H, b.y1 + m)
                base[y0:y1, x0:x1] = src_bgr[y0:y1, x0:x1]
    if text_only:
        pil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    else:
        pil = Image.fromarray(cv2.cvtColor(base, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    for b in blocks:
        b.overflow = False
        text = " ".join((b.translation or "").split())
        L, R, ox, oy, cx, cy, kind = layout_region(cleaned_bgr, b)
        b.kind = kind
        if not text or b.keep:
            continue
        if uppercase or kind in ("shout", "sfx"):
            text = text.upper()
        cs = b.char_size()
        # cỡ tối đa = font_scale × cỡ chữ gốc (mặc định 70%), tự thu nhỏ tới khi nằm gọn
        max_size = int(min(56, max(10, cs * font_scale)))
        min_size = int(max(7, min(max_size, cs * 0.3)))
        res = fit_in_shape(text, font_path, L, R, cy, max_size, min_size)
        if res is None:
            b.overflow = True  # phải thu nhỏ dưới mức cho phép -> báo ở tab Tình trạng
            res = fit_in_shape(text, font_path, L, R, cy, min_size - 1, 6)
        if res is None:
            res = _fallback_layout(text, font_path, L, R, cx, cy, 7 if min_size > 7 else min_size)
        font, size, sw, placed, yoff = res

        region = cleaned_bgr[b.y0:b.y1, b.x0:b.x1]
        bgc = np.median(region.reshape(-1, 3), axis=0) if region.size else np.array([255, 255, 255])
        lum = 0.114 * bgc[0] + 0.587 * bgc[1] + 0.299 * bgc[2]
        fill, stroke = ((0, 0, 0), (255, 255, 255)) if lum > 128 else ((255, 255, 255), (0, 0, 0))
        for line, lx, ly in placed:
            x = ox + lx - font.getlength(line) / 2
            y = oy + ly - yoff  # đỉnh dấu cao nhất trùng đỉnh dòng đã tính
            draw.text((x, y), line, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke)
    if text_only:
        return np.array(pil)  # RGBA
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
