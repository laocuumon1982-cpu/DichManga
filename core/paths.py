"""Đường dẫn & môi trường dùng chung (bản cài thường và bản portable).

Bản portable có cấu trúc:
    DichTruyenTranh_v2.0_Portable/
        DichTruyenTranh.exe (trình khởi động)
        python/             (Python nhúng + thư viện)
        app/                (main.py, core/, fonts/, icon.ico)
        models/             (model OCR + model dịch, mang theo được)
"""
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = APP_DIR.parent
IS_PORTABLE = (ROOT_DIR / "python" / "python.exe").exists() and APP_DIR.name.lower() == "app"
MODELS_DIR = (ROOT_DIR if IS_PORTABLE else APP_DIR) / "models"
ICON_PATH = APP_DIR / "icon.ico"


def setup_env() -> None:
    """Gọi trước khi import torch / transformers / easyocr."""
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    if IS_PORTABLE or MODELS_DIR.exists():
        # model nằm cạnh app -> chép cả thư mục sang máy khác là chạy được
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(MODELS_DIR / "huggingface"))
        os.environ.setdefault("TORCH_HOME", str(MODELS_DIR / "torch"))
        os.environ.setdefault("EASYOCR_MODULE_PATH", str(MODELS_DIR / "easyocr"))
    # pythonw.exe (không có cửa sổ console) -> stdout/stderr là None, thư viện in log sẽ lỗi
    log_path = APP_DIR / "app_log.txt"
    if sys.stdout is None or sys.stderr is None:
        try:
            f = open(log_path, "a", encoding="utf-8", buffering=1)
        except OSError:
            f = open(os.devnull, "w", encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = f
        if sys.stderr is None:
            sys.stderr = f


def easyocr_dir():
    """Thư mục model EasyOCR (None = mặc định ~/.EasyOCR)."""
    p = os.environ.get("EASYOCR_MODULE_PATH")
    return str(Path(p) / "model") if p else None
