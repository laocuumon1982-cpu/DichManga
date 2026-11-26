"""Tự kết nối Ollama trên máy: tìm / mở Ollama, liệt kê model đã cài, chọn model hợp nhất,
tải model mới (có % tiến độ). Dùng API gốc của Ollama (/api/...)."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

DEFAULT_URL = "http://localhost:11434/v1"
# gợi ý cho card 12 GB (RTX 3060): (tên model, dung lượng, mô tả)
RECOMMENDED = [
    ("qwen2.5:14b", "9 GB", "dịch Trung/Nhật tốt nhất cho card 12 GB"),
    ("qwen2.5:7b", "4.7 GB", "nhanh gấp đôi, dịch hơi kém hơn"),
    ("qwen3:14b", "9.3 GB", "đời mới, có chế độ suy nghĩ (chậm hơn)"),
]
# thứ tự ưu tiên khi tự chọn model đã cài (dịch Trung/Nhật -> Việt)
PREFER = [r"qwen2\.5:14b", r"qwen3:14b", r"qwen2\.5:7b", r"qwen3:8b", r"qwen2\.5", r"qwen3", r"qwen",
          r"gemma3", r"gemma2", r"llama3", r"mistral"]
SKIP = re.compile(r"embed|bge|minilm|nomic|clip|whisper|vision|-vl|llava|moondream", re.I)


def root_url(url: str) -> str:
    """http://localhost:11434/v1 -> http://localhost:11434"""
    u = urlsplit((url or DEFAULT_URL).strip())
    path = re.sub(r"/v1/?$|/v1/chat/completions/?$|/api/?.*$", "", u.path.rstrip("/"))
    return urlunsplit((u.scheme or "http", u.netloc or "localhost:11434", path, "", "")).rstrip("/")


def version(url: str, timeout: float = 2.5):
    """Phiên bản Ollama nếu đang chạy, None nếu không kết nối được."""
    try:
        r = requests.get(root_url(url) + "/api/version", timeout=timeout)
        r.raise_for_status()
        return r.json().get("version", "?")
    except Exception:  # noqa: BLE001
        return None


def installed(url: str):
    """[(tên, dung lượng GB)] model đã tải về Ollama (bỏ model nhúng / ảnh)."""
    r = requests.get(root_url(url) + "/api/tags", timeout=10)
    r.raise_for_status()
    out = []
    for m in r.json().get("models", []):
        name = m.get("name") or m.get("model") or ""
        if name and not SKIP.search(name):
            out.append((name, round((m.get("size") or 0) / 1024 ** 3, 1)))
    return out


def pick_best(names, current: str = ""):
    """Giữ model đang chọn nếu đã cài, không thì chọn model hợp dịch nhất."""
    if not names:
        return ""
    norm = {n: n.replace(":latest", "") for n in names}
    cur = (current or "").replace(":latest", "")
    for n, short in norm.items():
        if cur and (short == cur or n == current):
            return n
    for pat in PREFER:
        for n in names:
            if re.search(pat, n, re.I):
                return n
    return names[0]


def find_exe():
    """Đường dẫn ollama.exe / 'ollama app.exe' trên Windows (hoặc 'ollama' trên PATH)."""
    exe = shutil.which("ollama")
    if exe:
        return exe
    cands = []
    for env in ("LOCALAPPDATA", "ProgramFiles", "ProgramW6432"):
        base = os.environ.get(env)
        if base:
            cands += [Path(base) / "Programs" / "Ollama" / "ollama.exe", Path(base) / "Ollama" / "ollama.exe"]
    for c in cands:
        if c.is_file():
            return str(c)
    return None


def start_server(url: str, log=print, wait: float = 20):
    """Ollama chưa chạy thì tự mở 'ollama serve' (ẩn cửa sổ) và chờ sẵn sàng. Trả về phiên bản hoặc None."""
    v = version(url)
    if v:
        return v
    exe = find_exe()
    if not exe:
        return None
    log("Đang mở Ollama...")
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    except OSError:
        return None
    t0 = time.time()
    while time.time() - t0 < wait:
        v = version(url, timeout=1.5)
        if v:
            return v
        time.sleep(0.7)
    return None


def _has_model(url: str, model: str) -> bool:
    try:
        want = model.replace(":latest", "")
        return any(n.replace(":latest", "") == want for n, _ in installed(url))
    except Exception:  # noqa: BLE001
        return False


def _pull_api(url, model, progress, stop_event):
    """Tải qua API /api/pull (gửi cả 'model' lẫn 'name' cho Ollama bản cũ)."""
    with requests.post(root_url(url) + "/api/pull", json={"model": model, "name": model, "stream": True},
                       stream=True, timeout=(10, 900)) as r:
        if r.status_code >= 400:
            raise RuntimeError(f"Ollama trả lỗi {r.status_code}: {r.text[:200]}")
        ok = False
        for line in r.iter_lines():
            if stop_event is not None and stop_event.is_set():
                raise RuntimeError("Đã huỷ tải model")
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("error"):
                raise RuntimeError(d["error"])
            st = d.get("status", "")
            if st == "success":
                ok = True
            total, done = d.get("total") or 0, d.get("completed") or 0
            if progress:
                if total:
                    progress(100.0 * done / total, f"{st}: {done / 1024 ** 3:.1f}/{total / 1024 ** 3:.1f} GB")
                else:
                    progress(None, st)
        if not ok:
            raise RuntimeError("kết nối bị ngắt giữa chừng")


_PCT = re.compile(r"(\d{1,3})%")
_SIZE = re.compile(r"([\d.]+\s*[KMGT]?B)\s*/\s*([\d.]+\s*[KMGT]?B)")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _pull_cli(model, progress, stop_event):
    """Dự phòng: chạy lệnh 'ollama pull <model>' (cách tải chuẩn của Ollama), đọc % từ màn hình lệnh."""
    exe = find_exe()
    if not exe:
        raise RuntimeError("không tìm thấy ollama.exe")
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    proc = subprocess.Popen([exe, "pull", model], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=flags)
    buf, tail = b"", ""
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                proc.kill()
                raise RuntimeError("Đã huỷ tải model")
            ch = proc.stdout.read(1)
            if not ch:
                break
            if ch in (b"\r", b"\n"):
                txt = _ANSI.sub("", buf.decode("utf-8", "replace")).strip()
                buf = b""
                if not txt:
                    continue
                tail = txt
                if progress:
                    m, sz = _PCT.search(txt), _SIZE.search(txt)
                    label = txt.split(":")[0][:40] + (f": {sz.group(1)}/{sz.group(2)}" if sz else "")
                    progress(float(m.group(1)) if m else None, label)
            else:
                buf += ch
    finally:
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(tail or f"ollama pull thoát với mã {rc}")


def pull(url: str, model: str, progress=None, stop_event=None, log=print):
    """Tải model về Ollama. progress(phần trăm 0–100 hoặc None, mô tả).
    Thử API trước; lỗi thì chạy lệnh 'ollama pull'. Cuối cùng kiểm tra model đã có thật chưa."""
    errors = []
    try:
        _pull_api(url, model, progress, stop_event)
    except Exception as e:  # noqa: BLE001
        if stop_event is not None and stop_event.is_set():
            raise
        errors.append(f"API: {e}")
        log(f"Tải qua API lỗi ({e}) – thử lệnh 'ollama pull'...")
        try:
            _pull_cli(model, progress, stop_event)
        except Exception as e2:  # noqa: BLE001
            if stop_event is not None and stop_event.is_set():
                raise
            errors.append(f"lệnh ollama pull: {e2}")
    if not _has_model(url, model):
        raise RuntimeError(" | ".join(errors) or "tải xong nhưng Ollama chưa thấy model – mở lại Ollama rồi bấm ⟳")


def auto_connect(url: str, current_model: str = "", log=print):
    """Tự kết nối: mở Ollama nếu cần, liệt kê model, chọn model hợp nhất.
    Trả về dict: ok, version, models [(tên, GB)], model (đã chọn), message."""
    v = start_server(url, log)
    if not v:
        exe = find_exe()
        msg = ("Không mở được Ollama – hãy mở Ollama từ menu Start rồi bấm lại" if exe else
               "Chưa thấy Ollama trên máy – tải tại ollama.com rồi cài đặt")
        return {"ok": False, "version": None, "models": [], "model": "", "message": msg}
    models = installed(url)
    names = [n for n, _ in models]
    model = pick_best(names, current_model)
    if not names:
        msg = f"Đã kết nối Ollama {v} nhưng chưa có model nào – bấm ⬇ Tải model"
    elif current_model and model != current_model and current_model.replace(":latest", "") not in \
            [n.replace(":latest", "") for n in names]:
        msg = f"Đã kết nối Ollama {v} – chưa có '{current_model}', tự chọn {model} ({len(names)} model đã cài)"
    else:
        msg = f"Đã kết nối Ollama {v} – dùng {model} ({len(names)} model đã cài)"
    return {"ok": True, "version": v, "models": models, "model": model, "message": msg}
