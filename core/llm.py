"""Dịch cả chương bằng AI (LLM) theo ngữ cảnh.

Gom chữ của mọi trang trong chương -> gửi một lượt (chia phần nếu dài) kèm bảng thuật ngữ,
văn phong, ghi chú truyện và các câu đã dịch trước đó để cả chương thống nhất tên riêng,
xưng hô. Model trả về JSON [{"id":..,"vi":..}]. Câu AI bỏ sót -> GTX dịch bù.

Nhà cung cấp:
- Chạy trên máy (miễn phí, không cần mạng): Ollama, LM Studio (API kiểu OpenAI).
- Online (cần API key của bạn): DeepSeek, OpenAI, Gemini, Claude, hoặc máy chủ tuỳ chỉnh kiểu OpenAI.
"""
import json
import re
import time
from urllib.parse import urlsplit, urlunsplit

import requests

LANG_VI = {"zh": "tiếng Trung", "zh_tw": "tiếng Trung (phồn thể)", "ja": "tiếng Nhật", "en": "tiếng Anh"}
KIND_HINT = {"thought": "suy nghĩ", "shout": "hét", "narration": "dẫn truyện", "sfx": "tượng thanh", "free": "chữ trên hình"}

# id: (tên hiển thị, URL mặc định, model mặc định, cần API key?, kiểu API)
PROVIDERS = {
    "ollama":   ("Ollama – chạy trên máy", "http://localhost:11434/v1", "qwen2.5:14b", False, "ollama"),
    "lmstudio": ("LM Studio – chạy trên máy", "http://localhost:1234/v1", "", False, "openai"),
    "deepseek": ("DeepSeek (API key)", "https://api.deepseek.com", "deepseek-chat", True, "openai"),
    "gemini":   ("Google Gemini (API key)", "https://generativelanguage.googleapis.com/v1beta/openai",
                 "gemini-2.5-flash", True, "openai"),
    "openai":   ("OpenAI (API key)", "https://api.openai.com/v1", "gpt-4o-mini", True, "openai"),
    "claude":   ("Anthropic Claude (API key)", "https://api.anthropic.com", "claude-sonnet-5-5", True, "anthropic"),
    "custom":   ("Máy chủ khác (kiểu OpenAI)", "http://localhost:8000/v1", "", False, "openai"),
}
LOCAL_PROVIDERS = {"ollama", "lmstudio", "custom"}


def _chat_url(base: str) -> str:
    u = urlsplit(base.strip())
    path = u.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    return urlunsplit((u.scheme, u.netloc, path, u.query, ""))


def _models_url(base: str) -> str:
    u = urlsplit(base.strip())
    path = u.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    return urlunsplit((u.scheme, u.netloc, path + "/models", u.query, ""))


def friendly_error(e) -> str:
    """Lỗi dễ hiểu cho người dùng, không bao giờ để lộ API key."""
    t = str(e)
    t = re.sub(r"(key|token|Bearer)[=: ]+[A-Za-z0-9_\-\.]{8,}", r"\1=***", t, flags=re.I)
    resp = getattr(e, "response", None)
    code = getattr(resp, "status_code", None)
    body = ""
    try:
        body = resp.text[:300] if resp is not None else ""
    except Exception:  # noqa: BLE001
        pass
    if "not found" in body and ("pull" in body or "model" in body):
        try:
            body = str(json.loads(body).get("error", body))  # {"error": "model \"x\" not found..."}
        except (ValueError, AttributeError):
            pass
        m = re.search(r'model ["\']?([^"\'\s]+)["\']?', body)
        name = m.group(1) if m else ""
        return f"Ollama chưa có model {name} – bấm ⬇ Tải model hoặc chọn model đã cài (⟳)"
    if isinstance(e, requests.ConnectionError):
        return "không kết nối được – kiểm tra địa chỉ URL / Ollama hoặc LM Studio đã mở chưa"
    if isinstance(e, requests.Timeout):
        return "hết thời gian chờ (model chạy chậm hoặc mạng chậm)"
    if code in (401, 403):
        return f"API key sai hoặc chưa được cấp quyền ({code})"
    if code == 402:
        return "tài khoản API hết số dư (402)"
    if code == 404:
        return "sai tên model hoặc sai URL (404)"
    if code == 429:
        return "vượt giới hạn gọi (429) – chờ một lát rồi thử lại"
    if code == 400:
        return "yêu cầu bị từ chối (400) – thường do sai tên model"
    return t[:200]


class LLMClient:
    def __init__(self, provider: str, base_url: str = "", model: str = "", api_key: str = "",
                 timeout: float = 600):
        if provider not in PROVIDERS:
            raise ValueError(f"Không biết nhà cung cấp '{provider}'")
        name, def_url, def_model, _need_key, api = PROVIDERS[provider]
        self.provider = provider
        self.api = api
        self.base = (base_url or def_url).strip()
        self.model = (model or def_model).strip()
        self.key = (api_key or "").strip()
        self.timeout = timeout
        self.s = requests.Session()

    def list_models(self):
        """Danh sách model trên máy chủ (Ollama / LM Studio / OpenAI...)."""
        if self.api == "ollama":
            from .ollama import installed

            return [n for n, _ in installed(self.base)]
        if self.api == "anthropic":
            r = self.s.get(self.base.rstrip("/") + "/v1/models", timeout=15,
                           headers={"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        else:
            h = {"Authorization": f"Bearer {self.key}"} if self.key else {}
            r = self.s.get(_models_url(self.base), timeout=15, headers=h)
        r.raise_for_status()
        return sorted(m.get("id", "") for m in r.json().get("data", []) if m.get("id"))

    def chat(self, system: str, user: str) -> str:
        if not self.model:
            raise RuntimeError("Chưa nhập tên model")
        if self.api == "ollama":
            # API gốc của Ollama: đặt được độ dài ngữ cảnh (mặc định Ollama chỉ ~2–4k token, chương dài
            # sẽ bị cắt mất), giữ model trong VRAM 30 phút, tắt chế độ 'suy nghĩ' của Qwen3 cho nhanh
            from .ollama import root_url

            r = self.s.post(root_url(self.base) + "/api/chat", timeout=self.timeout,
                            json={"model": self.model, "stream": False, "keep_alive": "30m", "think": False,
                                  "options": {"temperature": 0.3, "num_ctx": 8192},
                                  "messages": [{"role": "system", "content": system},
                                               {"role": "user", "content": user}]})
            if r.status_code == 400 and "think" in r.text:  # Ollama cũ / model không hỗ trợ 'think'
                r = self.s.post(root_url(self.base) + "/api/chat", timeout=self.timeout,
                                json={"model": self.model, "stream": False, "keep_alive": "30m",
                                      "options": {"temperature": 0.3, "num_ctx": 8192},
                                      "messages": [{"role": "system", "content": system},
                                                   {"role": "user", "content": user}]})
            r.raise_for_status()
            return (r.json().get("message") or {}).get("content", "")
        if self.api == "anthropic":
            r = self.s.post(self.base.rstrip("/") + "/v1/messages", timeout=self.timeout,
                            headers={"x-api-key": self.key, "anthropic-version": "2023-06-01",
                                     "content-type": "application/json"},
                            json={"model": self.model, "max_tokens": 8000, "temperature": 0.3,
                                  "system": system, "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            return "".join(p.get("text", "") for p in r.json().get("content", []))
        h = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        r = self.s.post(_chat_url(self.base), timeout=self.timeout, headers=h,
                        json={"model": self.model, "temperature": 0.3, "stream": False,
                              "messages": [{"role": "system", "content": system},
                                           {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""


# ---------------------------------------------------------------------
#  Prompt + đọc kết quả
# ---------------------------------------------------------------------
def build_prompt(lang, items, terms, style, notes, done_pairs):
    """items: [{"id", "page", "text", "kind"?}]. Trả về (system, user)."""
    system = (
        f"Bạn là dịch giả truyện tranh chuyên nghiệp, dịch {LANG_VI.get(lang, lang)} sang tiếng Việt.\n"
        "Yêu cầu:\n"
        "- Đọc hết các câu để nắm mạch truyện trước khi dịch; giữ thống nhất tên riêng và cách xưng hô "
        "theo BẢNG THUẬT NGỮ và theo các câu đã dịch trước đó.\n"
        "- Câu ngắn gọn, tự nhiên như lời thoại truyện tranh (phải vừa bóng thoại); đúng giọng nhân vật.\n"
        "- Ô loại 'tượng thanh' dịch thành từ tượng thanh tiếng Việt ngắn.\n"
        "- Không giải thích, không thêm chú thích, không bỏ sót câu nào.\n"
        "- Chỉ trả về MỘT mảng JSON dạng [{\"id\": <số>, \"vi\": \"<bản dịch>\"}] đủ mọi id."
    )
    parts = []
    if style:
        parts.append(f"VĂN PHONG: {style}")
    if notes:
        parts.append(f"GHI CHÚ VỀ TRUYỆN: {notes}")
    if terms:
        parts.append("BẢNG THUẬT NGỮ (gốc => dịch):\n" + "\n".join(
            f"- {t['src']} => {t['dst']}" + (f" ({t['note']})" if t.get("note") else "") for t in terms))
    if done_pairs:
        parts.append("CÁC CÂU ĐÃ DỊCH NGAY TRƯỚC ĐÓ (để giữ mạch, KHÔNG dịch lại):\n" + "\n".join(
            f"{a} => {b}" for a, b in done_pairs))
    payload = []
    for it in items:
        o = {"id": it["id"], "trang": it["page"], "goc": it["text"]}
        if it.get("kind") in KIND_HINT:
            o["loai"] = KIND_HINT[it["kind"]]
        payload.append(o)
    parts.append("CÁC CÂU CẦN DỊCH (theo thứ tự đọc):\n" + json.dumps(payload, ensure_ascii=False))
    parts.append("Trả về DUY NHẤT mảng JSON [{\"id\":..., \"vi\":\"...\"}].")
    return system, "\n\n".join(parts)


def parse_reply(txt: str) -> dict:
    """Lấy {id: bản dịch} từ câu trả lời (bỏ khối <think> của Qwen/DeepSeek-R1, khối ```json)."""
    txt = re.sub(r"<think>.*?</think>", "", txt or "", flags=re.S)
    txt = re.sub(r"```(?:json)?", "", txt)
    m = re.search(r"\[.*\]", txt, re.S)
    if not m:
        raise ValueError("AI không trả về mảng JSON")
    raw = m.group(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = json.loads(re.sub(r",\s*([\]}])", r"\1", raw))  # dấu phẩy thừa
    out = {}
    for o in data:
        if isinstance(o, dict) and "id" in o:
            v = o.get("vi", o.get("text", ""))
            try:
                out[int(o["id"])] = str(v).strip()
            except (TypeError, ValueError):
                continue
    return out


def chunks(items, limit):
    out, cur, n = [], [], 0
    for it in items:
        if cur and n + len(it["text"]) > limit:
            out.append(cur)
            cur, n = [], 0
        cur.append(it)
        n += len(it["text"])
    if cur:
        out.append(cur)
    return out


def translate_chapter(client: LLMClient, lang, items, terms=None, style="", notes="",
                      log=print, progress=None, stop_event=None):
    """items: [{"id", "page", "text", "kind"?}] theo thứ tự đọc cả chương.
    Trả về {id: bản dịch} (có thể thiếu id nếu AI lỗi – bên gọi tự dịch bù)."""
    limit = 2200 if client.provider in LOCAL_PROVIDERS else 6000  # model chạy máy: ngữ cảnh ngắn hơn
    parts = chunks(items, limit)
    result = {}
    by_id = {it["id"]: it for it in items}
    for k, part in enumerate(parts):
        if stop_event is not None and stop_event.is_set():
            break
        if progress:
            progress(k, len(parts))
        done = [(by_id[i]["text"], v) for i, v in list(result.items())[-25:]]
        system, user = build_prompt(lang, part, terms or [], style, notes, done)
        want = {it["id"] for it in part}
        for attempt in range(2):
            try:
                t0 = time.time()
                got = parse_reply(client.chat(system, user))
                got = {i: v for i, v in got.items() if i in want and v}
                result.update(got)
                log(f"  AI dịch phần {k + 1}/{len(parts)}: {len(got)}/{len(part)} câu – {time.time() - t0:.1f}s")
                if len(got) >= len(part) or attempt:
                    break
                # thiếu câu -> hỏi lại riêng các câu còn thiếu
                part = [it for it in part if it["id"] not in got]
                system, user = build_prompt(lang, part, terms or [], style, notes, done)
            except Exception as e:  # noqa: BLE001
                log(f"  ! AI lỗi ở phần {k + 1}: {friendly_error(e)}")
                if isinstance(e, (requests.ConnectionError,)) or getattr(
                        getattr(e, "response", None), "status_code", None) in (401, 402, 403, 404):
                    return result  # lỗi cấu hình -> không thử tiếp các phần sau
    if progress:
        progress(len(parts), len(parts))
    return result
