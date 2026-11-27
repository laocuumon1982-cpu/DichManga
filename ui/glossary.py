"""Hộp thoại Bảng thuật ngữ (lưu trong data.db – SQLite)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from core.store import Glossary

LANG_OPTS = [("Mọi ngôn ngữ", ""), ("Trung", "zh"), ("Trung phồn thể", "zh_tw"), ("Nhật", "ja"), ("Hàn", "ko"), ("Anh", "en")]


class GlossaryDialog(QDialog):
    COLS = ["Bật", "Chữ gốc", "Dịch thành", "Ghi chú (giới tính, xưng hô...)", "Ngôn ngữ"]

    def __init__(self, parent=None, glossary: Glossary = None):
        super().__init__(parent)
        self.setWindowTitle("📖 Bảng thuật ngữ")
        self.resize(860, 560)
        self.g = glossary or Glossary()
        self._loading = False
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        t = QLabel("📖  Bảng thuật ngữ – tên riêng, xưng hô, từ cố định")
        t.setObjectName("cardTitle")
        v.addWidget(t)
        hint = QLabel(
            "• <b>Chữ gốc là Trung / Nhật / Anh</b> (vd. <i>凌伊山 → Lăng Y Sơn</i>): AI (LLM) dịch đúng tên riêng, "
            "xưng hô theo bảng; GTX được thay sẵn tên trước khi dịch.<br>"
            "• <b>Chữ gốc là tiếng Việt</b> (vd. <i>Lin Yishan → Lăng Y Sơn</i>, <i>ngài → người</i>): tự <b>sửa sau "
            "khi dịch</b> với mọi bộ dịch.<br>Sửa xong bấm <b>🔁 Dịch lại</b> ở màn hình chính để áp dụng cho truyện "
            "đã dịch.")
        hint.setObjectName("cardHint")
        hint.setWordWrap(True)
        v.addWidget(hint)

        row = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("🔎 Tìm...")
        self.ed_search.textChanged.connect(self._filter)
        row.addWidget(self.ed_search, 1)
        v.addLayout(row)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._on_changed)
        v.addWidget(self.table, 1)

        add = QHBoxLayout()
        self.ed_src = QLineEdit()
        self.ed_src.setPlaceholderText("Chữ gốc (vd. 凌伊山)")
        self.ed_dst = QLineEdit()
        self.ed_dst.setPlaceholderText("Dịch thành (vd. Lăng Y Sơn)")
        self.ed_note = QLineEdit()
        self.ed_note.setPlaceholderText("Ghi chú (tuỳ chọn)")
        self.cb_lang = QComboBox()
        for txt, d in LANG_OPTS:
            self.cb_lang.addItem(txt, d)
        b_add = QPushButton("➕ Thêm")
        b_add.setObjectName("primary")
        b_add.clicked.connect(self._add)
        self.ed_dst.returnPressed.connect(self._add)
        self.ed_note.returnPressed.connect(self._add)
        for w, s in ((self.ed_src, 2), (self.ed_dst, 2), (self.ed_note, 2), (self.cb_lang, 1), (b_add, 0)):
            add.addWidget(w, s)
        v.addLayout(add)

        bot = QHBoxLayout()
        b_del = QPushButton("🗑 Xoá dòng chọn")
        b_del.setObjectName("danger")
        b_del.clicked.connect(self._delete)
        b_imp = QPushButton("📥 Nhập CSV")
        b_imp.setToolTip("File CSV/TSV: cột 1 = chữ gốc, cột 2 = dịch thành, cột 3 = ghi chú (tuỳ chọn)")
        b_imp.clicked.connect(self._import)
        b_exp = QPushButton("📤 Xuất CSV")
        b_exp.clicked.connect(self._export)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("cardHint")
        b_close = QPushButton("Đóng")
        b_close.clicked.connect(self.accept)
        for w in (b_del, b_imp, b_exp):
            bot.addWidget(w)
        bot.addWidget(self.lbl_count)
        bot.addStretch(1)
        bot.addWidget(b_close)
        v.addLayout(bot)
        self.reload()

    # ---------------- dữ liệu ----------------
    def reload(self):
        self._loading = True
        rows = self.g.all()
        self.table.setRowCount(0)
        for r in rows:
            k = self.table.rowCount()
            self.table.insertRow(k)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if r["enabled"] else Qt.Unchecked)
            chk.setData(Qt.UserRole, r["id"])
            self.table.setItem(k, 0, chk)
            for c, key in ((1, "src"), (2, "dst"), (3, "note")):
                self.table.setItem(k, c, QTableWidgetItem(r[key]))
            lang = QTableWidgetItem(dict((d, t) for t, d in LANG_OPTS).get(r["lang"], r["lang"]))
            lang.setData(Qt.UserRole, r["lang"])
            lang.setFlags(lang.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(k, 4, lang)
        self.lbl_count.setText(f"{len(rows)} thuật ngữ")
        self._loading = False
        self._filter(self.ed_search.text())

    def _row_data(self, k):
        it = self.table.item(k, 0)
        return dict(row_id=it.data(Qt.UserRole), enabled=it.checkState() == Qt.Checked,
                    src=self.table.item(k, 1).text(), dst=self.table.item(k, 2).text(),
                    note=self.table.item(k, 3).text(), lang=self.table.item(k, 4).data(Qt.UserRole) or "")

    def _on_changed(self, item):
        if self._loading:
            return
        d = self._row_data(item.row())
        if not d["src"].strip() or not d["dst"].strip():
            return
        try:
            self.g.upsert(d["src"], d["dst"], d["note"], d["lang"], d["enabled"], d["row_id"])
        except Exception as e:  # noqa: BLE001  (trùng chữ gốc...)
            QMessageBox.warning(self, "Không lưu được", str(e))
            self.reload()

    def _add(self):
        src, dst = self.ed_src.text().strip(), self.ed_dst.text().strip()
        if not src or not dst:
            return
        self.g.upsert(src, dst, self.ed_note.text().strip(), self.cb_lang.currentData())
        for w in (self.ed_src, self.ed_dst, self.ed_note):
            w.clear()
        self.ed_src.setFocus()
        self.reload()

    def _delete(self):
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        if not rows:
            return
        if QMessageBox.question(self, "Xoá", f"Xoá {len(rows)} thuật ngữ đã chọn?") != QMessageBox.Yes:
            return
        for k in rows:
            self.g.delete(self.table.item(k, 0).data(Qt.UserRole))
        self.reload()

    def _import(self):
        f, _ = QFileDialog.getOpenFileName(self, "Nhập bảng thuật ngữ", "", "CSV / TSV (*.csv *.tsv *.txt)")
        if not f:
            return
        try:
            n = self.g.import_csv(f)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Lỗi", str(e))
            return
        self.reload()
        QMessageBox.information(self, "Đã nhập", f"Đã nhập {n} thuật ngữ.")

    def _export(self):
        f, _ = QFileDialog.getSaveFileName(self, "Xuất bảng thuật ngữ", "thuat_ngu.csv", "CSV (*.csv)")
        if f:
            n = self.g.export_csv(f)
            QMessageBox.information(self, "Đã xuất", f"Đã xuất {n} thuật ngữ.")

    def _filter(self, text):
        t = (text or "").lower()
        for k in range(self.table.rowCount()):
            show = not t or any(t in (self.table.item(k, c).text() or "").lower() for c in (1, 2, 3))
            self.table.setRowHidden(k, not show)
