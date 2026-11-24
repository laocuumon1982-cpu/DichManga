"""Điều phối: đọc trang -> OCR (GPU) -> dịch -> xoá chữ (LaMa) -> vẽ chữ Việt -> lưu.

- Bộ dịch máy (HachimiMT / NLLB / GTX): 3 công đoạn chạy song song (dây chuyền) – trong lúc GPU
  đọc chữ trang N+1, trang N đang được dịch và các trang trước đó đang được vẽ chữ.
- Bộ dịch AI (LLM): đọc chữ cả chương trước, dịch một lượt theo ngữ cảnh, rồi mới vẽ chữ.
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
from .exporter import write_text_export  # noqa: F401  (main.py dùng)
from .loader import imread, imwrite, list_images, pdf_to_images
from .typeset import clean_page, render_page

MODES_LLM = "llm"


@dataclass
class Config:
    src_lang: str = "zh"          # zh | zh_tw | ja | en
    device: str = "auto"          # auto (ưu tiên GPU) | cuda | cpu
    engine: str = "local:ngocdang83/HachimiMT-60-zh-vi"  # "gtx" | "llm" | "local:<model Hugging Face>"
    gtx_fallback: bool = True     # câu model local / AI bỏ trống -> nhờ GTX dịch bù (nếu có mạng)
    use_lama: bool = True         # xoá chữ trên hình bằng AI LaMa (không thì OpenCV)
    use_glossary: bool = True     # dùng bảng thuật ngữ
    llm_provider: str = "ollama"  # xem core/llm.py PROVIDERS (API key KHÔNG lưu ở đây)
    llm_url: str = ""
    llm_model: str = ""
    llm_style: str = ""
    llm_notes: str = ""
    export_xlsx: bool = True      # xuất Excel lời thoại
    export_psd: bool = False      # xuất PSD 3 lớp (gốc / nền sạch / chữ)
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


def rerender_page(page: dict, font_path: str, uppercase: bool, font_scale: int = 70) -> None:
    """Vẽ lại 1 trang từ ảnh đã xoá chữ + bản dịch (sau khi sửa / đổi font)."""
    clean = imread(page["clean"])
    if clean is None:
        raise RuntimeError(f"Thiếu ảnh đã xoá chữ: {page['clean']}")
    src = imread(page["src"]) if page.get("src") else None
    blocks = [TextBlock.from_dict(d) for d in page["blocks"]]
    imwrite(page["out"], render_page(clean, blocks, font_path, uppercase, src, font_scale / 100))
    page["blocks"] = [b.to_dict() for b in blocks]  # cập nhật loại bóng / cờ tràn chữ


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


_LAMA_CACHE = {}


def get_lama(device: str, log, stop_event=None):
    from .inpaint import LamaInpainter

    if device not in _LAMA_CACHE:
        _LAMA_CACHE.clear()
        _LAMA_CACHE[device] = LamaInpainter(device, log, stop_event)
    return _LAMA_CACHE[device]


def default_engine(src_lang: str) -> str:
    if src_lang == "en":
        return "gtx"
    return "local:facebook/nllb-200-distilled-600M" if src_lang == "ja" else "local:ngocdang83/HachimiMT-60-zh-vi"


class Pipeline:
    def __init__(self, cfg: Config, log=print, stop_event=None, api_key: str = ""):
        self.cfg = cfg
        self.log = log
        self.stop = stop_event or threading.Event()
        self.api_key = api_key  # chỉ giữ trong bộ nhớ, không ghi vào project.json
        self.out = Path(cfg.out_dir)
        self.work = self.out / "_work"
        self.project_path = str(self.work / "project.json")
        self.source_name = "truyen"
        self.ocr = None
        self.gtx = None
        self.local = None
        self.llm = None
        self.lama = None
        self.glossary = None

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

    def load_models(self, need_ocr: bool = True, need_clean: bool = True) -> None:
        from .translators import GTXTranslator

        dev = resolve_device(self.cfg.device)
        has, info = gpu_info()
        self.log(f"Thiết bị xử lý: {'GPU ' + info if dev == 'cuda' else 'CPU'}")
        if dev == "cpu" and self.cfg.device == "auto":
            self.log(f"  ({info})")
        if need_ocr:
            self.ocr = get_ocr(self.cfg.src_lang, dev == "cuda", self.log)
        if need_clean and self.cfg.use_lama:
            try:
                self.lama = get_lama(dev, self.log, self.stop)
                self.log(f"Xoá chữ trên hình: AI LaMa ({dev.upper()})")
            except Exception as e:  # noqa: BLE001
                self.lama = None
                self.log(f"! Không dùng được LaMa ({e}) – xoá chữ bằng OpenCV")
        if self.cfg.use_glossary:
            try:
                from .store import Glossary

                self.glossary = Glossary()
            except Exception as e:  # noqa: BLE001
                self.log(f"! Không mở được bảng thuật ngữ: {e}")
        self.gtx = GTXTranslator(self.log)
        self.local = None
        self.llm = None
        engine = self.cfg.engine or default_engine(self.cfg.src_lang)
        if engine == MODES_LLM:
            from .llm import PROVIDERS, LLMClient

            self.llm = LLMClient(self.cfg.llm_provider, self.cfg.llm_url, self.cfg.llm_model, self.api_key)
            self.log(f"Bộ dịch: AI {PROVIDERS[self.cfg.llm_provider][0]} – model {self.llm.model or '?'} "
                     "(dịch cả chương theo ngữ cảnh)")
            return
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

    # ---------------- dịch ----------------
    def _post(self, res):
        if self.glossary is not None:
            res = self.glossary.apply_post(res, self.cfg.src_lang)
        return res

    def translate(self, texts):
        """Dịch 1 trang (bộ dịch máy). Câu rỗng giữ rỗng."""
        if not texts:
            return []
        if self.local is None:
            src = self.glossary.apply_pre(texts, self.cfg.src_lang) if self.glossary is not None else texts
            return self._post(self.gtx.translate(src, self.cfg.src_lang))
        res = self.local.translate(texts, self.cfg.src_lang)
        miss = [i for i, t in enumerate(res) if not t.strip()]
        if miss and self.cfg.gtx_fallback:
            try:
                for i, t in zip(miss, self.gtx.translate([texts[i] for i in miss], self.cfg.src_lang)):
                    res[i] = t
            except Exception:  # noqa: BLE001
                pass
        return self._post(res)

    def translate_chapter(self, pages_blocks, progress=None):
        """Dịch cả chương bằng AI: pages_blocks = [(index trang, [TextBlock])]. Ghi .translation tại chỗ."""
        from .llm import translate_chapter

        items, refs = [], []
        for idx, blocks in pages_blocks:
            for b in blocks:
                if b.keep or not b.text.strip():
                    continue
                items.append({"id": len(items) + 1, "page": idx + 1, "text": b.text, "kind": b.kind})
                refs.append(b)
        if not items:
            return
        terms = self.glossary.terms_for(self.cfg.src_lang, [it["text"] for it in items]) \
            if self.glossary is not None else []
        if terms:
            self.log(f"  Dùng {len(terms)} thuật ngữ từ bảng thuật ngữ")
        got = translate_chapter(self.llm, self.cfg.src_lang, items, terms, self.cfg.llm_style,
                                self.cfg.llm_notes, self.log, progress, self.stop)
        miss = [k for k, it in enumerate(items) if not got.get(it["id"])]
        if miss and self.cfg.gtx_fallback and not self.stop.is_set():
            self.log(f"  {len(miss)} câu AI chưa dịch được → GTX dịch bù")
            try:
                fb = self.gtx.translate([items[k]["text"] for k in miss], self.cfg.src_lang)
                for k, t in zip(miss, fb):
                    if t:
                        got[items[k]["id"]] = t
            except Exception as e:  # noqa: BLE001
                self.log(f"  ! GTX lỗi: {e}")
        vals = self._post([got.get(it["id"], "") for it in items])
        for b, v in zip(refs, vals):
            b.translation = v

    # ---------------- vẽ 1 trang ----------------
    def _render(self, i, src, img, blocks, ext):
        clean = clean_page(img, blocks, self.lama)
        clean_path = self.work / "clean" / f"{i + 1:04d}.png"
        imwrite(clean_path, clean)
        out_path = self.out / f"{i + 1:04d}.{ext}"
        imwrite(out_path, render_page(clean, blocks, self.cfg.font_path, self.cfg.uppercase, img,
                                      self.cfg.font_scale / 100))
        return {"index": i, "src": str(src), "clean": str(clean_path), "out": str(out_path),
                "blocks": [b.to_dict() for b in blocks]}

    def _new_project(self):
        cfg = asdict(self.cfg)
        return {"version": 4, "source": self.source_name, "config": cfg, "pages": []}

    def run(self, pages, progress=None, page_done=None) -> bool:
        """progress(xong, tổng, mô tả). Chế độ AI: đọc chữ cả chương -> dịch 1 lượt -> vẽ."""
        if self.llm is not None:
            return self._run_chapter(pages, progress, page_done)
        return self._run_stream(pages, progress, page_done)

    def _finish(self, project, n, t_all, failed):
        if self.stop.is_set():
            self.log("Đã dừng theo yêu cầu.")
        if project["pages"]:
            self.export_all(project)
        if failed:
            self.log(f"Lưu ý: {failed} khung chưa dịch được – giữ chữ gốc, "
                     "có thể gõ bản dịch trong bảng rồi bấm Lưu (xem tab Tình trạng).")
        dt = time.time() - t_all
        k = len(project["pages"])
        speed = f" (~{dt / k:.1f}s/trang)" if k else ""
        self.log(f"Xong {k}/{n} trang trong {dt:.0f}s{speed}.")
        return not self.stop.is_set()

    def _run_stream(self, pages, progress, page_done) -> bool:
        ext = "png" if self.cfg.img_format == "png" else "jpg"
        project = self._new_project()
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
            page = self._render(i, src, img, blocks, ext)
            miss = sum(1 for b in blocks if not b.translation and not b.keep)
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
                progress(done, n, f"Trang {done}/{n}")

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
                        progress(state["done"], n, f"Trang {state['done']}/{n}")
                    continue
                if self.stop.is_set():  # đã bấm Dừng -> bỏ các trang còn trong hàng đợi
                    continue
                t0 = time.time()
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
        return self._finish(project, n, t_all, state["failed"])

    def _run_chapter(self, pages, progress, page_done) -> bool:
        """AI dịch theo ngữ cảnh: tiến độ chia 3 chặng – đọc chữ 45%, AI dịch 25%, vẽ chữ 30%."""
        ext = "png" if self.cfg.img_format == "png" else "jpg"
        project = self._new_project()
        n = len(pages)
        t_all = time.time()
        U = 1000  # thang tiến độ

        def prog(frac, text):
            if progress:
                progress(int(U * min(1.0, frac)), U, text)

        # 1. đọc chữ cả chương (ảnh đọc sẵn ở luồng phụ)
        read = []
        for i, src in enumerate(pages):
            if self.stop.is_set():
                break
            img = imread(src)
            if img is None:
                self.log(f"! Bỏ qua trang {i + 1}: không đọc được {Path(src).name}")
                continue
            t0 = time.time()
            try:
                blocks = self.ocr.process(img)
            except Exception as e:  # noqa: BLE001
                self.log(f"! Trang {i + 1}: lỗi OCR ({e})")
                blocks = []
            self.log(f"Đọc chữ trang {i + 1}/{n}: {len(blocks)} khung – {time.time() - t0:.1f}s")
            read.append((i, src, img, blocks))
            prog(0.45 * (i + 1) / n, f"Đọc chữ trang {i + 1}/{n}")
        if self.stop.is_set():
            return self._finish(project, n, t_all, 0)

        # 2. AI dịch cả chương một lượt
        self.log(f"AI đang dịch cả chương ({sum(len(r[3]) for r in read)} khung chữ)...")
        prog(0.45, "AI đang dịch cả chương...")
        self.translate_chapter([(i, blocks) for i, _s, _im, blocks in read],
                               progress=lambda k, m: prog(0.45 + 0.25 * k / max(1, m),
                                                          f"AI đang dịch phần {min(k + 1, m)}/{m}"))
        # 3. xoá chữ + vẽ chữ song song
        lock = threading.Lock()
        state = {"done": 0, "failed": 0}

        def render_one(i, src, img, blocks):
            page = self._render(i, src, img, blocks, ext)
            miss = sum(1 for b in blocks if not b.translation and not b.keep)
            with lock:
                project["pages"].append(page)
                project["pages"].sort(key=lambda p: p["index"])
                save_project(project, self.project_path)
                state["done"] += 1
                state["failed"] += miss
                d = state["done"]
            if page_done:
                page_done(i, page)
            prog(0.70 + 0.30 * d / max(1, len(read)), f"Vẽ chữ trang {d}/{len(read)}")

        with ThreadPoolExecutor(max_workers=3) as pool:
            futs = [pool.submit(render_one, *r) for r in read if not self.stop.is_set()]
            for f in futs:
                try:
                    f.result()
                except Exception as e:  # noqa: BLE001
                    self.log(f"! Lỗi khi vẽ/ghi trang: {e}")
        return self._finish(project, n, t_all, state["failed"])

    # ---------------- dịch lại dự án đã có (không đọc lại chữ) ----------------
    def retranslate(self, project, progress=None, page_done=None, only_empty=False) -> bool:
        """Dịch lại mọi khung của dự án bằng bộ dịch đang chọn (vd. sau khi sửa bảng thuật ngữ),
        rồi vẽ lại. only_empty=True: chỉ dịch các khung đang trống."""
        t_all = time.time()
        pages = project["pages"]
        cfg = project.setdefault("config", {})
        U = 1000

        def prog(frac, text):
            if progress:
                progress(int(U * min(1.0, frac)), U, text)

        blocks_by_page = [(p["index"], [TextBlock.from_dict(d) for d in p["blocks"]]) for p in pages]
        if only_empty:
            todo = [(i, [b for b in bl if not b.translation]) for i, bl in blocks_by_page]
        else:
            todo = blocks_by_page
        prog(0.02, "Đang dịch lại...")
        if self.llm is not None:
            self.translate_chapter(todo, progress=lambda k, m: prog(0.6 * k / max(1, m),
                                                                    f"AI đang dịch phần {min(k + 1, m)}/{m}"))
        else:
            for k, (i, bl) in enumerate(todo):
                if self.stop.is_set():
                    break
                sel = [b for b in bl if not b.keep]
                for b, t in zip(sel, self.translate([b.text for b in sel])):
                    b.translation = t
                prog(0.6 * (k + 1) / max(1, len(todo)), f"Dịch lại trang {k + 1}/{len(todo)}")
        for k, (p, (_i, bl)) in enumerate(zip(pages, blocks_by_page)):
            if self.stop.is_set():
                break
            p["blocks"] = [b.to_dict() for b in bl]
            rerender_page(p, self.cfg.font_path or cfg.get("font_path", ""), self.cfg.uppercase,
                          self.cfg.font_scale)
            if page_done:
                page_done(p["index"], p)
            prog(0.6 + 0.4 * (k + 1) / len(pages), f"Vẽ lại trang {k + 1}/{len(pages)}")
        cfg.update({k: v for k, v in asdict(self.cfg).items() if k != "out_dir"})
        save_project(project, self.project_path)
        self.export_all(project)
        self.log(f"Đã dịch lại {len(pages)} trang trong {time.time() - t_all:.0f}s.")
        return not self.stop.is_set()

    # ---------------- xuất file ----------------
    def export_all(self, project):
        from .exporter import export_extras

        export_extras(project, self.out, self.cfg, self.log)
