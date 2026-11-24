"""Xoá chữ bằng AI: LaMa tinh chỉnh cho manga/anime (AnimeMangaInpainting, giấy phép MIT).

Model (~200 MB) tải một lần từ nguồn gốc trên GitHub, kiểm tra SHA-256, lưu ở models/inpaint/.
Bản TorchScript nên không cần mã nguồn kiến trúc – chỉ cần PyTorch. Chạy GPU nếu có.
Dùng cho chữ nằm trên hình / nền lưới chấm; bóng thoại nền phẳng vẫn tô thẳng màu nền (nhanh, sạch).
"""
import hashlib
import threading
from pathlib import Path

import cv2
import numpy as np

from .paths import MODELS_DIR

LAMA_URL = "https://github.com/Sanster/models/releases/download/AnimeMangaInpainting/anime-manga-big-lama.pt"
LAMA_SHA256 = "479d3afdcb7ed2fd944ed4ebcc39ca45b33491f0f2e43eb1000bd623cfb41823"
LAMA_SIZE = 205717870
LAMA_PATH = MODELS_DIR / "inpaint" / "anime-manga-big-lama.pt"
MAX_SIDE = 1536  # vùng lớn hơn thì thu nhỏ khi đưa vào model (đỡ tốn VRAM / thời gian)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_ready() -> bool:
    """Đã có model và đúng checksum? (checksum đầy đủ chỉ tính 1 lần, ghi dấu ra file .ok)"""
    p = LAMA_PATH
    if not p.is_file() or p.stat().st_size != LAMA_SIZE:
        return False
    stamp = p.with_suffix(p.suffix + ".ok")
    key = f"{LAMA_SHA256}:{LAMA_SIZE}:{int(p.stat().st_mtime)}"
    if stamp.is_file() and stamp.read_text().strip() == key:
        return True
    if _sha256(p) != LAMA_SHA256:
        return False
    stamp.write_text(key)
    return True


def download_model(log=print, stop_event=None) -> Path:
    """Tải model LaMa từ GitHub (nguồn gốc), kiểm tra SHA-256."""
    if model_ready():
        return LAMA_PATH
    import requests

    LAMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LAMA_PATH.with_suffix(".part")
    log("Đang tải model xoá chữ LaMa (~200 MB, chỉ tải 1 lần)...")
    with requests.get(LAMA_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or LAMA_SIZE)
        done, last = 0, -1
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError("Đã dừng khi đang tải model")
                f.write(chunk)
                done += len(chunk)
                pct = int(100 * done / max(1, total))
                if pct // 20 != last:
                    last = pct // 20
                    log(f"  LaMa: {pct}%")
    if _sha256(tmp) != LAMA_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("File model LaMa tải về bị lỗi (sai SHA-256) – thử lại sau")
    tmp.replace(LAMA_PATH)
    model_ready()
    return LAMA_PATH


class LamaInpainter:
    def __init__(self, device: str = "cpu", log=print, stop_event=None):
        import torch

        self.torch = torch
        self.device = device
        self.lock = threading.Lock()
        path = download_model(log, stop_event)
        log(f"Đang nạp model xoá chữ LaMa lên {device.upper()}...")
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.model = torch.jit.load(str(path), map_location=device).eval()

    def _run(self, rgb, mask):
        """rgb uint8 HxWx3, mask uint8 HxW (>0 = xoá) – kích thước bội số của 8."""
        torch = self.torch
        ti = torch.from_numpy(rgb).permute(2, 0, 1)[None].float().to(self.device) / 255.0
        tm = (torch.from_numpy(mask)[None, None].to(self.device) > 0).float()
        with torch.inference_mode():
            out = self.model(ti, tm)[0].permute(1, 2, 0).float().cpu().numpy()
        return (out.clip(0, 1) * 255).astype(np.uint8)

    def inpaint(self, img_bgr, mask):
        """Xoá vùng mask (uint8, >0) trên ảnh BGR. Xử lý từng cụm vùng xoá kèm phần nền xung
        quanh (LaMa cần thấy hoạ tiết xung quanh mới dựng lại được lưới chấm)."""
        m = (mask > 0).astype(np.uint8) * 255
        if not m.any():
            return img_bgr.copy()
        H, W = img_bgr.shape[:2]
        out = img_bgr.copy()
        n, _lab, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(m, np.ones((41, 41), np.uint8)))
        for i in range(1, n):
            x, y, w, h = stats[i, :4]
            p = int(min(160, max(32, 0.35 * max(w, h))))
            x0, y0, x1, y1 = max(0, x - p), max(0, y - p), min(W, x + w + p), min(H, y + h + p)
            crop, cm = img_bgr[y0:y1, x0:x1], m[y0:y1, x0:x1]
            if not cm.any():
                continue
            ch, cw = crop.shape[:2]
            scale = min(1.0, MAX_SIDE / max(ch, cw))
            if scale < 1.0:
                sw_, sh_ = max(8, int(cw * scale)), max(8, int(ch * scale))
                crop_s = cv2.resize(crop, (sw_, sh_), interpolation=cv2.INTER_AREA)
                cm_s = cv2.resize(cm, (sw_, sh_), interpolation=cv2.INTER_NEAREST)
            else:
                crop_s, cm_s = crop, cm
            sh, sw = crop_s.shape[:2]
            ph, pw = (sh + 7) // 8 * 8, (sw + 7) // 8 * 8
            rgb = cv2.cvtColor(crop_s, cv2.COLOR_BGR2RGB)
            rgb = cv2.copyMakeBorder(rgb, 0, ph - sh, 0, pw - sw, cv2.BORDER_REFLECT)
            mk = cv2.copyMakeBorder(cm_s, 0, ph - sh, 0, pw - sw, cv2.BORDER_CONSTANT, value=0)
            with self.lock:  # nhiều luồng vẽ dùng chung 1 model
                res = self._run(rgb, mk)
            res = cv2.cvtColor(res[:sh, :sw], cv2.COLOR_RGB2BGR)
            if scale < 1.0:
                res = cv2.resize(res, (cw, ch), interpolation=cv2.INTER_CUBIC)
            keep = cm[..., None] > 0
            out[y0:y1, x0:x1] = np.where(keep, res, out[y0:y1, x0:x1])
        return out
