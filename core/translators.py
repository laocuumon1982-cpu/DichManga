"""Bộ dịch:
- GTXTranslator: Google Translate miễn phí (endpoint client=gtx, cần Internet).
- LocalTranslator: model chạy trên máy (HachimiMT cho tiếng Trung, NLLB-200 / Opus-MT
  cho tiếng Nhật). GPU: PyTorch fp16 dịch theo lô. CPU: CTranslate2 INT8 nếu có.
"""
import json
import time
from pathlib import Path
from urllib.parse import quote


class GTXTranslator:
    """Google Translate miễn phí. Gọi bằng urllib (Google hay chặn 'dấu vân tay' của thư viện
    requests bằng lỗi 429). Đường chính: translate_a/single (client=gtx). Bị chặn thì chuyển
    sang đường dự phòng translate_a/t (client=dict-chrome-ex) dịch nhiều câu một lần."""
    URL = "https://translate.googleapis.com/translate_a/single"
    URL_DICT = "https://clients5.google.com/translate_a/t"
    CODES = {"zh": "zh-CN", "zh_tw": "zh-TW", "ja": "ja", "ko": "ko", "en": "en"}
    CHUNK = 1000        # số ký tự tối đa gộp trong 1 lần gọi
    GET_LIMIT = 6000    # URL dài hơn mức này thì dùng POST
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")

    def __init__(self, log=print, delay: float = 0.1):
        self.log = log
        self.delay = delay
        self.cache = {}

    def _open(self, url, params, post_q=None, timeout=20):
        import urllib.parse
        import urllib.request

        q = urllib.parse.urlencode(params, doseq=True)
        if post_q is None:
            req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": self.UA})
        else:
            req = urllib.request.Request(
                f"{url}?{q}", data=urllib.parse.urlencode({"q": post_q}).encode("utf-8"),
                headers={"User-Agent": self.UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _call(self, text: str, sl: str, tl: str = "vi") -> str:
        import urllib.error

        params = {"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "ie": "UTF-8", "oe": "UTF-8"}
        use_post = len(quote(text)) > self.GET_LIMIT
        last = None
        for attempt in range(4):
            try:
                if use_post:
                    data = self._open(self.URL, params, post_q=text)
                else:
                    data = self._open(self.URL, {**params, "q": text})
                if not data or not data[0]:
                    return ""
                return "".join(seg[0] for seg in data[0] if seg and seg[0])
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code == 429:  # gọi quá nhanh -> chờ lâu dần rồi thử lại
                    last = "HTTP 429 – Google tạm chặn vì gọi quá nhanh"
                    time.sleep(4 * (attempt + 1))
                elif e.code in (405, 411, 413) and use_post:
                    use_post = False
                else:
                    time.sleep(1.5 * (attempt + 1))
            except (OSError, ValueError) as e:  # mạng / JSON hỏng
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"GTX lỗi: {last}")

    def _call_dict(self, texts, sl: str, tl: str = "vi"):
        """Đường dự phòng: dịch nhiều câu 1 lần, trả về đúng số câu."""
        params = [("client", "dict-chrome-ex"), ("sl", sl), ("tl", tl)] + [("q", t) for t in texts]
        data = self._open(self.URL_DICT, params)
        out = []
        for x in data:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, list) and x:
                out.append(x[0] if isinstance(x[0], str) else str(x[0]))
            else:
                out.append("")
        if len(out) != len(texts):
            raise ValueError("số câu trả về không khớp")
        return [o.strip() for o in out]

    def translate(self, texts, src_lang: str):
        """Dịch danh sách câu. Câu nào lỗi trả về chuỗi rỗng (không làm hỏng cả trang)."""
        sl = self.CODES.get(src_lang, "auto")
        results = [""] * len(texts)
        todo = []
        for i, t in enumerate(texts):
            t = " ".join((t or "").split())
            if not t:
                continue
            if (sl, t) in self.cache:
                results[i] = self.cache[(sl, t)]
            else:
                todo.append((i, t))

        chunks, cur, cur_len = [], [], 0
        for i, t in todo:
            if cur and cur_len + len(t) > self.CHUNK:
                chunks.append(cur)
                cur, cur_len = [], 0
            cur.append((i, t))
            cur_len += len(t) + 1
        if cur:
            chunks.append(cur)

        def keep(pairs, outs):
            for (i, t), o in zip(pairs, outs):
                results[i] = o
                if o:
                    self.cache[(sl, t)] = o

        for ch in chunks:
            done = False
            if len(ch) > 1:
                try:  # gộp nhiều khung thoại vào 1 lần gọi, mỗi khung 1 dòng
                    out = [o.strip() for o in self._call("\n".join(t for _, t in ch), sl).split("\n")]
                    if len(out) == len(ch) and all(out):
                        keep(ch, out)
                        done = True
                except Exception as e:  # noqa: BLE001
                    self.log(f"  ! {e} – thử đường dự phòng")
            if not done:
                try:  # đường dự phòng: nhiều câu 1 lần, không lo lệch dòng
                    keep(ch, self._call_dict([t for _, t in ch], sl))
                    done = all(results[i] for i, _ in ch)
                except Exception:  # noqa: BLE001
                    pass
            if not done:  # vẫn thiếu -> dịch từng khung
                for i, t in ch:
                    if results[i]:
                        continue
                    try:
                        keep([(i, t)], [self._call(t, sl).strip()])
                    except Exception as e:  # noqa: BLE001
                        self.log(f"  ! Không dịch được '{t[:20]}': {e}")
                    time.sleep(self.delay)
            time.sleep(self.delay)
        return results


# =====================================================================
#  Model dịch chạy local
# =====================================================================
NLLB_CODES = {"zh": "zho_Hans", "zh_tw": "zho_Hant", "ja": "jpn_Jpan", "ko": "kor_Hang"}
# Bản CTranslate2 INT8 dựng sẵn (chạy CPU nhanh gấp nhiều lần PyTorch)
CT2_REPOS = {
    "facebook/nllb-200-distilled-600M": ("JustFrederik/nllb-200-distilled-600M-ct2-int8", ""),
}
CT2_SUBFOLDER = "ct2-int8_float32"  # HachimiMT để bản CT2 trong thư mục con này


class LocalTranslator:
    def __init__(self, model_id: str, device: str, src_lang: str, log=print):
        import torch

        self.torch = torch
        self.model_id = model_id
        self.device = device
        self.src_lang = src_lang
        self.log = log
        self.kind = "nllb" if "nllb" in model_id.lower() else "marian"
        self.backend = None
        self._fp32 = device != "cuda"
        self.t2s = None
        if self.kind == "marian" and src_lang == "zh_tw" and "zh" in model_id.lower():
            try:  # HachimiMT chỉ học giản thể -> chuyển phồn → giản
                from opencc import OpenCC

                self.t2s = OpenCC("t2s")
            except Exception:  # noqa: BLE001
                log("  ! Thiếu opencc, tiếng Trung phồn thể sẽ dịch kém hơn")

        if device == "cpu" and self._try_ct2():
            return
        self._load_hf()

    # ---------- PyTorch (GPU fp16 / CPU) ----------
    def _load_hf(self):
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        dev = self.device
        self.log(f"Đang tải model dịch {self.model_id} lên {dev.upper()} (lần đầu sẽ tải từ Hugging Face)...")
        if self.kind == "nllb":
            self.tok = AutoTokenizer.from_pretrained(self.model_id, src_lang=NLLB_CODES[self.src_lang])
        else:
            self.tok = AutoTokenizer.from_pretrained(self.model_id)
        model = AutoModelForSeq2SeqLM.from_pretrained(self.model_id)
        if dev == "cuda":
            model = model.half()  # fp16: nhanh gấp ~2 lần, tốn nửa VRAM
        self.model = model.to(dev).eval()
        self.backend = "hf"
        self.log(f"  Model dịch: PyTorch {'fp16 GPU' if dev == 'cuda' else 'CPU'}")

    # ---------- CTranslate2 INT8 (CPU) ----------
    def _try_ct2(self) -> bool:
        try:
            import ctranslate2
            from huggingface_hub import snapshot_download
            from transformers import AutoTokenizer
        except Exception:  # noqa: BLE001
            return False
        try:
            if self.model_id in CT2_REPOS:
                repo, sub = CT2_REPOS[self.model_id]
                path = Path(snapshot_download(repo))
                ct2_dir = path / sub if sub else path
                tok_src = self.model_id
            else:
                path = Path(snapshot_download(self.model_id, allow_patterns=[
                    "*.json", "*.spm", "*.model", "*.txt", f"{CT2_SUBFOLDER}/*"]))
                ct2_dir = path / CT2_SUBFOLDER
                tok_src = str(path)
            if not (ct2_dir / "model.bin").exists():
                return False
            self.log(f"Đang tải model dịch {self.model_id} (CTranslate2 INT8, CPU)...")
            if self.kind == "nllb":
                self.tok = AutoTokenizer.from_pretrained(tok_src, src_lang=NLLB_CODES[self.src_lang])
            else:
                self.tok = AutoTokenizer.from_pretrained(tok_src)
            import os

            self.ct2 = ctranslate2.Translator(str(ct2_dir), device="cpu", compute_type="int8",
                                              inter_threads=1, intra_threads=max(1, (os.cpu_count() or 4) - 1))
            self.backend = "ct2"
            self.log("  Model dịch: CTranslate2 INT8 (CPU)")
            return True
        except Exception as e:  # noqa: BLE001
            self.log(f"  (Không dùng được CTranslate2: {e} – chuyển sang PyTorch)")
            return False

    # ---------- dịch ----------
    def _prep(self, t: str) -> str:
        t = " ".join((t or "").split())
        return self.t2s.convert(t) if self.t2s else t

    def translate(self, texts, src_lang=None):
        src = [self._prep(t) for t in texts]
        results = [""] * len(src)
        idx = [i for i, t in enumerate(src) if t]
        if not idx:
            return results
        idx.sort(key=lambda i: len(src[i]))  # gom câu cùng độ dài -> ít padding
        gpu = self.device == "cuda"
        bs = 48 if gpu else 16
        beams = 4 if gpu else 2
        for k in range(0, len(idx), bs):
            part = idx[k:k + bs]
            batch = [src[i] for i in part]
            if self.backend == "ct2":
                out = self._ct2_batch(batch, beams)
            else:
                out = self._hf_batch(batch, beams)
                if gpu and not self._fp32 and not any(o.strip() for o in out):
                    # fp16 cho ra rỗng (tràn số) -> chuyển về fp32 và dịch lại lô này
                    self.log("  (fp16 cho kết quả rỗng – chuyển model dịch sang fp32)")
                    self.model = self.model.float()
                    self._fp32 = True
                    out = self._hf_batch(batch, beams)
            for i, o in zip(part, out):
                results[i] = o.strip()
        return results

    def _hf_batch(self, batch, beams):
        torch = self.torch
        enc = self.tok(batch, return_tensors="pt", padding=True, truncation=True, max_length=256).to(self.device)
        longest = int(enc["input_ids"].shape[1])
        kw = dict(max_new_tokens=min(400, 40 + longest * 3), num_beams=beams, early_stopping=True)
        if self.kind == "nllb":
            kw["forced_bos_token_id"] = self.tok.convert_tokens_to_ids("vie_Latn")
            kw.update(no_repeat_ngram_size=4, repetition_penalty=1.1)
        else:
            kw.update(no_repeat_ngram_size=2, repetition_penalty=1.2)  # theo khuyến nghị HachimiMT
        with torch.inference_mode():
            gen = self.model.generate(**enc, **kw)
        return self.tok.batch_decode(gen, skip_special_tokens=True)

    def _ct2_batch(self, batch, beams):
        tokens = [self.tok.convert_ids_to_tokens(self.tok.encode(t, truncation=True, max_length=256))
                  for t in batch]
        kw = dict(beam_size=beams, max_decoding_length=300, repetition_penalty=1.15,
                  max_batch_size=len(batch))
        if self.kind == "nllb":
            kw["target_prefix"] = [["vie_Latn"]] * len(batch)
            kw["no_repeat_ngram_size"] = 4
        else:
            kw["no_repeat_ngram_size"] = 2
        res = self.ct2.translate_batch(tokens, **kw)
        out = []
        for r in res:
            toks = r.hypotheses[0]
            if self.kind == "nllb" and toks and toks[0] == "vie_Latn":
                toks = toks[1:]
            out.append(self.tok.decode(self.tok.convert_tokens_to_ids(toks), skip_special_tokens=True))
        return out
