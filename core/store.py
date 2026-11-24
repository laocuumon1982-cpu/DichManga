"""Lưu trữ:
- config.json : cài đặt nhỏ (sửa tay được) – thay cho registry (QSettings) của bản cũ, tự nhập 1 lần.
- data.db     : SQLite cho dữ liệu lớn dần – bảng thuật ngữ (tên riêng, xưng hô...).
Cả hai nằm cạnh app (bản portable: cạnh DichTruyenTranh.exe) nên mang đi máy khác vẫn còn.
"""
import csv
import json
import re
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from .paths import DATA_DIR

CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "data.db"
CJK_KANA_HANGUL = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]")


# =====================================================================
#  config.json
# =====================================================================
class JsonSettings:
    """Giống QSettings (value / setValue) nhưng ghi ra config.json dễ đọc, dễ sửa tay."""

    def __init__(self, path: Path = CONFIG_PATH, legacy=None):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.data = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001  file hỏng -> giữ bản sao, dùng mặc định
                bad = self.path.with_suffix(f".hong_{int(time.time())}.json")
                shutil.copy2(self.path, bad)
                self.data = {}
        elif legacy is not None:
            self._import_legacy(legacy)

    def _import_legacy(self, qs):
        """Nhập cài đặt cũ từ QSettings (registry) – chỉ chạy 1 lần khi chưa có config.json."""
        try:
            keys = qs.allKeys()
        except Exception:  # noqa: BLE001
            keys = []
        for k in keys:
            v = qs.value(k)
            if isinstance(v, str) and v in ("true", "false"):
                v = v == "true"
            self.data[k] = v
        if self.data:
            self.data["_imported_from_registry"] = time.strftime("%Y-%m-%d %H:%M")
            self.save()

    def value(self, key, default=None):
        return self.data.get(key, default)

    def get_bool(self, key, default=False) -> bool:
        v = self.data.get(key, default)
        return v == "true" if isinstance(v, str) else bool(v)

    def get_int(self, key, default=0) -> int:
        try:
            return int(self.data.get(key, default))
        except (TypeError, ValueError):
            return default

    def setValue(self, key, v):  # noqa: N802  (giữ tên giống QSettings)
        self.data[key] = v

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)


# =====================================================================
#  data.db – bảng thuật ngữ
# =====================================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS glossary (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    src      TEXT NOT NULL,            -- chữ gốc (Trung/Nhật/Anh) hoặc chữ Việt cần sửa
    dst      TEXT NOT NULL,            -- bản dịch / chữ Việt đúng
    note     TEXT NOT NULL DEFAULT '', -- ghi chú: giới tính, xưng hô, vai vế...
    lang     TEXT NOT NULL DEFAULT '', -- '' = mọi ngôn ngữ
    enabled  INTEGER NOT NULL DEFAULT 1,
    updated  TEXT NOT NULL DEFAULT '',
    UNIQUE(src, lang)
);
"""


class Glossary:
    """Bảng thuật ngữ dùng chung cho mọi truyện.
    - Dòng có chữ gốc Trung/Nhật/Hàn/Anh: gửi cho AI (LLM) để dịch đúng tên riêng, xưng hô;
      với GTX thì thay sẵn tên riêng trước khi gửi.
    - Dòng mà chữ gốc là tiếng Việt: 'sửa sau dịch' – tự thay trong mọi bản dịch (mọi bộ dịch)."""

    def __init__(self, path: Path = DB_PATH):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # ---------- đọc / ghi ----------
    def all(self, lang=None):
        q = "SELECT * FROM glossary"
        args = ()
        if lang:
            q += " WHERE lang IN ('', ?)"
            args = (lang,)
        with self._conn() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY src COLLATE NOCASE", args)]

    def upsert(self, src, dst, note="", lang="", enabled=True, row_id=None):
        src, dst = (src or "").strip(), (dst or "").strip()
        if not src or not dst:
            return
        now = time.strftime("%Y-%m-%d %H:%M")
        with self.lock, self._conn() as c:
            if row_id:
                c.execute("UPDATE glossary SET src=?, dst=?, note=?, lang=?, enabled=?, updated=? WHERE id=?",
                          (src, dst, note or "", lang or "", int(bool(enabled)), now, row_id))
            else:
                c.execute("INSERT INTO glossary(src, dst, note, lang, enabled, updated) VALUES(?,?,?,?,?,?) "
                          "ON CONFLICT(src, lang) DO UPDATE SET dst=excluded.dst, note=excluded.note, "
                          "enabled=excluded.enabled, updated=excluded.updated",
                          (src, dst, note or "", lang or "", int(bool(enabled)), now))

    def delete(self, row_id):
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM glossary WHERE id=?", (row_id,))

    def import_csv(self, path) -> int:
        """CSV/TSV: cột src, dst, note (tuỳ chọn), lang (tuỳ chọn). Dòng đầu là tiêu đề thì bỏ qua."""
        raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        dialect = csv.excel_tab if raw.count("\t") > raw.count(",") else csv.excel
        n = 0
        for i, row in enumerate(csv.reader(raw.splitlines(), dialect)):
            if len(row) < 2:
                continue
            if i == 0 and row[0].strip().lower() in ("src", "goc", "gốc", "nguyen van", "nguyên văn"):
                continue
            self.upsert(row[0], row[1], row[2] if len(row) > 2 else "", row[3] if len(row) > 3 else "")
            n += 1
        return n

    def export_csv(self, path) -> int:
        rows = self.all()
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["src", "dst", "note", "lang"])
            for r in rows:
                w.writerow([r["src"], r["dst"], r["note"], r["lang"]])
        return len(rows)

    # ---------- dùng khi dịch ----------
    def terms_for(self, lang, texts=None):
        """Thuật ngữ gốc (Trung/Nhật/Anh) đang bật; texts: chỉ lấy thuật ngữ có xuất hiện trong chương."""
        joined = "\n".join(texts or [])
        out = []
        for r in self.all(lang):
            if not r["enabled"] or not self.is_source_term(r["src"], lang):
                continue
            if texts is None or r["src"] in joined or r["src"].lower() in joined.lower():
                out.append(r)
        return out

    @staticmethod
    def is_source_term(src: str, lang: str) -> bool:
        if CJK_KANA_HANGUL.search(src):
            return True
        return lang == "en" and not re.search(r"[À-ỹđĐ]", src)  # tiếng Anh: chữ Latin không dấu

    def post_rules(self, lang=None):
        """Các dòng 'sửa sau dịch' (chữ gốc là tiếng Việt)."""
        return [(r["src"], r["dst"]) for r in self.all(lang)
                if r["enabled"] and not self.is_source_term(r["src"], lang or "")]

    def apply_post(self, texts, lang=None):
        rules = self.post_rules(lang)
        if not rules:
            return list(texts)
        out = []
        for t in texts:
            for a, b in rules:
                if a and t:
                    t = re.sub(rf"(?<![\wÀ-ỹ]){re.escape(a)}(?![\wÀ-ỹ])", b, t)
            out.append(t)
        return out

    def apply_pre(self, texts, lang):
        """Cho GTX: thay sẵn tên riêng gốc bằng tên tiếng Việt trước khi gửi (dài trước, ngắn sau)."""
        terms = sorted(self.terms_for(lang, texts), key=lambda r: -len(r["src"]))
        if not terms:
            return list(texts)
        out = []
        for t in texts:
            for r in terms:
                t = t.replace(r["src"], f" {r['dst']} ") if CJK_KANA_HANGUL.search(r["src"]) else \
                    re.sub(rf"\b{re.escape(r['src'])}\b", r["dst"], t)
            out.append(" ".join(t.split()))
        return out
