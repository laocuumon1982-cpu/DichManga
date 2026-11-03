"""Đọc trang truyện từ thư mục ảnh hoặc file PDF, ghi ảnh/xuất PDF.

Dùng np.fromfile + cv2.imdecode để đọc được đường dẫn có dấu tiếng Việt trên Windows.
"""
import re
from pathlib import Path

import cv2
import numpy as np

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".jfif"}
PDF_MAX_PT = 14400  # giới hạn kích thước trang PDF (200 inch)


def natural_key(name: str):
    """Sắp xếp tự nhiên: 2.jpg đứng trước 10.jpg."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def list_images(folder) -> list:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXT]
    files.sort(key=lambda p: natural_key(p.name))
    return [str(p) for p in files]


def imread(path):
    """Đọc ảnh -> BGR uint8 (xử lý ảnh xám, ảnh có alpha, ảnh 16-bit)."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.dtype == np.uint16:
        img = (img / 257).astype(np.uint8)
    elif img.dtype != np.uint8:
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:  # ảnh có kênh alpha -> ghép lên nền trắng
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        rgb = img[:, :, :3].astype(np.float32)
        img = (rgb * alpha + 255 * (1 - alpha)).astype(np.uint8)
    return np.ascontiguousarray(img)


def imwrite(path, img, quality: int = 95) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower()
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if ext in (".jpg", ".jpeg") else []
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        raise IOError(f"Không ghi được ảnh: {path}")
    buf.tofile(str(path))


def pdf_page_count(pdf_path) -> int:
    import fitz

    with fitz.open(str(pdf_path)) as doc:
        return doc.page_count


def pdf_to_images(pdf_path, out_dir, dpi: int = 200, log=print, stop_event=None) -> list:
    """Tách PDF thành ảnh. Nếu trang chỉ là 1 ảnh scan (JPG/PNG, không alpha) thì lấy
    nguyên ảnh gốc để giữ chất lượng, ngược lại render trang theo DPI."""
    import fitz  # PyMuPDF

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*"):  # xoá ảnh của lần tách trước
        if old.is_file():
            old.unlink()
    doc = fitz.open(str(pdf_path))
    if doc.needs_pass:
        doc.close()
        raise RuntimeError("PDF có mật khẩu, không mở được.")
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    paths = []
    n = doc.page_count
    for i in range(n):
        if stop_event is not None and stop_event.is_set():
            break
        page = doc[i]
        saved = None
        try:
            imgs = page.get_images(full=True)
            if len(imgs) == 1 and imgs[0][1] == 0 and page.rotation == 0:  # không smask, không xoay
                info = doc.extract_image(imgs[0][0])
                ext = (info.get("ext") or "").lower()
                if ext in ("jpeg", "jpg", "png") and info.get("width", 0) >= 600:
                    p = out_dir / f"{i + 1:04d}.{'jpg' if ext == 'jpeg' else ext}"
                    p.write_bytes(info["image"])
                    if imread(p) is not None:
                        saved = p
                    else:
                        p.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            saved = None
        if saved is None:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            saved = out_dir / f"{i + 1:04d}.png"
            pix.save(str(saved))
        paths.append(str(saved))
        if (i + 1) % 10 == 0 or i + 1 == n:
            log(f"  Đã tách {i + 1}/{n} trang PDF")
    doc.close()
    return paths


def export_pdf(image_paths, pdf_path, quality: int = 90) -> None:
    """Gộp các trang đã dịch thành 1 file PDF (ảnh nén JPEG để file gọn)."""
    import fitz

    doc = fitz.open()
    for p in image_paths:
        img = imread(p)
        if img is None:
            continue
        h, w = img.shape[:2]
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            continue
        pw, ph = w * 72 / 150, h * 72 / 150  # 150 DPI
        s = min(1.0, PDF_MAX_PT / max(pw, ph))  # trang webtoon rất dài -> thu nhỏ khổ giấy
        page = doc.new_page(width=pw * s, height=ph * s)
        page.insert_image(page.rect, stream=buf.tobytes())
    if doc.page_count == 0:
        doc.close()
        return
    Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    Path(pdf_path).write_bytes(data)
