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


# =====================================================================
#  data.db – xưng hô giữa các nhân vật (cho AI dịch đúng vai vế)
# =====================================================================
PRONOUN_SCHEMA = """
CREATE TABLE IF NOT EXISTS pronouns (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    a         TEXT NOT NULL,             -- nhân vật A (tên gốc hoặc tên Việt)
    b         TEXT NOT NULL,             -- nhân vật B
    a_self    TEXT NOT NULL DEFAULT '',  -- A tự xưng
    a_calls_b TEXT NOT NULL DEFAULT '',  -- A gọi B là
    b_self    TEXT NOT NULL DEFAULT '',  -- B tự xưng
    b_calls_a TEXT NOT NULL DEFAULT '',  -- B gọi A là
    note      TEXT NOT NULL DEFAULT '',
    enabled   INTEGER NOT NULL DEFAULT 1,
    updated   TEXT NOT NULL DEFAULT '',
    UNIQUE(a, b)
);
"""
# mẫu xưng hô hay gặp: (tên mẫu, A xưng, A gọi B, B xưng, B gọi A)
PRONOUN_PRESETS = [
    ("Anh – Em", "anh", "em", "em", "anh"),
    ("Chị – Em", "chị", "em", "em", "chị"),
    ("Tớ – Cậu (bạn bè)", "tớ", "cậu", "tớ", "cậu"),
    ("Tao – Mày (thân / gây gổ)", "tao", "mày", "tao", "mày"),
    ("Tôi – Anh (lịch sự)", "tôi", "anh", "tôi", "anh"),
    ("Ta – Ngươi (cổ trang)", "ta", "ngươi", "ta", "ngươi"),
    ("Huynh – Muội", "huynh", "muội", "muội", "huynh"),
    ("Sư phụ – Đồ nhi", "vi sư", "đồ nhi", "đồ nhi", "sư phụ"),
    ("Bố – Con", "bố", "con", "con", "bố"),
    ("Mẹ – Con", "mẹ", "con", "con", "mẹ"),
    ("Bổn vương – Thần", "bổn vương", "ngươi", "thần", "điện hạ"),
    ("Thầy/Cô – Em (học đường)", "thầy", "em", "em", "thầy"),
]


class Pronouns:
    """Bảng xưng hô A ↔ B dùng chung cho mọi truyện (bật/tắt từng cặp)."""

    def __init__(self, path: Path = DB_PATH):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(PRONOUN_SCHEMA)

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def all(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM pronouns ORDER BY a COLLATE NOCASE, b")]

    def upsert(self, a, b, a_self="", a_calls_b="", b_self="", b_calls_a="", note="", enabled=True, row_id=None):
        a, b = (a or "").strip(), (b or "").strip()
        if not a or not b:
            return
        vals = [(v or "").strip() for v in (a_self, a_calls_b, b_self, b_calls_a, note)]
        now = time.strftime("%Y-%m-%d %H:%M")
        with self.lock, self._conn() as c:
            if row_id:
                c.execute("UPDATE pronouns SET a=?, b=?, a_self=?, a_calls_b=?, b_self=?, b_calls_a=?, note=?, "
                          "enabled=?, updated=? WHERE id=?", (a, b, *vals, int(bool(enabled)), now, row_id))
            else:
                c.execute("INSERT INTO pronouns(a, b, a_self, a_calls_b, b_self, b_calls_a, note, enabled, updated) "
                          "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(a, b) DO UPDATE SET a_self=excluded.a_self, "
                          "a_calls_b=excluded.a_calls_b, b_self=excluded.b_self, b_calls_a=excluded.b_calls_a, "
                          "note=excluded.note, enabled=excluded.enabled, updated=excluded.updated",
                          (a, b, *vals, int(bool(enabled)), now))

    def delete(self, row_id):
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM pronouns WHERE id=?", (row_id,))

    @staticmethod
    def describe(r) -> str:
        """1 dòng mô tả cho AI: 'A ↔ B: A xưng "ta", gọi B là "ngươi"; B xưng ..., gọi A là ...'."""
        a, b = r["a"], r["b"]
        parts = []
        sa = ", ".join(x for x in ((f'xưng "{r["a_self"]}"' if r.get("a_self") else ""),
                                   (f'gọi {b} là "{r["a_calls_b"]}"' if r.get("a_calls_b") else "")) if x)
        sb = ", ".join(x for x in ((f'xưng "{r["b_self"]}"' if r.get("b_self") else ""),
                                   (f'gọi {a} là "{r["b_calls_a"]}"' if r.get("b_calls_a") else "")) if x)
        if sa:
            parts.append(f"{a} {sa}")
        if sb:
            parts.append(f"{b} {sb}")
        line = f"- {a} ↔ {b}: " + "; ".join(parts) if parts else f"- {a} ↔ {b}"
        return line + (f" ({r['note']})" if r.get("note") else "")

    def prompt_text(self, texts=None) -> str:
        """Khối XƯNG HÔ cho AI. texts: chỉ lấy cặp có tên xuất hiện (nếu tên viết bằng chữ gốc);
        cặp ghi bằng tên Việt luôn được gửi."""
        joined = "\n".join(texts or [])
        lines = []
        for r in self.all():
            if not r["enabled"]:
                continue
            if texts is not None:
                names_src = [n for n in (r["a"], r["b"]) if CJK_KANA_HANGUL.search(n)]
                if names_src and not all(n in joined for n in names_src):
                    continue
            lines.append(self.describe(r))
        return "\n".join(lines)
