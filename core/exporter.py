"""Xuất kết quả: ban_dich.txt, kịch bản .tsv/.txt, PDF gộp, CBZ, Excel lời thoại, PSD 3 lớp."""
from pathlib import Path

from .block import TextBlock
from .loader import export_pdf, imread
from .typeset import KIND_VI, render_page


def _cfg(cfg, key, default=None):
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def write_text_export(project: dict, path) -> None:
    out = []
    for p in project["pages"]:
        out.append(f"===== Trang {p['index'] + 1} =====")
        for k, b in enumerate(p["blocks"], 1):
            out.append(f"[{k}] {b['text']}\n    → {b['translation']}")
        out.append("")
    Path(path).write_text("\n".join(out), encoding="utf-8")


def export_xlsx(project: dict, path) -> int:
    """Bảng lời thoại: trang | ô | loại | chữ gốc | bản dịch | ghi chú (để nhóm dịch rà soát)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Lời thoại"
    head = ["Trang", "Ô", "Loại", "Chữ gốc", "Bản dịch", "Ghi chú"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="7C3AED")
        c.alignment = Alignment(horizontal="center", vertical="center")
    n = 0
    warn = PatternFill("solid", fgColor="FDE68A")
    for p in project["pages"]:
        for k, b in enumerate(p["blocks"], 1):
            note = []
            if b.get("keep"):
                note.append("giữ nguyên")
            elif not b.get("translation"):
                note.append("chưa dịch")
            if b.get("overflow"):
                note.append("chữ tràn khung")
            ws.append([p["index"] + 1, k, KIND_VI.get(b.get("kind", ""), ""), b.get("text", ""),
                       b.get("translation", ""), ", ".join(note)])
            if note and "giữ nguyên" not in note:
                for c in ws[ws.max_row]:
                    c.fill = warn
            n += 1
    for col, w in zip("ABCDEF", (7, 5, 13, 50, 60, 18)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    wb.save(path)
    return n


def export_psd(project: dict, out_dir, cfg, log=print) -> int:
    """Mỗi trang 1 file PSD 3 lớp: Gốc / Nền sạch / Chữ dịch (sửa tiếp trong Photoshop)."""
    from PIL import Image
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer
    import cv2

    psd_dir = Path(out_dir) / "psd"
    psd_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in project["pages"]:
        src, clean = imread(p.get("src", "")), imread(p.get("clean", ""))
        if src is None or clean is None:
            continue
        blocks = [TextBlock.from_dict(d) for d in p["blocks"]]
        text = render_page(clean, blocks, _cfg(cfg, "font_path", ""), _cfg(cfg, "uppercase", False), src,
                           _cfg(cfg, "font_scale", 70) / 100, text_only=True)
        H, W = clean.shape[:2]
        # ô giữ nguyên / chưa dịch: lớp nền sạch phải còn chữ gốc
        base = clean.copy()
        for b in blocks:
            if b.keep or not (b.translation or "").strip():
                m = max(4, b.char_size() // 2)
                x0, y0, x1, y1 = max(0, b.x0 - m), max(0, b.y0 - m), min(W, b.x1 + m), min(H, b.y1 + m)
                base[y0:y1, x0:x1] = src[y0:y1, x0:x1]
        psd = PSDImage.new("RGB", (W, H))
        # tên lớp không dấu (định dạng PSD lưu tên lớp kiểu cũ, không nhận chữ có dấu)
        for name, im in (("Goc (ban goc)", Image.fromarray(cv2.cvtColor(src, cv2.COLOR_BGR2RGB))),
                         ("Nen sach", Image.fromarray(cv2.cvtColor(base, cv2.COLOR_BGR2RGB))),
                         ("Chu dich", Image.fromarray(text, "RGBA"))):
            layer = PixelLayer.frompil(im, psd, name, 0, 0)
            if name.startswith("Goc"):
                layer.visible = False
        psd.save(str(psd_dir / f"{p['index'] + 1:04d}.psd"))
        n += 1
    return n


def export_extras(project: dict, out_dir, cfg, log=print) -> None:
    out_dir = Path(out_dir)
    name = project.get("source", "truyen")
    write_text_export(project, out_dir / "ban_dich.txt")
    if _cfg(cfg, "export_pdf", True):
        try:
            log("Đang xuất PDF...")
            export_pdf([p["out"] for p in project["pages"]], out_dir / f"{name}_vi.pdf")
            log(f"Đã xuất PDF: {name}_vi.pdf")
        except Exception as e:  # noqa: BLE001
            log(f"! Xuất PDF lỗi: {e}")
    if _cfg(cfg, "export_script", True):
        try:
            from .script import export_script_txt, export_tsv

            export_tsv(project, out_dir / f"{name}_kich_ban.tsv")
            export_script_txt(project, out_dir / f"{name}_kich_ban.txt")
        except Exception as e:  # noqa: BLE001
            log(f"! Xuất kịch bản lỗi: {e}")
    if _cfg(cfg, "export_cbz", False):
        try:
            from .loader import export_cbz

            n = export_cbz([p["out"] for p in project["pages"]], out_dir / f"{name}_vi.cbz", name,
                           _cfg(cfg, "credit", ""))
            log(f"Đã đóng gói {n} trang: {name}_vi.cbz")
        except Exception as e:  # noqa: BLE001
            log(f"! Xuất CBZ lỗi: {e}")
    if _cfg(cfg, "export_xlsx", True):
        try:
            n = export_xlsx(project, out_dir / f"{name}_loi_thoai.xlsx")
            log(f"Đã xuất Excel lời thoại ({n} ô): {name}_loi_thoai.xlsx")
        except ImportError:
            log("! Chưa có thư viện openpyxl – bấm Cập nhật để cài")
        except Exception as e:  # noqa: BLE001
            log(f"! Xuất Excel lỗi: {e}")
    if _cfg(cfg, "export_psd", False):
        try:
            log("Đang xuất PSD 3 lớp...")
            n = export_psd(project, out_dir, cfg, log)
            log(f"Đã xuất {n} file PSD vào thư mục psd\\")
        except ImportError:
            log("! Chưa có thư viện psd-tools – bấm Cập nhật để cài")
        except Exception as e:  # noqa: BLE001
            log(f"! Xuất PSD lỗi: {e}")
