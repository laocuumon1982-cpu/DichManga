"""Tải sẵn model về thư mục models/ (dùng cho bản portable chạy offline).

Cách dùng:  python prefetch_models.py zh ja en
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.paths import MODELS_DIR, easyocr_dir, setup_env  # noqa: E402

setup_env()


def step(msg):
    print(f"\n=== {msg} ===", flush=True)


def hf_model(model_id):
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    AutoTokenizer.from_pretrained(model_id)
    m = AutoModelForSeq2SeqLM.from_pretrained(model_id)
    del m


def main(langs):
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print("Thư mục model:", MODELS_DIR)
    import easyocr
    from huggingface_hub import snapshot_download

    from core.ocr import EASYOCR_LANGS
    from core.translators import CT2_REPOS, CT2_SUBFOLDER

    mdir = easyocr_dir()
    kw = {"model_storage_directory": mdir} if mdir else {}
    for lang in langs:
        step(f"EasyOCR ({lang})")
        easyocr.Reader(EASYOCR_LANGS[lang], gpu=False, verbose=False, **kw)

    if "zh" in langs or "zh_tw" in langs:
        for mid in ("ngocdang83/HachimiMT-60-zh-vi",):
            step(f"Model dịch {mid}")
            hf_model(mid)
            snapshot_download(mid, allow_patterns=["*.json", "*.spm", "*.model", "*.txt", f"{CT2_SUBFOLDER}/*"])

    if "ja" in langs:
        step("manga-ocr (OCR tiếng Nhật)")
        from manga_ocr import MangaOcr

        MangaOcr(force_cpu=True)
        mid = "facebook/nllb-200-distilled-600M"
        step(f"Model dịch {mid} (~2.4 GB)")
        hf_model(mid)
        try:
            snapshot_download(CT2_REPOS[mid][0])  # bản CPU nhanh
        except Exception as e:  # noqa: BLE001
            print("  (bỏ qua bản CTranslate2:", e, ")")

    print("\nĐã tải xong toàn bộ model.")


if __name__ == "__main__":
    args = [a.lower() for a in sys.argv[1:]] or ["zh", "ja", "en"]
    main([a for a in args if a in ("zh", "zh_tw", "ja", "en")])
