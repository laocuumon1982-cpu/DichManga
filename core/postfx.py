"""Hậu kỳ trang đã dịch: đóng dấu logo / credit nhóm dịch, ghép & cắt webtoon thông minh."""
from pathlib import Path

import cv2
import numpy as np

from .loader import imread, imwrite

LOGO_POS = [("Tự chọn góc trống", "auto"), ("Dưới phải", "br"), ("Dưới trái", "bl"), ("Dưới giữa", "bc"),
            ("Trên phải", "tr"), ("Trên trái", "tl")]
LOGO_PAGES = [("Mọi trang", "all"), ("Trang đầu", "first"), ("Trang cuối", "last"),
              ("Trang đầu + cuối", "first_last")]
JPG_MAX = 65000  # JPEG không lưu được ảnh cao quá 65535 px


# =====================================================================
#  Logo / credit
# =====================================================================
def _read_rgba(path):
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    im = cv2.imdecode(data, cv2.IMREAD_UNCHANGED) if data.size else None
    if im is None:
        return None
    if im.dtype != np.uint8:
        im = cv2.normalize(im, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    elif im.shape[2] == 3:
        im = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA)
    return im


def logo_wanted(cfg_get, index: int, total: int) -> bool:
    path = cfg_get("logo_path", "")
    if not path or not Path(path).is_file():
        return False
    which = cfg_get("logo_pages", "all")
    first, last = index == 0, index == total - 1
    return (which == "all" or (which == "first" and first) or (which == "last" and last)
            or (which == "first_last" and (first or last)))


def _overlap(r, boxes):
    x0, y0, x1, y1 = r
    a = max(1, (x1 - x0) * (y1 - y0))
    s = 0
    for b in boxes:
        ix = max(0, min(x1, b[2]) - max(x0, b[0]))
        iy = max(0, min(y1, b[3]) - max(y0, b[1]))
        s += ix * iy
    return s / a


def stamp_logo(img, logo_path, pos="auto", size_pct=12, opacity=85, boxes=None):
    """Đóng dấu logo (PNG trong suốt) lên ảnh BGR. size_pct: % chiều ngang trang.
    pos='auto': chọn góc ít chi tiết nhất và không đè lên ô thoại."""
    logo = _read_rgba(logo_path)
    if logo is None:
        return img
    H, W = img.shape[:2]
    lw = max(16, int(W * max(2, min(60, size_pct)) / 100))
    lh = max(8, int(logo.shape[0] * lw / max(1, logo.shape[1])))
    if lh > H // 3:
        lh = H // 3
        lw = max(8, int(logo.shape[1] * lh / max(1, logo.shape[0])))
    logo = cv2.resize(logo, (lw, lh), interpolation=cv2.INTER_AREA if lw < logo.shape[1] else cv2.INTER_CUBIC)
    m = max(6, int(0.02 * W))
    spots = {"tl": (m, m), "tr": (W - lw - m, m), "bl": (m, H - lh - m), "br": (W - lw - m, H - lh - m),
             "bc": ((W - lw) // 2, H - lh - m)}
    if pos not in spots:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        best, score = "br", None
        for key in ("br", "bl", "tr", "tl", "bc"):
            x, y = spots[key]
            if x < 0 or y < 0:
                continue
            patch = gray[y:y + lh, x:x + lw]
            sc = float(patch.std()) + 400 * _overlap((x, y, x + lw, y + lh), boxes or [])
            if score is None or sc < score - 1e-6:
                best, score = key, sc
        pos = best
    x, y = spots[pos]
    x, y = max(0, min(W - lw, x)), max(0, min(H - lh, y))
    out = img.copy()
    roi = out[y:y + lh, x:x + lw].astype(np.float32)
    a = (logo[:, :, 3:4].astype(np.float32) / 255.0) * (max(5, min(100, opacity)) / 100)
    out[y:y + lh, x:x + lw] = (logo[:, :, :3].astype(np.float32) * a + roi * (1 - a)).astype(np.uint8)
    return out


# =====================================================================
#  Webtoon: ghép thành dải dài / cắt lại theo chiều cao, né bóng thoại
# =====================================================================
def _load_strip(paths, boxes_by_page=None):
    """Đọc các trang, đưa về cùng chiều ngang (chiều ngang hay gặp nhất), nối dọc.
    Trả về (ảnh dải, [(y0, y1) vùng cấm cắt])."""
    imgs, ws = [], []
    for p in paths:
        im = imread(p)
        if im is not None:
            imgs.append((p, im))
            ws.append(im.shape[1])
    if not imgs:
        raise RuntimeError("Không đọc được trang nào.")
    W = max(set(ws), key=ws.count)
    parts, forbid, y = [], [], 0
    for k, (p, im) in enumerate(imgs):
        s = W / im.shape[1]
        if im.shape[1] != W:
            im = cv2.resize(im, (W, max(1, int(im.shape[0] * s))), interpolation=cv2.INTER_AREA)
        for b in (boxes_by_page or {}).get(p, []):
            pad = max(12, int(0.25 * (b[3] - b[1])))
            forbid.append((y + int(b[1] * s) - pad, y + int(b[3] * s) + pad))
        parts.append(im)
        y += im.shape[0]
    return np.vstack(parts), forbid


def merge_strip(paths, out_path, boxes_by_page=None) -> list:
    """Ghép mọi trang thành 1 ảnh dài. JPG cao quá 65000 px thì tự chia thành vài phần."""
    strip, _ = _load_strip(paths, boxes_by_page)
    out_path = Path(out_path)
    ext = out_path.suffix.lower()
    if ext in (".jpg", ".jpeg") and strip.shape[0] > JPG_MAX:
        cuts = smart_cuts(strip, JPG_MAX - 2000, [], hard_max=JPG_MAX)
        outs = []
        for k, (y0, y1) in enumerate(zip([0] + cuts, cuts + [strip.shape[0]]), 1):
            p = out_path.with_name(f"{out_path.stem}_{k:02d}{ext}")
            imwrite(p, strip[y0:y1])
            outs.append(str(p))
        return outs
    imwrite(out_path, strip)
    return [str(out_path)]


def smart_cuts(strip, target_h: int, forbid, hard_max: int = None):
    """Chọn các hàng để cắt: gần bội số target_h, ưu tiên hàng nền trơn (một màu),
    tuyệt đối không cắt ngang ô thoại (forbid)."""
    H = strip.shape[0]
    if H <= target_h * 1.15:
        return []
    gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY) if strip.ndim == 3 else strip
    small = gray[:, ::4].astype(np.float32)
    row_std = small.std(axis=1)
    row_std = np.convolve(row_std, np.ones(7) / 7, mode="same")  # cắt ở giữa dải trơn
    bad = np.zeros(H, bool)
    for y0, y1 in forbid:
        bad[max(0, y0):min(H, y1)] = True
    cost = row_std + bad * 1e6
    hard_max = hard_max or int(target_h * 1.6)
    cuts, last = [], 0
    while H - last > target_h * 1.15:
        lo = last + int(target_h * 0.75)
        hi = min(H - int(target_h * 0.25), last + min(hard_max, int(target_h * 1.25)))
        if hi <= lo:
            break
        ys = np.arange(lo, hi)
        dist = np.abs(ys - (last + target_h)) / target_h
        c = cost[lo:hi] + 4.0 * dist
        y = int(ys[int(np.argmin(c))])
        if cost[y] >= 1e6:  # cửa sổ toàn ô thoại -> nới rộng tới giới hạn cứng
            hi2 = min(H - 1, last + hard_max)
            ys = np.arange(lo, hi2)
            y = int(ys[int(np.argmin(cost[lo:hi2]))]) if len(ys) else hi
        cuts.append(y)
        last = y
    return cuts


def split_strip(paths, out_dir, target_h: int = 2000, boxes_by_page=None, ext: str = "jpg") -> list:
    """Ghép rồi cắt lại thành các ảnh cao ~target_h px, không cắt ngang chữ / bóng thoại."""
    strip, forbid = _load_strip(paths, boxes_by_page)
    cuts = smart_cuts(strip, int(target_h), forbid)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"*.{ext}"):
        old.unlink()
    outs = []
    for k, (y0, y1) in enumerate(zip([0] + cuts, cuts + [strip.shape[0]]), 1):
        p = out_dir / f"{k:04d}.{ext}"
        imwrite(p, strip[y0:y1])
        outs.append(str(p))
    return outs
