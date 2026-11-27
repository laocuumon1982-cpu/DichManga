"""Kịch bản lời thoại & soát lỗi cả chương.

- Xuất kịch bản: .tsv (trang / ô / loại / gốc / dịch) và _kich_ban.txt (chỉ bản dịch, gọn cho người lồng chữ).
- Nhập kịch bản (bản dịch làm sẵn / nhóm dịch sửa) từ .xlsx .tsv .csv .json .txt .md .docx rồi áp vào các ô.
- Tìm & thay thế trong bản dịch cả chương.
- Soát lỗi (QC): chưa dịch, tràn khung, còn chữ gốc, dấu câu, thuật ngữ chưa đúng... + tự sửa lỗi dấu câu.
"""
import csv
import io
import json
import re
import zipfile
from pathlib import Path

from .typeset import KIND_VI

CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯ｦ-ﾟ]")
PAGE_RE = re.compile(r"^\s*(?:=+|#+|\*+)?\s*(?:trang|page|p\.?|tr\.?)\s*(\d+)\b.*$", re.I)
NUM_LINE_RE = re.compile(r"^\s*[\[(]?(\d{1,3})[\]).:\-–]\s*(.*)$")


# =====================================================================
#  Xuất kịch bản
# =====================================================================
def _one_line(t: str) -> str:
    return " ".join((t or "").split())


def export_tsv(project: dict, path) -> int:
    n = 0
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, dialect=csv.excel_tab)
        w.writerow(["Trang", "Ô", "Loại", "Chữ gốc", "Bản dịch"])
        for p in project["pages"]:
            for k, b in enumerate(p["blocks"], 1):
                w.writerow([p["index"] + 1, k, KIND_VI.get(b.get("kind", ""), ""), _one_line(b.get("text")),
                            _one_line(b.get("translation"))])
                n += 1
    return n


def export_script_txt(project: dict, path) -> int:
    """Chỉ bản dịch, đánh số theo ô – nhập lại được (sửa xong nạp vào app)."""
    out, n = [], 0
    for p in project["pages"]:
        out.append(f"## Trang {p['index'] + 1}")
        for k, b in enumerate(p["blocks"], 1):
            mark = " (giữ nguyên)" if b.get("keep") else ""
            out.append(f"{k}. {_one_line(b.get('translation'))}{mark}")
            n += 1
        out.append("")
    Path(path).write_text("\n".join(out), encoding="utf-8")
    return n


# =====================================================================
#  Nhập kịch bản
# =====================================================================
def _norm(h) -> str:
    return re.sub(r"\s+", " ", str(h or "")).strip().lower()


def _rows_to_entries(rows):
    """Bảng (có / không có tiêu đề) -> [(trang | None, ô | None, bản dịch)]."""
    rows = [[("" if c is None else str(c)).strip() for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    head = [_norm(c) for c in rows[0]]
    ci_page = ci_box = ci_tr = None
    for i, h in enumerate(head):
        if ci_page is None and h in ("trang", "page", "p", "tr", "trang số"):
            ci_page = i
        elif ci_box is None and h in ("ô", "o", "#", "box", "id", "stt", "ô số", "khung"):
            ci_box = i
        elif ci_tr is None and ("dịch" in h or h in ("vi", "translation", "tiếng việt", "việt")):
            ci_tr = i
    if ci_tr is not None:  # có tiêu đề
        body = rows[1:]
    else:
        body = rows
        ncol = max(len(r) for r in rows)
        if ncol >= 3 and all((r[0].isdigit() and r[1].isdigit()) for r in rows[:3] if len(r) >= 2):
            ci_page, ci_box, ci_tr = 0, 1, ncol - 1
        elif ncol == 2 and all(r[0].isdigit() for r in rows[:3]):
            ci_box, ci_tr = 0, 1
        else:
            ci_tr = ncol - 1
    out = []
    for r in body:
        def cell(i):
            return r[i] if i is not None and i < len(r) else ""
        tr = cell(ci_tr)
        pg, bx = cell(ci_page), cell(ci_box)
        out.append((int(pg) if pg.isdigit() else None, int(bx) if bx.isdigit() else None, tr))
    return out


def _text_to_entries(txt: str):
    """Văn bản: hỗ trợ ban_dich.txt của app ([k] gốc / → dịch), '## Trang N' + 'k. câu',
    hoặc mỗi dòng 1 câu theo thứ tự đọc."""
    entries, page, auto_k = [], None, 0
    lines = txt.replace("\r", "").split("\n")
    has_arrow = any(l.strip().startswith("→") for l in lines)
    last_k = None
    for line in lines:
        s = line.strip()
        if not s:
            continue
        m = PAGE_RE.match(s)
        if m and len(s) < 40:
            page, auto_k, last_k = int(m.group(1)), 0, None
            continue
        if has_arrow:  # định dạng ban_dich.txt
            m = re.match(r"^\[(\d+)\]", s)
            if m:
                last_k = int(m.group(1))
                continue
            if s.startswith("→") and last_k is not None:
                entries.append((page, last_k, s[1:].strip()))
                last_k = None
            continue
        m = NUM_LINE_RE.match(s)
        if m:
            k, t = int(m.group(1)), m.group(2).strip()
        else:
            auto_k += 1
            k, t = (auto_k if page is not None else None), s
        t = re.sub(r"\s*\(giữ nguyên\)\s*$", "", t)
        auto_k = k or auto_k
        entries.append((page, k if page is not None else None, t))
    return entries


def _docx_text(path) -> str:
    """Đọc chữ trong .docx không cần thư viện ngoài (mỗi đoạn 1 dòng)."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    out = []
    for p in paras:
        p = re.sub(r"<w:tab/>", "\t", p)
        p = re.sub(r"<w:br/>", "\n", p)
        out.append(re.sub(r"<[^>]+>", "", p))
    import html

    return html.unescape("\n".join(out))


def read_script(path):
    """Đọc file kịch bản -> [(trang 1.. | None, ô 1.. | None, bản dịch)]."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return _rows_to_entries(rows)
    if ext == ".docx":
        txt = _docx_text(path)
        if txt.count("\t") > 3:
            return _rows_to_entries([l.split("\t") for l in txt.splitlines()])
        return _text_to_entries(txt)
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    if ext == ".json":
        data = json.loads(raw)
        if isinstance(data, dict) and "pages" in data:  # project.json của app
            out = []
            for p in data["pages"]:
                for k, b in enumerate(p.get("blocks", []), 1):
                    out.append((p.get("index", 0) + 1, k, b.get("translation", "")))
            return out
        out = []
        for it in data if isinstance(data, list) else []:
            if isinstance(it, str):
                out.append((None, None, it))
            elif isinstance(it, dict):
                pg = it.get("page", it.get("trang"))
                bx = it.get("box", it.get("o", it.get("ô", it.get("id"))))
                out.append((int(pg) if str(pg).isdigit() else None, int(bx) if str(bx).isdigit() else None,
                            str(it.get("vi", it.get("translation", it.get("dich", ""))) or "")))
        return out
    if ext in (".tsv", ".csv"):
        dialect = csv.excel_tab if ext == ".tsv" or raw.count("\t") > raw.count(",") else csv.excel
        return _rows_to_entries(list(csv.reader(io.StringIO(raw), dialect)))
    return _text_to_entries(raw)


def apply_script(project: dict, entries, skip_keep: bool = True):
    """Áp kịch bản vào dự án. Có số trang + số ô -> đặt đúng ô; không có -> điền lần lượt theo
    thứ tự đọc (bỏ qua ô 'giữ nguyên'). Trả về (số ô đã đổi, danh sách index trang bị đổi)."""
    pages = sorted(project["pages"], key=lambda p: p["index"])
    by_index = {p["index"] + 1: p for p in pages}
    changed, touched = 0, set()

    def put(p, k, t):
        nonlocal changed
        if 0 <= k < len(p["blocks"]):
            b = p["blocks"][k]
            t = (t or "").strip()
            if b.get("translation", "") != t:
                b["translation"] = t
                changed += 1
                touched.add(p["index"])

    seq = []
    page_seq = {}
    for pg, bx, t in entries:
        if pg is not None and bx is not None:
            if pg in by_index:
                put(by_index[pg], bx - 1, t)
        elif pg is not None:
            page_seq.setdefault(pg, []).append(t)
        else:
            seq.append(t)
    for pg, ts in page_seq.items():  # có trang, không số ô -> điền lần lượt trong trang
        p = by_index.get(pg)
        if not p:
            continue
        slots = [k for k, b in enumerate(p["blocks"]) if not (skip_keep and b.get("keep"))]
        for k, t in zip(slots, ts):
            put(p, k, t)
    if seq:  # không có số trang -> điền lần lượt cả chương
        slots = [(p, k) for p in pages for k, b in enumerate(p["blocks"]) if not (skip_keep and b.get("keep"))]
        for (p, k), t in zip(slots, seq):
            put(p, k, t)
    return changed, sorted(touched)


# =====================================================================
#  Tìm & thay thế
# =====================================================================
def _pattern(find: str, case: bool, whole: bool, regex: bool):
    pat = find if regex else re.escape(find)
    if whole:
        pat = rf"(?<![\wÀ-ỹ]){pat}(?![\wÀ-ỹ])"
    return re.compile(pat, 0 if case else re.I)


def find_matches(project: dict, find: str, repl: str = "", case=False, whole=False, regex=False,
                 field: str = "translation"):
    """[(index trang, ô, trước, sau)] mọi ô có chữ cần tìm."""
    if not find:
        return []
    rx = _pattern(find, case, whole, regex)
    out = []
    for p in sorted(project["pages"], key=lambda p: p["index"]):
        for k, b in enumerate(p["blocks"]):
            t = b.get(field, "") or ""
            if rx.search(t):
                out.append((p["index"], k, t, rx.sub(repl if regex else (lambda _m: repl), t)))
    return out


def replace_all(project: dict, find: str, repl: str, case=False, whole=False, regex=False, only=None):
    """Thay trong bản dịch. only: tập (index trang, ô) được phép thay. Trả về danh sách index trang bị đổi."""
    touched = set()
    for pi, k, _before, after in find_matches(project, find, repl, case, whole, regex):
        if only is not None and (pi, k) not in only:
            continue
        for p in project["pages"]:
            if p["index"] == pi:
                p["blocks"][k]["translation"] = after
                touched.add(pi)
    return sorted(touched)


# =====================================================================
#  Soát lỗi (QC)
# =====================================================================
# mã lỗi: (nhóm, mô tả). Nhóm: 1 = nên sửa trước khi xuất, 2 = lệch khung, 3 = kiểm tra lại
QC_CODES = {
    "E01": (1, "❌ Chưa dịch"),
    "E02": (1, "❌ Còn chữ gốc trong bản dịch"),
    "E03": (1, "❌ AI trả thừa chữ (chú thích / nhãn)"),
    "W01": (2, "⚠ Chữ tràn khung"),
    "W02": (2, "⚠ Câu dịch quá dài so với bóng"),
    "W03": (3, "✎ Lỗi dấu câu / khoảng trắng"),
    "W04": (3, "✎ Lặp từ liên tiếp"),
    "W05": (3, "✎ Thuật ngữ chưa đúng bảng"),
    "W06": (3, "✎ Bản dịch giống hệt chữ gốc"),
    "W07": (3, "✎ Ngoặc / ngoặc kép bị lẻ"),
}
_PUNCT_BAD = re.compile(r"\s+[,.!?;:…]|[,;:](?=[^\s\d\"'”’)\]])|!{4,}|\?{4,}|\.{4,}|\s{2,}")
_AI_JUNK = re.compile(r"^\s*(bản dịch|dịch|translation|vi|tiếng việt)\s*[:：]|\(\s*(chú thích|ghi chú|note)|"
                      r"<think>|```|\{\"id\"", re.I)
_REPEAT = re.compile(r"(?<![\wÀ-ỹ])([\wÀ-ỹ]{2,})\s+\1(?![\wÀ-ỹ])", re.I)
_REPEAT_OK = {"từ", "dần", "lâu", "mãi", "khóc", "ha", "hê", "hì", "hu", "ư", "ừ", "chậm", "nhanh", "đi"}


def qc_check(project: dict, terms=None):
    """[(index trang, ô, mã lỗi, chi tiết)]. terms: [{'src','dst'}] thuật ngữ gốc đang bật."""
    issues = []
    for p in sorted(project["pages"], key=lambda p: p["index"]):
        for k, b in enumerate(p["blocks"]):
            if b.get("keep"):
                continue
            src, tr = b.get("text", "") or "", (b.get("translation", "") or "").strip()

            def add(code, detail=""):
                issues.append((p["index"], k, code, detail or f"{_one_line(src)}  →  {_one_line(tr)}"))
            if not tr:
                if src.strip():
                    add("E01", _one_line(src))
                continue
            if CJK_RE.search(tr):
                add("E02")
            if _AI_JUNK.search(tr):
                add("E03")
            if b.get("overflow"):
                add("W01")
            else:
                n_src = len(re.sub(r"\s", "", src))
                if CJK_RE.search(src) and n_src and len(tr) > max(60, 7 * n_src):
                    add("W02")
            if _PUNCT_BAD.search(tr):
                add("W03")
            m = _REPEAT.search(tr)
            if m and m.group(1).lower() not in _REPEAT_OK:
                add("W04", f"“{m.group(0)}” trong: {_one_line(tr)}")
            for t in terms or []:
                if t["src"] and t["src"].lower() in src.lower() and t["dst"].lower() not in tr.lower():
                    add("W05", f"{t['src']} → phải là “{t['dst']}”:  {_one_line(tr)}")
                    break
            if _one_line(tr).lower() == _one_line(src).lower() and len(tr) > 3:
                add("W06")
            if tr.count("(") != tr.count(")") or tr.count("“") != tr.count("”") or tr.count('"') % 2:
                add("W07")
    issues.sort(key=lambda x: (QC_CODES[x[2]][0], x[0], x[1]))
    return issues


def fix_punct(t: str) -> str:
    """Sửa lỗi trình bày hay gặp: khoảng trắng thừa, dấu cách trước dấu câu, thiếu cách sau dấu,
    '....' -> '...', '!!!!!' -> '!!!', bỏ nhãn 'Bản dịch:' AI trả thừa, viết hoa chữ đầu câu."""
    if not t:
        return t
    s = re.sub(r"^\s*(bản dịch|dịch|translation)\s*[:：]\s*", "", t, flags=re.I)
    s = s.replace("…", "...")
    s = re.sub(r"\s*\.\s*\.\s*\.(\s*\.)*", "...", s)
    s = re.sub(r"!{4,}", "!!!", s)
    s = re.sub(r"\?{4,}", "???", s)
    s = re.sub(r"\s+([,.!?;:])", r"\1", s)
    s = re.sub(r"([,;:])(?=[^\s\d\"'”’)\]])", r"\1 ", s)
    s = re.sub(r"([!?])(?=[A-Za-zÀ-ỹ])", r"\1 ", s)
    s = re.sub(r"(\.\.\.)(?=[A-Za-zÀ-ỹ])", r"\1 ", s)
    s = " ".join(s.split())
    m = re.search(r"[A-Za-zÀ-ỹđĐ]", s)
    if m and m.start() <= 3 and s[m.start()].islower() and not s.startswith("..."):
        s = s[:m.start()] + s[m.start()].upper() + s[m.start() + 1:]
    return s


def auto_fix(project: dict):
    """Tự sửa dấu câu mọi ô. Trả về (số ô đã sửa, danh sách index trang bị đổi)."""
    n, touched = 0, set()
    for p in project["pages"]:
        for b in p["blocks"]:
            tr = b.get("translation", "")
            if not tr or b.get("keep"):
                continue
            new = fix_punct(tr)
            if new != tr:
                b["translation"] = new
                n += 1
                touched.add(p["index"])
    return n, sorted(touched)
