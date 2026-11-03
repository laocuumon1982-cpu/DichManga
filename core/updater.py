"""Cập nhật app từ GitHub Releases.

- Kiểm tra bản mới: API releases/latest của repo GITHUB_REPO.
- Cập nhật nhanh: tải gói `DichTruyenTranh_app_update.zip` (chỉ chứa code app, vài trăm KB),
  sao lưu file cũ vào app/_backup/<phiên bản>/ rồi chép đè, cài thêm thư viện nếu
  requirements.txt thay đổi, sau đó khởi động lại app.
- Bản cập nhật lớn (đổi Python / PyTorch) thì mở trang Releases để tải bản portable mới.
"""
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from . import APP_VERSION, GITHUB_REPO
from .paths import APP_DIR, IS_PORTABLE

API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
UPDATE_ASSET = "DichTruyenTranh_app_update.zip"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "DichTruyenTranh-Updater"}
# những gì gói cập nhật được phép ghi đè trong thư mục app
ALLOWED_TOP = {"main.py", "prefetch_models.py", "requirements.txt", "icon.ico", "README.md",
               "core", "ui", "fonts", "tools", "version.txt"}


def parse_version(v: str):
    nums = [int(x) for x in re.findall(r"\d+", v or "")][:4]
    return tuple(nums + [0] * (4 - len(nums)))


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def check_latest(timeout: float = 10.0) -> dict:
    """Trả về thông tin bản phát hành mới nhất. Ném lỗi nếu không kết nối được."""
    r = requests.get(API_LATEST, headers=HEADERS, timeout=timeout)
    if r.status_code == 404:
        return {"version": "", "newer": False, "notes": "", "url": RELEASES_URL, "assets": {}}
    r.raise_for_status()
    d = r.json()
    tag = d.get("tag_name") or d.get("name") or ""
    assets = {a["name"]: {"url": a["browser_download_url"], "size": a.get("size", 0)}
              for a in d.get("assets", [])}
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "newer": is_newer(tag),
        "notes": d.get("body") or "",
        "url": d.get("html_url") or RELEASES_URL,
        "published": (d.get("published_at") or "")[:10],
        "assets": assets,
        "app_update": assets.get(UPDATE_ASSET),
    }


def download(url: str, dest: Path, progress=None, stop_event=None) -> Path:
    """Tải file, progress(đã tải, tổng) – tổng = 0 nếu server không báo."""
    dest = Path(dest)
    with requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError("Đã huỷ tải")
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    return dest


def _python_console_exe() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        cand = exe.with_name("python.exe")
        if cand.exists():
            return str(cand)
    return str(exe)


def _torch_constraints(tmpdir: Path):
    """Khoá phiên bản torch đang dùng để pip không thay bằng bản khác (mất GPU)."""
    lines = []
    try:
        from importlib.metadata import version

        for pkg in ("torch", "torchvision"):
            try:
                lines.append(f"{pkg}=={version(pkg)}")
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    if not lines:
        return None
    p = tmpdir / "constraints.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def apply_update(zip_path: Path, log=print) -> bool:
    """Chép đè code app từ gói zip. Trả về True nếu cần cài thêm thư viện."""
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        # gói có thể bọc trong 1 thư mục gốc -> bỏ thư mục đó
        prefix = ""
        if "main.py" not in names:
            cands = [n[:-len("main.py")] for n in names if n.endswith("/main.py") and n.count("/") == 1]
            if not cands:
                raise RuntimeError("Gói cập nhật không hợp lệ (không có main.py).")
            prefix = cands[0]
        if prefix + "core/__init__.py" not in names:
            raise RuntimeError("Gói cập nhật không hợp lệ (thiếu core/).")
        tmp = Path(tempfile.mkdtemp(prefix="dtt_update_"))
        files = []
        for n in names:
            rel = n[len(prefix):]
            if not rel or rel.split("/")[0] not in ALLOWED_TOP or ".." in rel.split("/"):
                continue
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            files.append(rel)
    old_req = (APP_DIR / "requirements.txt").read_text(encoding="utf-8", errors="ignore") \
        if (APP_DIR / "requirements.txt").exists() else ""
    new_req = (tmp / "requirements.txt").read_text(encoding="utf-8", errors="ignore") \
        if (tmp / "requirements.txt").exists() else old_req

    backup = APP_DIR / "_backup" / f"v{APP_VERSION}"
    log(f"Sao lưu bản hiện tại vào {backup}")
    for rel in files:
        src = APP_DIR / rel
        if src.exists():
            dst = backup / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    log(f"Chép {len(files)} file mới...")
    for rel in files:
        dst = APP_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp / rel, dst)
    shutil.rmtree(tmp, ignore_errors=True)
    return new_req.strip() != old_req.strip()


def install_requirements(log=print) -> bool:
    """Cài thư viện mới theo requirements.txt (giữ nguyên PyTorch)."""
    req = APP_DIR / "requirements.txt"
    if not req.exists():
        return True
    tmp = Path(tempfile.mkdtemp(prefix="dtt_pip_"))
    cmd = [_python_console_exe(), "-m", "pip", "install", "--no-warn-script-location", "-r", str(req)]
    c = _torch_constraints(tmp)
    if c:
        cmd += ["-c", str(c)]
    if IS_PORTABLE:
        cmd.append("--no-build-isolation")
    log("Cài thư viện: " + " ".join(cmd[2:]))
    flags = 0x08000000 if sys.platform == "win32" else 0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", creationflags=flags)
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log(line)
    proc.wait()
    shutil.rmtree(tmp, ignore_errors=True)
    return proc.returncode == 0


def restart_app() -> None:
    """Mở lại app (cùng trình Python) – app hiện tại tự thoát sau đó."""
    flags = 0x00000008 if sys.platform == "win32" else 0  # DETACHED_PROCESS
    subprocess.Popen([sys.executable, str(APP_DIR / "main.py")], cwd=str(APP_DIR), creationflags=flags,
                     close_fds=True)
