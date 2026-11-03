"""Phát hiện & nhận dạng chữ trên trang truyện (chạy GPU nếu có).

- Phát hiện vùng chữ: EasyOCR (CRAFT). Ảnh webtoon dài được cắt thành nhiều đoạn
  chồng lên nhau để chữ không bị thu nhỏ quá mức.
- Nhận dạng tiếng Nhật: manga-ocr (đọc tốt chữ dọc, chữ viết tay trong manga).
- Nhận dạng tiếng Trung: EasyOCR (ch_sim / ch_tra). Cột chữ dọc được cắt thành
  từng ký tự rồi xếp ngang lại trước khi nhận dạng (EasyOCR chỉ đọc tốt chữ ngang).
"""
import re

import cv2
import numpy as np

from .block import TextBlock

CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]")
EASYOCR_LANGS = {"zh": ["ch_sim", "en"], "zh_tw": ["ch_tra", "en"], "ja": ["ja", "en"], "en": ["en"]}
LATIN_RE = re.compile(r"[A-Za-z].*[A-Za-z]")


def is_valid_text(t: str, lang: str) -> bool:
    """Bỏ nhiễu: tiếng Anh cần ≥ 2 chữ cái, tiếng Trung/Nhật cần ≥ 1 chữ CJK."""
    if lang == "en":
        return bool(LATIN_RE.search(t))
    return bool(CJK_RE.search(t))


def fix_english(t: str) -> str:
    """Chuẩn hoá chữ OCR truyện tiếng Anh: nối từ bị gạch nối xuống dòng, đổi CHỮ IN HOA
    toàn bộ (kiểu truyện tranh) về dạng câu thường để Google dịch chính xác hơn."""
    t = re.sub(r"(\w)- (\w)", r"\1\2", t)
    t = " ".join(t.split())
    letters = [c for c in t if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8:
        t = t.lower()
        t = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
        t = re.sub(r"\bi\b", "I", t)
        t = re.sub(r"\bi'", "I'", t)
    return t
MAX_CANVAS = 2560


def _unbatch(lst):
    """reader.detect trả về danh sách theo lô ảnh; lấy phần của ảnh đầu tiên."""
    if not lst:
        return []
    first = lst[0]
    if len(first) == 0:
        return []
    if isinstance(first[0], (list, tuple, np.ndarray)):
        return first
    return lst


def _area(r):
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def dedupe_rects(rects, contain_ratio: float = 0.7):
    """Bỏ khung trùng (do các đoạn cắt chồng nhau): khung nhỏ nằm phần lớn trong khung lớn."""
    rects = sorted(rects, key=_area, reverse=True)
    kept = []
    for r in rects:
        a = _area(r)
        if a == 0:
            continue
        dup = False
        for k in kept:
            ix = max(0, min(r[2], k[2]) - max(r[0], k[0]))
            iy = max(0, min(r[3], k[3]) - max(r[1], k[1]))
            if ix * iy >= contain_ratio * a:
                dup = True
                break
        if not dup:
            kept.append(r)
    return kept


def tile_ranges(H: int, W: int):
    """Các đoạn theo chiều dọc để phát hiện chữ (ảnh webtoon cao gấp nhiều lần chiều ngang)."""
    if H <= max(2.2 * W, MAX_CANVAS):
        return [(0, H)]
    th = int(max(1024, min(MAX_CANVAS, 1.5 * W)))
    ov = int(th * 0.25)
    step = th - ov
    out, y = [], 0
    while True:
        y1 = min(H, y + th)
        out.append((max(0, y1 - th), y1))
        if y1 >= H:
            break
        y += step
    return out


def group_rects(rects):
    """Gom các dòng/cột chữ gần nhau thành 1 khung thoại (union-find)."""
    n = len(rects)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    sizes = [max(1, min(r[2] - r[0], r[3] - r[1])) for r in rects]
    for i in range(n):
        a = rects[i]
        for j in range(i + 1, n):
            si, sj = sizes[i], sizes[j]
            if max(si, sj) > 2.2 * min(si, sj):  # cỡ chữ quá khác nhau -> khác khung
                continue
            b = rects[j]
            gap = 0.6 * min(si, sj)
            dx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
            dy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
            if dx <= gap and dy <= gap:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def clean_text(t: str, lang: str = "zh") -> str:
    if lang == "en":
        return fix_english(t or "")
    t = (t or "").replace("\n", "").strip()
    # bỏ khoảng trắng chen giữa các ký tự CJK
    t = re.sub(r"(?<=[　-鿿＀-￯])\s+(?=[　-鿿＀-￯])", "", t)
    return t


def vertical_to_horizontal(crop):
    """Cắt cột chữ dọc (ảnh xám) thành từng ký tự rồi xếp thành 1 dòng ngang."""
    h, w = crop.shape[:2]
    if h < 2 or w < 2:
        return crop
    _, bw = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    fg = (bw == 0) if (bw == 0).mean() < 0.5 else (bw == 255)  # mực = phần ít hơn
    prof = fg.sum(axis=1)
    ink = prof > max(1, int(0.02 * w))
    runs, start = [], None
    for y, v in enumerate(ink):
        if v and start is None:
            start = y
        elif not v and start is not None:
            runs.append([start, y])
            start = None
    if start is not None:
        runs.append([start, h])
    # gộp các mảnh của cùng 1 ký tự (vd. 三, 二) nếu tổng chiều cao ~ 1 ký tự
    cells = []
    for r in runs:
        if cells and r[1] - cells[-1][0] <= 1.15 * w:
            cells[-1][1] = r[1]
        else:
            cells.append(list(r))
    final = []
    for s, e in cells:  # mảnh quá dài (ký tự dính nhau) -> chia đều
        k = max(1, int(round((e - s) / max(1, w))))
        step = (e - s) / k
        for t in range(k):
            final.append((int(s + t * step), int(s + (t + 1) * step)))
    if not final:
        return crop
    bg = int(np.median(crop))
    tiles = []
    for s, e in final:
        seg = crop[max(0, s - 1):min(h, e + 1)]
        if seg.shape[0] < 2:
            continue
        if seg.shape[0] > w:
            seg = cv2.resize(seg, (w, w))
        tile = np.full((w, w), bg, np.uint8)
        off = (w - seg.shape[0]) // 2
        tile[off:off + seg.shape[0], :seg.shape[1]] = seg
        tiles.append(tile)
        tiles.append(np.full((w, max(2, w // 8)), bg, np.uint8))  # khoảng cách ký tự
    return np.hstack(tiles) if tiles else crop


class OCREngine:
    def __init__(self, lang: str, use_gpu: bool, log=print):
        import easyocr

        self.lang = lang
        self.log = log
        self.use_gpu = use_gpu
        log(f"Đang tải EasyOCR ({', '.join(EASYOCR_LANGS[lang])}) trên {'GPU' if use_gpu else 'CPU'}...")
        from .paths import easyocr_dir

        mdir = easyocr_dir()
        kw = {"model_storage_directory": mdir} if mdir else {}
        self.reader = easyocr.Reader(EASYOCR_LANGS[lang], gpu=use_gpu, verbose=False, **kw)
        self.mocr = None
        if lang == "ja":
            log(f"Đang tải manga-ocr cho tiếng Nhật trên {'GPU' if use_gpu else 'CPU'}...")
            from manga_ocr import MangaOcr

            self.mocr = MangaOcr(force_cpu=not use_gpu)

    # ---------- phát hiện ----------
    def _detect_once(self, rgb):
        h, w = rgb.shape[:2]
        h_list, f_list = self.reader.detect(
            rgb,
            min_size=8,
            text_threshold=0.6,
            low_text=0.35,
            link_threshold=0.4,
            canvas_size=int(min(MAX_CANVAS if self.use_gpu else 1600, max(h, w))),
            mag_ratio=1.0,
            width_ths=0.7 if self.lang == "en" else 0.3,
            height_ths=0.5,
            add_margin=0.05,
        )
        rects = []
        for box in _unbatch(h_list):
            x0, x1, y0, y1 = [int(v) for v in box[:4]]
            rects.append([x0, y0, x1, y1])
        for poly in _unbatch(f_list):
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            rects.append([int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))])
        return rects

    def detect(self, img_bgr):
        H, W = img_bgr.shape[:2]
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        rects = []
        for y0, y1 in tile_ranges(H, W):
            for r in self._detect_once(np.ascontiguousarray(rgb[y0:y1])):
                rects.append([r[0], r[1] + y0, r[2], r[3] + y0])
        out = []
        for x0, y0, x1, y1 in rects:
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(W, x1), min(H, y1)
            if x1 - x0 >= 4 and y1 - y0 >= 4:
                out.append([x0, y0, x1, y1])
        return dedupe_rects(out)

    # ---------- nhận dạng ----------
    @staticmethod
    def _line_crop(gray, r, vertical):
        x0, y0, x1, y1 = r
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        if vertical and crop.shape[0] > 1.3 * crop.shape[1]:
            crop = vertical_to_horizontal(crop)
        # chuẩn hoá chiều cao 64px (đúng cỡ đầu vào của EasyOCR) để ghép lô
        h, w = crop.shape[:2]
        if h != 64:
            nw = max(8, int(round(w * 64 / max(1, h))))
            crop = cv2.resize(crop, (nw, 64), interpolation=cv2.INTER_AREA if h > 64 else cv2.INTER_CUBIC)
        return cv2.copyMakeBorder(crop, 6, 6, 6, 6, cv2.BORDER_REPLICATE)

    def recognize_lines_zh(self, gray, items):
        """Nhận dạng TẤT CẢ dòng chữ của 1 trang trong 1 lần gọi (ghép dọc thành 1 ảnh,
        EasyOCR xử lý theo lô trên GPU) thay vì gọi từng dòng."""
        crops = [self._line_crop(gray, r, v) for r, v in items]
        texts = [""] * len(items)
        valid = [(i, c) for i, c in enumerate(crops) if c is not None]
        if not valid:
            return texts
        gap = 8
        W = max(c.shape[1] for _, c in valid)
        Htot = sum(c.shape[0] + gap for _, c in valid)
        canvas = np.full((Htot, W), 255, np.uint8)
        boxes, starts, y = [], [], 0
        for i, c in valid:
            h, w = c.shape[:2]
            canvas[y:y + h, :w] = c
            boxes.append([0, w, y, y + h])
            starts.append((y, y + h, i))
            y += h + gap
        res = self.reader.recognize(canvas, horizontal_list=boxes, free_list=[], detail=1,
                                    batch_size=32 if self.use_gpu else 4, paragraph=False)
        for box, text, _conf in res:
            cy = (box[0][1] + box[2][1]) / 2
            for y0, y1, i in starts:
                if y0 - 2 <= cy <= y1 + 2:
                    texts[i] += (" " + text) if (self.lang == "en" and texts[i]) else text
                    break
        return texts

    def recognize_blocks_ja(self, img_bgr, blocks):
        """manga-ocr theo lô (GPU fp16), lỗi thì quay về từng khung."""
        from PIL import Image

        H, W = img_bgr.shape[:2]
        ims = []
        for b in blocks:
            p = max(3, b.char_size() // 5)
            crop = img_bgr[max(0, b.y0 - p):min(H, b.y1 + p), max(0, b.x0 - p):min(W, b.x1 + p)]
            ims.append(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)).convert("L").convert("RGB"))
        if not ims:
            return []
        try:
            return self._mocr_batch(ims)
        except Exception as e:  # noqa: BLE001
            self.log(f"  (manga-ocr lô lỗi: {e} – chạy từng khung)")
            return [self.mocr(im) for im in ims]

    def _mocr_batch(self, ims, bs: int = 16):
        import contextlib

        import torch

        try:
            from manga_ocr.ocr import post_process
        except Exception:  # noqa: BLE001
            def post_process(t):
                return "".join(t.split())
        m = self.mocr
        dev = m.model.device
        out = []
        for k in range(0, len(ims), bs):
            x = torch.stack([m._preprocess(im) for im in ims[k:k + bs]]).to(dev)
            amp = torch.autocast("cuda", dtype=torch.float16) if dev.type == "cuda" else contextlib.nullcontext()
            with torch.inference_mode(), amp:
                gen = m.model.generate(x, max_length=300)
            for g in gen.cpu():
                out.append(post_process(m.tokenizer.decode(g, skip_special_tokens=True)))
        return out

    def process(self, img_bgr):
        """Trả về danh sách TextBlock (đã có .text) theo thứ tự đọc."""
        H, W = img_bgr.shape[:2]
        rects = self.detect(img_bgr)
        if not rects:
            return []
        vert = False if self.lang == "en" else None  # chữ Anh luôn ngang
        blocks = [TextBlock.from_lines([rects[i] for i in g], vertical=vert) for g in group_rects(rects)]
        try:
            if self.mocr is not None:
                for b, t in zip(blocks, self.recognize_blocks_ja(img_bgr, blocks)):
                    b.text = t
            else:
                gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
                items, owner = [], []
                for bi, b in enumerate(blocks):
                    for r in b.lines:
                        items.append((r, b.vertical))
                        owner.append(bi)
                for bi, t in zip(owner, self.recognize_lines_zh(gray, items)):
                    if self.lang == "en" and blocks[bi].text:
                        blocks[bi].text += " " + t
                    else:
                        blocks[bi].text += t
        except Exception as e:  # noqa: BLE001
            self.log(f"  ! Lỗi nhận dạng: {e}")
            return []
        out = []
        for b in blocks:
            b.text = clean_text(b.text, self.lang)
            if is_valid_text(b.text, self.lang):  # bỏ nhiễu / chữ Latin / chỉ có dấu câu
                out.append(b)
        # thứ tự đọc: chia trang thành các dải ngang; manga Nhật đọc phải → trái
        band = max(1, min(H // 10, int(1.5 * W) // 6))
        rtl = self.lang == "ja"
        out.sort(key=lambda b: (b.y0 // band, -b.x1 if rtl else b.x0))
        return out
