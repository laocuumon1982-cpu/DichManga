"""Điều phối: đọc trang -> OCR (GPU) -> dịch (local GPU / GTX) -> xoá chữ -> vẽ chữ Việt -> lưu.

3 công đoạn chạy song song (dây chuyền): trong lúc GPU đọc chữ trang N+1, trang N đang
được dịch và các trang trước đó đang được vẽ chữ / ghi file trên các luồng CPU.
"""
import json
import queue
from concurrent.futures import ThreadPoolExecutor
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .block import TextBlock
from .loader import export_pdf, imread, imwrite, list_images, pdf_to_images
from .typeset import clean_page, render_page


@dataclass
class Config:
    src_lang: str = "zh"          # zh | zh_tw | ja | en
    device: str = "auto"          # auto (ưu tiên GPU) | cuda | cpu
    engine: str = "local:ngocdang83/HachimiMT-60-zh-vi"  # "gtx" | "local:<model Hugging Face>"
    gtx_fallback: bool = True     # câu model local bỏ trống -> nhờ GTX dịch bù (nếu có mạng)
    font_path: str = ""
    uppercase: bool = False
    font_scale: int = 70          # cỡ chữ tối đa, % so với chữ gốc
    pdf_dpi: int = 200
    img_format: str = "jpg"       # jpg | png
    export_pdf: bool = True
    out_dir: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


# ---------------- GPU ----------------
def nvidia_gpu_name() -> str:
    """Tên card NVIDIA theo driver (không cần PyTorch). Rỗng nếu không có."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return ""
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        out = subprocess.run([exe, "--query-gpu=name", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=5, creationflags=flags)
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
    except Exception:  # noqa: BLE001
        return ""


def gpu_info():
    """(PyTorch dùng được CUDA?, mô tả trạng thái)."""
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
            return True, f"{name} ({vram:.0f} GB) – CUDA {torch.version.cuda}"
        card = nvidia_gpu_name()
        if card:
            if torch.version.cuda is None:
                return False, (f"Máy có {card} nhưng đang cài PyTorch bản CPU – "
                               "chạy lại install.bat để dùng GPU")
            return False, f"Máy có {card} nhưng CUDA không khởi động được – hãy cập nhật driver NVIDIA"
        return False, "Không có GPU NVIDIA – chạy bằng CPU"
    except Exception as e:  # noqa: BLE001
        return False, f"Chưa cài PyTorch ({e.__class__.__name__}) – chạy install.bat"


def resolve_device(pref: str) -> str:
    has, why = gpu_info()
    if pref == "cpu":
        return "cpu"
    if pref == "cuda" and not has:
        raise RuntimeError(f"Đã chọn GPU nhưng không dùng được: {why}. Chuyển Thiết bị sang Tự động/CPU.")
    return "cuda" if has else "cpu"


# ---------------- dự án ----------------
def save_project(project: dict, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_project(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_text_export(project: dict, path) -> None:
    out = []
    for p in project["pages"]:
        out.append(f"===== Trang {p['index'] + 1} =====")
        for k, b in enumerate(p["blocks"], 1):
            out.append(f"[{k}] {b['text']}\n    → {b['translation']}")
        out.append("")
    Path(path).write_text("\n".join(out), encoding="utf-8")


def rerender_page(page: dict, font_path: str, uppercase: bool, font_scale: int = 70) -> None:
    """Vẽ lại 1 trang từ ảnh đã xoá chữ + bản dịch (sau khi sửa / đổi font)."""
    clean = imread(page["clean"])
    if clean is None:
        raise RuntimeError(f"Thiếu ảnh đã xoá chữ: {page['clean']}")
    src = imread(page["src"]) if page.get("src") else None
    blocks = [TextBlock.from_dict(d) for d in page["blocks"]]
    imwrite(page["out"], render_page(clean, blocks, font_path, uppercase, src, font_scale / 100))


# Giữ model OCR trong bộ nhớ giữa các lần bấm "Bắt đầu" (khỏi tải lại lên GPU)
_OCR_CACHE = {}


def get_ocr(lang: str, use_gpu: bool, log):
    from .ocr import OCREngine

    key = (lang, use_gpu)
    if key not in _OCR_CACHE:
        _OCR_CACHE.clear()  # chỉ giữ 1 bộ để đỡ tốn VRAM
        try:
            import gc

            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        _OCR_CACHE[key] = OCREngine(lang, use_gpu=use_gpu, log=log)
    else:
        _OCR_CACHE[key].log = log
    return _OCR_CACHE[key]


_TR_CACHE = {}


def get_local_translator(model_id: str, device: str, src_lang: str, log):
    from .translators import LocalTranslator

    key = (model_id, device, src_lang)
    if key not in _TR_CACHE:
        _TR_CACHE.clear()
        _TR_CACHE[key] = LocalTranslator(model_id, device, src_lang, log)
    else:
        _TR_CACHE[key].log = log
    return _TR_CACHE[key]


def default_engine(src_lang: str) -> str:
    if src_lang == "en":
        return "gtx"
    return "local:facebook/nllb-200-distilled-600M" if src_lang == "ja" else "local:ngocdang83/HachimiMT-60-zh-vi"


class Pipeline:
    def __init__(self, cfg: Config, log=print, stop_event=None):
        self.cfg = cfg
        self.log = log
        self.stop = stop_event or threading.Event()
        self.out = Path(cfg.out_dir)
        self.work = self.out / "_work"
        self.project_path = str(self.work / "project.json")
        self.source_name = "truyen"
        self.ocr = None
        self.gtx = None

    def prepare_pages(self, source_type: str, source_path: str) -> list:
        self.source_name = Path(source_path).stem or "truyen"
        (self.work / "clean").mkdir(parents=True, exist_ok=True)
        if source_type == "pdf":
            self.log(f"Tách trang từ PDF: {Path(source_path).name} (DPI {self.cfg.pdf_dpi})")
            pages = pdf_to_images(source_path, self.work / "src", self.cfg.pdf_dpi, self.log, self.stop)
        else:
            pages = list_images(source_path)
        if not pages:
            raise RuntimeError("Không tìm thấy trang ảnh nào (jpg, png, webp, bmp).")
        self.log(f"Tổng cộng {len(pages)} trang.")
        return pages

    def load_models(self) -> None:
        from .translators import GTXTranslator

        dev = resolve_device(self.cfg.device)
        has, info = gpu_info()
        self.log(f"Thiết bị xử lý: {'GPU ' + info if dev == 'cuda' else 'CPU'}")
        if dev == "cpu" and self.cfg.device == "auto":
            self.log(f"  ({info})")
        self.ocr = get_ocr(self.cfg.src_lang, dev == "cuda", self.log)
        self.gtx = GTXTranslator(self.log)
        self.local = None
        engine = self.cfg.engine or default_engine(self.cfg.src_lang)
        if self.cfg.src_lang == "en":
            engine = "gtx"  # tiếng Anh dịch bằng GTX
        if engine.startswith("local:"):
            model_id = engine.split(":", 1)[1]
            if self.cfg.src_lang == "ja" and "zh-vi" in model_id.lower():
                self.log("HachimiMT chỉ dịch tiếng Trung → dùng NLLB-200 cho tiếng Nhật.")
                model_id = "facebook/nllb-200-distilled-600M"
            try:
                self.local = get_local_translator(model_id, dev, self.cfg.src_lang, self.log)
                self.log(f"Bộ dịch: {model_id} (chạy trên máy)")
            except Exception as e:  # noqa: BLE001
                self.log(f"! Không tải được model {model_id}: {e}\n  → Chuyển sang GTX Google.")
        if self.local is None:
            self.log("Bộ dịch: GTX Google Translate (miễn phí, cần Internet)")

    def translate(self, texts):
        if not texts:
            return []
        if self.local is None:
            return self.gtx.translate(texts, self.cfg.src_lang)
        res = self.local.translate(texts, self.cfg.src_lang)
        miss = [i for i, t in enumerate(res) if not t.strip()]
        if miss and self.cfg.gtx_fallback:
            try:
                for i, t in zip(miss, self.gtx.translate([texts[i] for i in miss], self.cfg.src_lang)):
                    res[i] = t
            except Exception:  # noqa: BLE001
                pass
        return res

    def run(self, pages, progress=None, page_done=None) -> bool:
        """progress(số trang xong, tổng số trang)."""
        ext = "png" if self.cfg.img_format == "png" else "jpg"
        project = {"version": 3, "source": self.source_name, "config": asdict(self.cfg), "pages": []}
        n = len(pages)
        t_all = time.time()
        lock = threading.Lock()
        state = {"done": 0, "failed": 0}
        q = queue.Queue(maxsize=3)   # OCR -> dịch
        SENTINEL = object()

        # ----- công đoạn 1: đọc ảnh + OCR (GPU) trên luồng riêng -----
        def ocr_stage():
            try:
                for i, src in enumerate(pages):
                    if self.stop.is_set():
                        break
                    t0 = time.time()
                    img = imread(src)
                    if img is None:
                        self.log(f"! Bỏ qua trang {i + 1}: không đọc được {Path(src).name}")
                        q.put((i, src, None, [], 0.0))
                        continue
                    try:
                        blocks = self.ocr.process(img)
                    except Exception as e:  # noqa: BLE001
                        self.log(f"! Trang {i + 1}: lỗi OCR ({e}) – giữ nguyên trang gốc")
                        blocks = []
                    q.put((i, src, img, blocks, time.time() - t0))
            finally:
                q.put(SENTINEL)

        # ----- công đoạn 3: xoá chữ + vẽ chữ + ghi file (CPU, nhiều luồng) -----
        def render_stage(i, src, img, blocks, t_ocr, t_tr):
            t0 = time.time()
            clean = clean_page(img, blocks)
            clean_path = self.work / "clean" / f"{i + 1:04d}.png"
            imwrite(clean_path, clean)
            out_path = self.out / f"{i + 1:04d}.{ext}"
            imwrite(out_path, render_page(clean, blocks, self.cfg.font_path, self.cfg.uppercase, img,
                                            self.cfg.font_scale / 100))
            page = {"index": i, "src": str(src), "clean": str(clean_path), "out": str(out_path),
                    "blocks": [b.to_dict() for b in blocks]}
            miss = sum(1 for b in blocks if not b.translation)
            with lock:
                project["pages"].append(page)
                project["pages"].sort(key=lambda p: p["index"])
                save_project(project, self.project_path)
                state["done"] += 1
                state["failed"] += miss
                done = state["done"]
            note = f", {miss} khung chưa dịch" if miss else ""
            self.log(f"Trang {i + 1}/{n}: {len(blocks)} khung{note} – OCR {t_ocr:.1f}s, "
                     f"dịch {t_tr:.1f}s, vẽ {time.time() - t0:.1f}s")
            if page_done:
                page_done(i, page)
            if progress:
                progress(done, n)

        th = threading.Thread(target=ocr_stage, daemon=True)
        th.start()
        futures = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            # ----- công đoạn 2: dịch (trên luồng hiện tại) -----
            while True:
                item = q.get()
                if item is SENTINEL:
                    break
                i, src, img, blocks, t_ocr = item
                if img is None:
                    with lock:
                        state["done"] += 1
                    if progress:
                        progress(state["done"], n)
                    continue
                if self.stop.is_set():  # đã bấm Dừng -> bỏ các trang còn trong hàng đợi
                    continue
                t0 = time.time()
                if True:
                    try:
                        trans = self.translate([b.text for b in blocks])
                    except Exception as e:  # noqa: BLE001
                        self.log(f"! Trang {i + 1}: lỗi dịch ({e})")
                        trans = [""] * len(blocks)
                    for b, t in zip(blocks, trans):
                        b.translation = t
                futures.append(pool.submit(render_stage, i, src, img, blocks, t_ocr, time.time() - t0))
            for f in futures:
                try:
                    f.result()
                except Exception as e:  # noqa: BLE001
                    self.log(f"! Lỗi khi vẽ/ghi trang: {e}")
        th.join(timeout=5)
        if self.stop.is_set():
            self.log("Đã dừng theo yêu cầu.")

        if project["pages"]:
            write_text_export(project, self.out / "ban_dich.txt")
            if self.cfg.export_pdf:
                pdf = self.out / f"{self.source_name}_vi.pdf"
                self.log("Đang xuất PDF...")
                export_pdf([p["out"] for p in project["pages"]], pdf)
                self.log(f"Đã xuất PDF: {pdf.name}")
        if state["failed"]:
            self.log(f"Lưu ý: {state['failed']} khung chưa dịch được – giữ chữ gốc, "
                     "có thể gõ bản dịch trong bảng rồi bấm Lưu.")
        dt = time.time() - t_all
        k = len(project["pages"])
        speed = f" (~{dt / k:.1f}s/trang)" if k else ""
        self.log(f"Xong {k}/{n} trang trong {dt:.0f}s{speed}.")
        return not self.stop.is_set()
