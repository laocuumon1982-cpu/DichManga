"""Các hộp thoại công cụ: Xưng hô nhân vật, Tìm & thay thế, Logo nhóm dịch, Cắt/ghép webtoon, Phím tắt."""
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
                               QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton,
                               QVBoxLayout)

from core.postfx import LOGO_PAGES, LOGO_POS
from core.store import PRONOUN_PRESETS, Pronouns

# Mẫu văn phong cho AI (hồ sơ thể loại truyện)
STYLE_PRESETS = [
    ("Tiên hiệp / cổ trang", "cổ trang tiên hiệp, xưng ta – ngươi, huynh – muội, sư phụ – đồ nhi; "
                             "dùng từ Hán Việt vừa phải, câu gọn"),
    ("Học đường", "trẻ trung, học đường, xưng tớ – cậu, mình – bạn; câu ngắn, tự nhiên như học sinh nói chuyện"),
    ("Shounen hành động", "sôi nổi, câu ngắn mạnh; xưng tao – mày khi gây gổ, tôi – cậu khi bình thường; "
                          "tiếng hét dùng dấu !"),
    ("Manhwa hiện đại", "hiện đại, đời thường, xưng anh – em / tôi – cậu theo tuổi tác và độ thân thiết"),
    ("Ngôn tình", "lãng mạn, nhẹ nhàng, tình cảm; xưng anh – em giữa cặp đôi"),
    ("Kinh dị / trinh thám", "u tối, căng thẳng, câu ngắn gọn; xưng tôi – anh / cô"),
    ("Hài hước", "hài hước, dí dỏm, dùng từ lóng vừa phải, giữ câu đùa"),
]


def _title(text):
    t = QLabel(text)
    t.setObjectName("cardTitle")
    return t


def _hint(text):
    h = QLabel(text)
    h.setObjectName("cardHint")
    h.setWordWrap(True)
    return h


# =====================================================================
#  Xưng hô nhân vật
# =====================================================================
class PronounDialog(QDialog):
    COLS = ["Bật", "Nhân vật A", "Nhân vật B", "A xưng", "A gọi B", "B xưng", "B gọi A", "Ghi chú"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("👥 Xưng hô nhân vật")
        self.resize(980, 560)
        self.db = Pronouns()
        self._loading = False
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(_title("👥  Xưng hô giữa các nhân vật – AI dịch đúng vai vế"))
        v.addWidget(_hint(
            "Mỗi dòng là 1 cặp nhân vật và cách họ gọi nhau (vd. <i>凌伊山 ↔ 小梅: A xưng 'ta', gọi B là 'đồ nhi'; "
            "B xưng 'đệ tử', gọi A là 'sư phụ'</i>). Tên viết bằng chữ gốc thì chỉ gửi khi tên đó có trong chương; "
            "tên viết tiếng Việt thì luôn gửi. Dùng cho bộ dịch <b>AI (LLM)</b>."))
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for c in range(1, len(self.COLS)):
            hh.setSectionResizeMode(c, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_changed)
        v.addWidget(self.table, 1)

        g = QGridLayout()
        g.setHorizontalSpacing(6)
        self.ed = {}
        for c, (key, ph) in enumerate((("a", "Nhân vật A"), ("b", "Nhân vật B"), ("a_self", "A xưng"),
                                       ("a_calls_b", "A gọi B là"), ("b_self", "B xưng"),
                                       ("b_calls_a", "B gọi A là"), ("note", "Ghi chú"))):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            e.returnPressed.connect(self._add)
            self.ed[key] = e
            g.addWidget(e, 0, c)
        b_preset = QToolButton()
        b_preset.setText("✨ Mẫu")
        b_preset.setToolTip("Điền nhanh cặp xưng hô hay gặp")
        b_preset.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(b_preset)
        for name, *vals in PRONOUN_PRESETS:
            act = m.addAction(name)
            act.triggered.connect(lambda _=False, vv=vals: self._preset(vv))
        b_preset.setMenu(m)
        g.addWidget(b_preset, 0, 7)
        b_add = QPushButton("➕ Thêm")
        b_add.setObjectName("primary")
        b_add.clicked.connect(self._add)
        g.addWidget(b_add, 0, 8)
        v.addLayout(g)

        bot = QHBoxLayout()
        b_del = QPushButton("🗑 Xoá dòng chọn")
        b_del.setObjectName("danger")
        b_del.clicked.connect(self._delete)
        b_prev = QPushButton("👁 Xem trước lời nhắn cho AI")
        b_prev.clicked.connect(self._preview)
        self.lbl = QLabel("")
        self.lbl.setObjectName("cardHint")
        b_close = QPushButton("Đóng")
        b_close.clicked.connect(self.accept)
        for w in (b_del, b_prev, self.lbl):
            bot.addWidget(w)
        bot.addStretch(1)
        bot.addWidget(b_close)
        v.addLayout(bot)
        self.reload()

    def _preset(self, vals):
        for key, val in zip(("a_self", "a_calls_b", "b_self", "b_calls_a"), vals):
            self.ed[key].setText(val)
        (self.ed["a"] if not self.ed["a"].text() else self.ed["b"]).setFocus()

    def reload(self):
        self._loading = True
        rows = self.db.all()
        self.table.setRowCount(0)
        for r in rows:
            k = self.table.rowCount()
            self.table.insertRow(k)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if r["enabled"] else Qt.Unchecked)
            chk.setData(Qt.UserRole, r["id"])
            self.table.setItem(k, 0, chk)
            for c, key in enumerate(("a", "b", "a_self", "a_calls_b", "b_self", "b_calls_a", "note"), 1):
                self.table.setItem(k, c, QTableWidgetItem(r[key]))
        self.lbl.setText(f"{len(rows)} cặp")
        self._loading = False

    def _on_changed(self, item):
        if self._loading:
            return
        k = item.row()
        vals = [self.table.item(k, c).text() if self.table.item(k, c) else "" for c in range(1, 8)]
        if not vals[0].strip() or not vals[1].strip():
            return
        it = self.table.item(k, 0)
        try:
            self.db.upsert(*vals, enabled=it.checkState() == Qt.Checked, row_id=it.data(Qt.UserRole))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Không lưu được", str(e))
            self.reload()

    def _add(self):
        d = {k: e.text().strip() for k, e in self.ed.items()}
        if not d["a"] or not d["b"]:
            return
        self.db.upsert(d["a"], d["b"], d["a_self"], d["a_calls_b"], d["b_self"], d["b_calls_a"], d["note"])
        for e in self.ed.values():
            e.clear()
        self.ed["a"].setFocus()
        self.reload()

    def _delete(self):
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        if rows and QMessageBox.question(self, "Xoá", f"Xoá {len(rows)} cặp đã chọn?") == QMessageBox.Yes:
            for k in rows:
                self.db.delete(self.table.item(k, 0).data(Qt.UserRole))
            self.reload()

    def _preview(self):
        txt = self.db.prompt_text() or "(chưa có cặp nào đang bật)"
        QMessageBox.information(self, "Gửi cho AI", "CÁCH XƯNG HÔ GIỮA CÁC NHÂN VẬT:\n" + txt)


# =====================================================================
#  Tìm & thay thế
# =====================================================================
class FindReplaceDialog(QDialog):
    def __init__(self, parent, project, on_apply):
        super().__init__(parent)
        self.setWindowTitle("🔍 Tìm & thay thế – cả chương")
        self.resize(900, 560)
        self.project, self.on_apply = project, on_apply
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(_title("🔍  Tìm & thay thế trong bản dịch cả chương"))
        g = QGridLayout()
        self.ed_find = QLineEdit()
        self.ed_find.setPlaceholderText("Tìm (vd. ngài)")
        self.ed_repl = QLineEdit()
        self.ed_repl.setPlaceholderText("Thay bằng (vd. người)")
        g.addWidget(QLabel("Tìm"), 0, 0)
        g.addWidget(self.ed_find, 0, 1)
        g.addWidget(QLabel("Thay bằng"), 1, 0)
        g.addWidget(self.ed_repl, 1, 1)
        v.addLayout(g)
        opt = QHBoxLayout()
        self.chk_case = QCheckBox("Phân biệt HOA/thường")
        self.chk_whole = QCheckBox("Khớp trọn từ")
        self.chk_whole.setChecked(True)
        self.chk_regex = QCheckBox("Biểu thức chính quy (regex)")
        for w in (self.chk_case, self.chk_whole, self.chk_regex):
            opt.addWidget(w)
            w.toggled.connect(self._search)
        opt.addStretch(1)
        v.addLayout(opt)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Thay", "Trang/Ô", "Trước", "Sau"])
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        v.addWidget(self.table, 1)
        bot = QHBoxLayout()
        self.lbl = QLabel("")
        self.lbl.setObjectName("cardHint")
        b_apply = QPushButton("✔ Thay các ô đã tick && vẽ lại")
        b_apply.setObjectName("primary")
        b_apply.clicked.connect(self._apply)
        b_close = QPushButton("Đóng")
        b_close.clicked.connect(self.reject)
        bot.addWidget(self.lbl, 1)
        bot.addWidget(b_apply)
        bot.addWidget(b_close)
        v.addLayout(bot)
        self.ed_find.textChanged.connect(self._search)
        self.ed_repl.textChanged.connect(self._search)

    def _opts(self):
        return dict(case=self.chk_case.isChecked(), whole=self.chk_whole.isChecked(),
                    regex=self.chk_regex.isChecked())

    def _search(self):
        from core.script import find_matches

        self.table.setRowCount(0)
        try:
            res = find_matches(self.project, self.ed_find.text(), self.ed_repl.text(), **self._opts())
        except Exception as e:  # noqa: BLE001  (regex sai)
            self.lbl.setText(f"⚠ {e}")
            return
        for r, (pi, k, before, after) in enumerate(res[:2000]):
            self.table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked)
            chk.setData(Qt.UserRole, (pi, k))
            self.table.setItem(r, 0, chk)
            for c, val in enumerate((f"{pi + 1}/{k + 1}", before, after), 1):
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
        self.table.resizeRowsToContents()
        self.lbl.setText(f"{len(res)} ô khớp" if self.ed_find.text() else "")

    def _apply(self):
        from core.script import replace_all

        only = {self.table.item(r, 0).data(Qt.UserRole) for r in range(self.table.rowCount())
                if self.table.item(r, 0).checkState() == Qt.Checked}
        if not only:
            return
        try:
            touched = replace_all(self.project, self.ed_find.text(), self.ed_repl.text(), only=only, **self._opts())
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Lỗi", str(e))
            return
        self.on_apply(touched)
        self.lbl.setText(f"✅ Đã thay {len(only)} ô trên {len(touched)} trang")
        self._search()


# =====================================================================
#  Logo / credit nhóm dịch
# =====================================================================
class LogoDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("🏷 Logo / credit nhóm dịch")
        self.resize(560, 360)
        self.s = settings
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(_title("🏷  Đóng dấu logo nhóm dịch lên trang"))
        v.addWidget(_hint("Chọn ảnh PNG nền trong suốt. 'Tự chọn góc trống' đặt logo vào góc ít chi tiết nhất "
                          "và không đè lên bóng thoại. Áp dụng khi dịch hoặc bấm 'Vẽ lại tất cả'."))
        g = QGridLayout()
        g.setVerticalSpacing(8)
        self.chk_on = QCheckBox("Bật đóng dấu logo")
        self.chk_on.setChecked(settings.get_bool("logo_on", False))
        g.addWidget(self.chk_on, 0, 0, 1, 3)
        self.ed_path = QLineEdit(settings.value("logo_path", "") or "")
        b = QPushButton("Chọn…")
        b.clicked.connect(self._pick)
        g.addWidget(QLabel("Ảnh logo"), 1, 0)
        g.addWidget(self.ed_path, 1, 1)
        g.addWidget(b, 1, 2)
        self.cb_pos = QComboBox()
        for t, d in LOGO_POS:
            self.cb_pos.addItem(t, d)
        self.cb_pages = QComboBox()
        for t, d in LOGO_PAGES:
            self.cb_pages.addItem(t, d)
        for cb, key, dv in ((self.cb_pos, "logo_pos", "auto"), (self.cb_pages, "logo_pages", "all")):
            i = cb.findData(settings.value(key, dv))
            cb.setCurrentIndex(max(0, i))
        g.addWidget(QLabel("Vị trí"), 2, 0)
        g.addWidget(self.cb_pos, 2, 1, 1, 2)
        g.addWidget(QLabel("Trang"), 3, 0)
        g.addWidget(self.cb_pages, 3, 1, 1, 2)
        self.sp_size = QSpinBox()
        self.sp_size.setRange(3, 50)
        self.sp_size.setSuffix(" % bề ngang")
        self.sp_size.setValue(settings.get_int("logo_size", 12))
        self.sl_op = QSlider(Qt.Horizontal)
        self.sl_op.setRange(10, 100)
        self.sl_op.setValue(settings.get_int("logo_opacity", 85))
        self.lbl_op = QLabel(f"{self.sl_op.value()}%")
        self.sl_op.valueChanged.connect(lambda x: self.lbl_op.setText(f"{x}%"))
        g.addWidget(QLabel("Cỡ"), 4, 0)
        g.addWidget(self.sp_size, 4, 1, 1, 2)
        g.addWidget(QLabel("Độ đậm"), 5, 0)
        g.addWidget(self.sl_op, 5, 1)
        g.addWidget(self.lbl_op, 5, 2)
        self.ed_credit = QLineEdit(settings.value("credit", "") or "")
        self.ed_credit.setPlaceholderText("vd. Nhóm dịch ABC (ghi vào file .cbz)")
        g.addWidget(QLabel("Tên nhóm"), 6, 0)
        g.addWidget(self.ed_credit, 6, 1, 1, 2)
        v.addLayout(g)
        v.addStretch(1)
        bot = QHBoxLayout()
        bot.addStretch(1)
        ok = QPushButton("✔ Lưu")
        ok.setObjectName("primary")
        ok.clicked.connect(self._save)
        cancel = QPushButton("Huỷ")
        cancel.clicked.connect(self.reject)
        bot.addWidget(ok)
        bot.addWidget(cancel)
        v.addLayout(bot)

    def _pick(self):
        f, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh logo", "", "Ảnh (*.png *.webp *.jpg *.jpeg)")
        if f:
            self.ed_path.setText(f)
            self.chk_on.setChecked(True)

    def _save(self):
        p = self.ed_path.text().strip()
        if self.chk_on.isChecked() and (not p or not Path(p).is_file()):
            QMessageBox.warning(self, "Logo", "Chưa chọn ảnh logo hợp lệ.")
            return
        s = self.s
        s.setValue("logo_on", self.chk_on.isChecked())
        s.setValue("logo_path", p)
        s.setValue("logo_pos", self.cb_pos.currentData())
        s.setValue("logo_pages", self.cb_pages.currentData())
        s.setValue("logo_size", self.sp_size.value())
        s.setValue("logo_opacity", self.sl_op.value())
        s.setValue("credit", self.ed_credit.text().strip())
        s.save()
        self.accept()


# =====================================================================
#  Cắt / ghép webtoon
# =====================================================================
class _WebtoonJob(QThread):
    done = Signal(bool, str)

    def __init__(self, mode, paths, out, height, boxes, ext):
        super().__init__()
        self.args = (mode, paths, out, height, boxes, ext)

    def run(self):
        from core.postfx import merge_strip, split_strip

        mode, paths, out, height, boxes, ext = self.args
        try:
            if mode == "merge":
                res = merge_strip(paths, Path(out) / f"webtoon_ghep.{ext}", boxes)
                self.done.emit(True, f"Đã ghép {len(paths)} trang thành {len(res)} ảnh dài trong:\n{out}")
            else:
                res = split_strip(paths, Path(out) / "webtoon_cat", height, boxes, ext)
                self.done.emit(True, f"Đã cắt thành {len(res)} ảnh (~{height}px, không cắt ngang chữ) trong:\n"
                                     f"{Path(out) / 'webtoon_cat'}")
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, str(e))


class WebtoonDialog(QDialog):
    def __init__(self, parent, project, out_dir):
        super().__init__(parent)
        self.setWindowTitle("📜 Cắt / ghép webtoon")
        self.resize(560, 300)
        self.project, self.out_dir, self.job = project, out_dir, None
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(_title("📜  Cắt / ghép trang webtoon đã dịch"))
        v.addWidget(_hint("• <b>Ghép</b>: nối mọi trang thành 1 ảnh cuộn dài (JPG quá 65.000px tự chia phần).<br>"
                          "• <b>Cắt thông minh</b>: ghép rồi cắt lại theo chiều cao chọn, chỉ cắt ở dải nền trơn và "
                          "<b>không bao giờ cắt ngang bóng thoại / chữ</b>."))
        g = QGridLayout()
        self.cb_mode = QComboBox()
        self.cb_mode.addItem("✂ Cắt thông minh theo chiều cao", "split")
        self.cb_mode.addItem("🔗 Ghép thành 1 ảnh dài", "merge")
        self.sp_h = QSpinBox()
        self.sp_h.setRange(800, 5000)
        self.sp_h.setSingleStep(100)
        self.sp_h.setValue(2000)
        self.sp_h.setSuffix(" px")
        self.cb_ext = QComboBox()
        self.cb_ext.addItems(["jpg", "png", "webp"])
        g.addWidget(QLabel("Cách làm"), 0, 0)
        g.addWidget(self.cb_mode, 0, 1)
        g.addWidget(QLabel("Chiều cao mỗi ảnh"), 1, 0)
        g.addWidget(self.sp_h, 1, 1)
        g.addWidget(QLabel("Định dạng"), 2, 0)
        g.addWidget(self.cb_ext, 2, 1)
        self.cb_mode.currentIndexChanged.connect(lambda: self.sp_h.setEnabled(self.cb_mode.currentData() == "split"))
        v.addLayout(g)
        self.lbl = _hint("")
        v.addWidget(self.lbl)
        v.addStretch(1)
        bot = QHBoxLayout()
        bot.addStretch(1)
        self.b_run = QPushButton("▶ Thực hiện")
        self.b_run.setObjectName("primary")
        self.b_run.clicked.connect(self._run)
        b_close = QPushButton("Đóng")
        b_close.clicked.connect(self.reject)
        bot.addWidget(self.b_run)
        bot.addWidget(b_close)
        v.addLayout(bot)

    def _run(self):
        pages = sorted(self.project["pages"], key=lambda p: p["index"])
        paths = [p["out"] for p in pages if Path(p["out"]).is_file()]
        if not paths:
            QMessageBox.information(self, "Webtoon", "Chưa có trang đã dịch.")
            return
        boxes = {p["out"]: [tuple(b["rect"]) for b in p["blocks"] if b.get("rect")] for p in pages}
        self.b_run.setEnabled(False)
        self.lbl.setText("⏳ Đang xử lý...")
        self.job = _WebtoonJob(self.cb_mode.currentData(), paths, self.out_dir, self.sp_h.value(), boxes,
                               self.cb_ext.currentText())
        self.job.done.connect(self._done)
        self.job.start()

    def _done(self, ok, msg):
        self.b_run.setEnabled(True)
        self.lbl.setText(("✅ " if ok else "❌ ") + msg)

    def reject(self):
        if self.job is not None and self.job.isRunning():
            self.job.wait()
        super().reject()


# =====================================================================
#  Phím tắt
# =====================================================================
SHORTCUTS = [
    ("Ctrl+O", "Mở thư mục ảnh"), ("Ctrl+Shift+O", "Mở PDF / CBZ / ZIP"), ("Ctrl+Enter", "Bắt đầu dịch"),
    ("Ctrl+S", "Lưu bản sửa trang đang xem & vẽ lại"), ("Ctrl+Shift+S", "Vẽ lại tất cả trang"),
    ("Alt+← / Alt+→", "Trang trước / trang sau"), ("Ctrl+H", "Tìm & thay thế cả chương"),
    ("Ctrl+I", "Nhập kịch bản (bản dịch làm sẵn)"), ("F6", "Xưng hô nhân vật"), ("F7", "Soát lỗi cả chương"),
    ("F8", "Tự sửa dấu câu"), ("F12", "Cắt / ghép webtoon"), ("F1", "Bảng phím tắt này"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⌨ Phím tắt")
        self.resize(460, 460)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.addWidget(_title("⌨  Phím tắt"))
        tb = QTextBrowser()
        rows = "".join(f"<tr><td style='padding:4px 14px 4px 0'><b>{k}</b></td><td>{d}</td></tr>"
                       for k, d in SHORTCUTS)
        tb.setHtml(f"<table>{rows}</table>")
        v.addWidget(tb, 1)
        b = QPushButton("Đóng")
        b.clicked.connect(self.accept)
        v.addWidget(b, 0, Qt.AlignRight)
