"""Dịch Truyện Tranh v2.0 by Duy Anh – dịch truyện tranh Trung / Nhật / Anh sang tiếng Việt.

Nguồn: thư mục ảnh (đánh số trang) hoặc file PDF (kéo thả vào cửa sổ cũng được).
Dịch: model chạy trên máy (HachimiMT cho tiếng Trung, NLLB-200 cho tiếng Nhật) trên GPU,
hoặc GTX Google Translate (miễn phí, online). OCR chạy trên GPU NVIDIA nếu máy có.
"""
import argparse
import os
import sys
import threading
import time
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from core import APP_AUTHOR, APP_NAME, APP_TITLE, APP_VERSION  # noqa: E402
from core.paths import ICON_PATH, IS_PORTABLE, setup_env  # noqa: E402

setup_env()  # phải chạy trước khi import PySide6 / torch

from PySide6.QtCore import QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal  # noqa: E402
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from core.loader import IMG_EXT, export_pdf, list_images, pdf_page_count  # noqa: E402
from core.pipeline import (Config, Pipeline, default_engine, gpu_info, load_project,  # noqa: E402
                           rerender_page, save_project, write_text_export)
from core.typeset import find_default_font  # noqa: E402
from ui.dialogs import AboutDialog, UpdateChecker, UpdateDialog  # noqa: E402
from ui.theme import QSS  # noqa: E402
from ui.widgets import Card, CompareView, field, thumb_size  # noqa: E402

LANGS = [("🇨🇳  Tiếng Trung (giản thể)", "zh"), ("🇹🇼  Tiếng Trung (phồn thể)", "zh_tw"),
         ("🇯🇵  Tiếng Nhật", "ja"), ("🇬🇧  Tiếng Anh", "en")]
ENGINES = {
    "zh": [
        ("HachimiMT-60 – chạy trên máy, khuyên dùng", "local:ngocdang83/HachimiMT-60-zh-vi"),
        ("HachimiMT-30 – chạy trên máy, nhanh hơn", "local:ngocdang83/HachimiMT-30-zh-vi"),
        ("HachimiMT-60-QT – giọng convert (ta/ngươi/hắn)", "local:ngocdang83/HachimiMT-60-QT"),
        ("NLLB-200 600M (Meta) – chạy trên máy", "local:facebook/nllb-200-distilled-600M"),
        ("GTX Google – online, miễn phí", "gtx"),
    ],
    "ja": [
        ("NLLB-200 600M (Meta) – chạy trên máy, khuyên dùng", "local:facebook/nllb-200-distilled-600M"),
        ("Opus-MT ja→vi – rất nhanh, kém chính xác", "local:Helsinki-NLP/opus-mt-ja-vi"),
        ("GTX Google – online, miễn phí", "gtx"),
    ],
}
ENGINES["zh_tw"] = ENGINES["zh"]
ENGINES["en"] = [("GTX Google – online, miễn phí", "gtx")]
DEVICES = [("⚡ Tự động – ưu tiên GPU", "auto"), ("Chỉ GPU (CUDA)", "cuda"), ("Chỉ CPU", "cpu")]


# =====================================================================
#  Luồng nền
# =====================================================================
class Worker(QThread):
    log = Signal(str)
    progress = Signal(int, int)
    pages_ready = Signal(list)
    page_done = Signal(int, object)
    finished_ok = Signal(bool, str)
    stage = Signal(str)

    def __init__(self, cfg: Config, source_type: str, source_path: str):
        super().__init__()
        self.cfg, self.source_type, self.source_path = cfg, source_type, source_path
        self.stop_event = threading.Event()

    def run(self):
        project_path = ""
        try:
            pipe = Pipeline(self.cfg, log=self.log.emit, stop_event=self.stop_event)
            project_path = pipe.project_path
            self.stage.emit("Đang chuẩn bị trang...")
            pages = pipe.prepare_pages(self.source_type, self.source_path)
            self.pages_ready.emit(pages)
            if self.stop_event.is_set():
                self.finished_ok.emit(False, project_path)
                return
            self.stage.emit("Đang tải model (lần đầu có thể mất vài phút)...")
            pipe.load_models()
            self.stage.emit("Đang dịch...")
            ok = pipe.run(pages, progress=self.progress.emit, page_done=self.page_done.emit)
            self.finished_ok.emit(ok, project_path)
        except Exception:  # noqa: BLE001
            self.log.emit("LỖI:\n" + traceback.format_exc())
            self.finished_ok.emit(False, project_path)


class GpuProbe(QThread):
    """Kiểm tra GPU ở nền (import torch mất vài giây) để cửa sổ mở ngay."""
    done = Signal(bool, str)

    def run(self):
        self.done.emit(*gpu_info())


# =====================================================================
#  Cửa sổ chính
# =====================================================================
class MainWindow(QMainWindow):
    def __init__(self, check_update=True):
        super().__init__()
        self.base_title = APP_TITLE + (" (Portable)" if IS_PORTABLE else "")
        self.setWindowTitle(self.base_title)
        self.resize(1480, 900)
        self.setMinimumSize(1100, 680)
        self.setAcceptDrops(True)
        self.settings = QSettings("DuyAnh", "DichTruyenTranh")
        self.source_type = None
        self.source_path = None
        self.src_pages = []      # đường dẫn ảnh gốc theo thứ tự trang
        self.done_pages = {}     # index -> dict trang đã dịch
        self.project = None
        self.project_path = None
        self.worker = None
        self._t_start = None
        self._thumb_queue = []
        self._gpu_text = ""
        self.update_info = None
        self._build_ui()
        self._load_settings()
        self.probe = GpuProbe()
        self.probe.done.connect(self._on_gpu)
        QTimer.singleShot(200, self.probe.start)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.timeout.connect(self._load_thumbs)
        self.checker = None
        if check_update:
            QTimer.singleShot(2500, self._auto_check_update)

    # ---------------- dựng giao diện ----------------
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_pages())
        body.addWidget(self._build_workspace())
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 0)
        body.setStretchFactor(2, 1)
        body.setSizes([380, 150, 950])
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 12, 12, 8)
        wl.addWidget(body)
        root.addWidget(wrap, 1)

        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.lbl_status = QLabel("Sẵn sàng – kéo thả thư mục ảnh hoặc file PDF vào cửa sổ để bắt đầu")
        sb.addWidget(self.lbl_status, 1)
        right = QLabel(f"{APP_NAME} v{APP_VERSION}  •  by {APP_AUTHOR}")
        sb.addPermanentWidget(right)

    def _build_header(self):
        hdr = QFrame()
        hdr.setObjectName("header")
        hdr.setFixedHeight(68)
        h = QHBoxLayout(hdr)
        h.setContentsMargins(18, 8, 14, 8)
        h.setSpacing(12)
        logo = QLabel()
        if ICON_PATH.exists():
            logo.setPixmap(QPixmap(str(ICON_PATH)).scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        h.addWidget(logo)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        tr = QHBoxLayout()
        tr.setSpacing(8)
        t = QLabel(APP_NAME)
        t.setObjectName("appTitle")
        tr.addWidget(t)
        badge = QLabel(f"v{APP_VERSION}")
        badge.setObjectName("versionBadge")
        badge.setFixedHeight(18)
        tr.addWidget(badge, 0, Qt.AlignVCenter)
        tr.addStretch(1)
        tv.addLayout(tr)
        sub = QLabel(f"by {APP_AUTHOR}  •  Trung · Nhật · Anh  →  Tiếng Việt")
        sub.setObjectName("appSub")
        tv.addWidget(sub)
        h.addLayout(tv)
        h.addStretch(1)
        self.chip_gpu = QLabel("⏳ Đang kiểm tra GPU...")
        self.chip_gpu.setObjectName("chip")
        h.addWidget(self.chip_gpu)
        self.b_update = QToolButton()
        self.b_update.setObjectName("headerBtn")
        self.b_update.setText("⟳  Cập nhật")
        self.b_update.setToolTip("Kiểm tra và cài bản mới từ GitHub")
        self.b_update.clicked.connect(self.open_update)
        h.addWidget(self.b_update)
        b_about = QToolButton()
        b_about.setObjectName("headerBtn")
        b_about.setText("ⓘ  Giới thiệu")
        b_about.clicked.connect(lambda: AboutDialog(self, self._gpu_text).exec())
        h.addWidget(b_about)
        return hdr

    def _build_sidebar(self):
        scroll = QScrollArea()
        scroll.setObjectName("sidebar")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(350)
        scroll.setMaximumWidth(460)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(12)

        # --- 1. nguồn truyện ---
        c = Card("Nguồn truyện", icon="📚")
        row = QHBoxLayout()
        row.setSpacing(8)
        b_folder = QPushButton("📁\nThư mục ảnh")
        b_folder.setObjectName("bigSource")
        b_folder.clicked.connect(self.pick_folder)
        b_pdf = QPushButton("📄\nFile PDF")
        b_pdf.setObjectName("bigSource")
        b_pdf.clicked.connect(self.pick_pdf)
        b_proj = QPushButton("🗂\nDự án cũ")
        b_proj.setObjectName("bigSource")
        b_proj.setToolTip("Mở project.json trong thư mục _work để sửa tiếp bản dịch")
        b_proj.clicked.connect(self.open_project)
        for b in (b_folder, b_pdf, b_proj):
            b.setMinimumHeight(62)
            row.addWidget(b)
        c.add(row)
        self.lbl_source = QLabel("Chưa chọn truyện – hoặc kéo thả vào cửa sổ")
        self.lbl_source.setObjectName("sourceInfo")
        self.lbl_source.setWordWrap(True)
        c.add(self.lbl_source)
        v.addWidget(c)

        # --- 2. dịch ---
        c = Card("Cài đặt dịch", icon="🌐")
        self.cb_lang = QComboBox()
        for t, d in LANGS:
            self.cb_lang.addItem(t, d)
        self.cb_engine = QComboBox()
        self.cb_lang.currentIndexChanged.connect(self._fill_engines)
        self.cb_device = QComboBox()
        for t, d in DEVICES:
            self.cb_device.addItem(t, d)
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        g.addWidget(field("Ngôn ngữ gốc", self.cb_lang), 0, 0)
        g.addWidget(field("Thiết bị", self.cb_device), 0, 1)
        g.addWidget(field("Bộ dịch", self.cb_engine), 1, 0, 1, 2)
        c.add(g)
        self.chk_fallback = QCheckBox("Câu bỏ trống → GTX dịch bù (cần mạng)")
        self.chk_fallback.setChecked(True)
        c.add(self.chk_fallback)
        v.addWidget(c)

        # --- 3. chữ ---
        c = Card("Hiển thị chữ", icon="🔤")
        self.ed_font = QLineEdit()
        self.ed_font.setPlaceholderText("Font hỗ trợ tiếng Việt (.ttf)")
        b_font = QPushButton("Chọn")
        b_font.clicked.connect(self.pick_font)
        fr = QHBoxLayout()
        fr.setSpacing(6)
        fr.addWidget(self.ed_font, 1)
        fr.addWidget(b_font)
        c.add(field("Font chữ", fr))
        self.sl_scale = QSlider(Qt.Horizontal)
        self.sl_scale.setRange(30, 120)
        self.sl_scale.setSingleStep(5)
        self.sl_scale.setPageStep(10)
        self.sl_scale.setValue(70)
        self.lbl_scale = QLabel("70%")
        self.lbl_scale.setFixedWidth(42)
        self.lbl_scale.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.sl_scale.valueChanged.connect(lambda val: self.lbl_scale.setText(f"{val}%"))
        sr = QHBoxLayout()
        sr.addWidget(self.sl_scale, 1)
        sr.addWidget(self.lbl_scale)
        box = field("Cỡ chữ tối đa (so với chữ gốc)", sr)
        box.setToolTip("Chữ Việt luôn tự thu nhỏ để nằm gọn trong bóng thoại.\n"
                       "Đổi xong bấm 'Vẽ lại tất cả' – không cần dịch lại.")
        c.add(box)
        self.chk_upper = QCheckBox("Chữ IN HOA (kiểu truyện tranh)")
        c.add(self.chk_upper)
        v.addWidget(c)

        # --- 4. xuất ---
        c = Card("Xuất kết quả", icon="💾")
        self.ed_out = QLineEdit()
        self.ed_out.setPlaceholderText("Thư mục lưu trang đã dịch")
        b_out = QPushButton("Chọn")
        b_out.clicked.connect(self.pick_out)
        orow = QHBoxLayout()
        orow.setSpacing(6)
        orow.addWidget(self.ed_out, 1)
        orow.addWidget(b_out)
        c.add(field("Thư mục kết quả", orow))
        self.cb_fmt = QComboBox()
        self.cb_fmt.addItems(["jpg", "png"])
        self.sp_dpi = QSpinBox()
        self.sp_dpi.setRange(100, 400)
        self.sp_dpi.setSingleStep(25)
        self.sp_dpi.setSuffix(" DPI")
        self.sp_dpi.setValue(200)
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.addWidget(field("Định dạng ảnh", self.cb_fmt), 0, 0)
        g.addWidget(field("Tách PDF", self.sp_dpi), 0, 1)
        c.add(g)
        self.chk_pdf = QCheckBox("Gộp các trang thành 1 file PDF")
        self.chk_pdf.setChecked(True)
        c.add(self.chk_pdf)
        v.addWidget(c)

        # --- 5. chạy + tiến độ ---
        c = Card("Tiến độ", icon="🚀")
        pr = QHBoxLayout()
        self.lbl_pct = QLabel("0%")
        self.lbl_pct.setObjectName("bigPercent")
        pr.addWidget(self.lbl_pct)
        pr.addStretch(1)
        self.lbl_eta = QLabel("")
        self.lbl_eta.setObjectName("progressText")
        self.lbl_eta.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        pr.addWidget(self.lbl_eta)
        c.add(pr)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        c.add(self.progress)
        self.lbl_progress = QLabel("Sẵn sàng")
        self.lbl_progress.setObjectName("progressText")
        self.lbl_progress.setWordWrap(True)
        c.add(self.lbl_progress)
        self.b_start = QPushButton("▶   BẮT ĐẦU DỊCH")
        self.b_start.setObjectName("primary")
        self.b_start.setCursor(Qt.PointingHandCursor)
        self.b_start.clicked.connect(self.start)
        c.add(self.b_start)
        row = QHBoxLayout()
        self.b_stop = QPushButton("■  Dừng")
        self.b_stop.setObjectName("danger")
        self.b_stop.setEnabled(False)
        self.b_stop.clicked.connect(self.stop)
        b_open_out = QPushButton("📂  Mở kết quả")
        b_open_out.clicked.connect(self.open_out)
        row.addWidget(self.b_stop)
        row.addWidget(b_open_out)
        c.add(row)
        v.addWidget(c)
        v.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    def _build_pages(self):
        box = QWidget()
        box.setMinimumWidth(130)
        box.setMaximumWidth(220)
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.lbl_pages = QLabel("TRANG")
        self.lbl_pages.setObjectName("viewCaption")
        v.addWidget(self.lbl_pages)
        self.page_list = QListWidget()
        self.page_list.setObjectName("pageList")
        self.page_list.setIconSize(thumb_size())
        self.page_list.setSpacing(1)
        self.page_list.currentRowChanged.connect(self.show_page)
        v.addWidget(self.page_list, 1)
        return box

    def _build_workspace(self):
        self.tabs = QTabWidget()
        # --- tab xem & sửa ---
        view = QWidget()
        vv = QVBoxLayout(view)
        vv.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        self.compare = CompareView()
        split.addWidget(self.compare)
        edit = QWidget()
        ev = QVBoxLayout(edit)
        ev.setContentsMargins(8, 0, 8, 8)
        ev.setSpacing(8)
        cap = QLabel("BẢN DỊCH CỦA TRANG – bấm đúp vào ô để sửa")
        cap.setObjectName("viewCaption")
        ev.addWidget(cap)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["#", "Chữ gốc (OCR)", "Bản dịch"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        ev.addWidget(self.table, 1)
        row = QHBoxLayout()
        b_apply = QPushButton("💾  Lưu bản sửa && vẽ lại trang")
        b_apply.clicked.connect(self.apply_edits)
        b_redraw_all = QPushButton("🎨  Vẽ lại tất cả (font / cỡ chữ / in hoa)")
        b_redraw_all.clicked.connect(self.redraw_all)
        row.addWidget(b_apply)
        row.addWidget(b_redraw_all)
        row.addStretch(1)
        ev.addLayout(row)
        split.addWidget(edit)
        split.setSizes([620, 250])
        vv.addWidget(split)
        self.tabs.addTab(view, "🖼  Xem && sửa")
        # --- tab nhật ký ---
        logw = QWidget()
        lv = QVBoxLayout(logw)
        lv.setContentsMargins(8, 8, 8, 8)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(5000)
        lv.addWidget(self.log_box)
        self.tabs.addTab(logw, "📜  Nhật ký")
        return self.tabs

    def log(self, msg):
        self.log_box.appendPlainText(msg)
        if msg.startswith("LỖI") or msg.startswith("! "):
            self.tabs.setTabText(1, "📜  Nhật ký  ⚠")

    # ---------------- GPU & cập nhật ----------------
    def _on_gpu(self, has, info):
        self._gpu_text = ("GPU " if has else "") + info
        if has:
            name = info.split(" (")[0]
            self.chip_gpu.setText(f"⚡ GPU: {name}")
            self.chip_gpu.setProperty("state", "ok")
            self.lbl_status.setText(f"GPU sẵn sàng: {info}")
        else:
            self.chip_gpu.setText("🖥 CPU")
            self.chip_gpu.setProperty("state", "warn")
            self.lbl_status.setText(f"⚠ {info}")
        self.chip_gpu.setToolTip(info)
        self.chip_gpu.style().unpolish(self.chip_gpu)
        self.chip_gpu.style().polish(self.chip_gpu)

    def _auto_check_update(self):
        self.checker = UpdateChecker()
        self.checker.result.connect(self._on_update_checked)
        self.checker.start()

    def _on_update_checked(self, info, err):
        if info and info.get("newer"):
            self.update_info = info
            self.b_update.setText(f"⬆  Có bản mới {info['tag']}")
            self.b_update.setProperty("update", True)
            self.b_update.style().unpolish(self.b_update)
            self.b_update.style().polish(self.b_update)
            self.lbl_status.setText(f"🎉 Đã có bản mới {info['tag']} – bấm 'Có bản mới' ở góc trên để cập nhật")

    def open_update(self):
        if self._busy():
            return
        UpdateDialog(self, self.update_info).exec()

    # ---------------- cài đặt ----------------
    def _load_settings(self):
        s = self.settings
        self._set_combo(self.cb_lang, s.value("lang", "zh"))
        self._set_combo(self.cb_device, s.value("device", "auto"))
        self._fill_engines()
        self.chk_fallback.setChecked(str(s.value("gtx_fallback", "true")) == "true")
        font = s.value("font", "") or ""
        self.ed_font.setText(font if font and Path(font).exists() else find_default_font())
        self.chk_upper.setChecked(str(s.value("upper", "false")) == "true")
        try:
            self.sl_scale.setValue(int(s.value("font_scale", 70)))
        except (TypeError, ValueError):
            self.sl_scale.setValue(70)
        try:
            self.sp_dpi.setValue(int(s.value("dpi", 200)))
        except (TypeError, ValueError):
            self.sp_dpi.setValue(200)
        self.cb_fmt.setCurrentText(s.value("fmt", "jpg"))
        self.chk_pdf.setChecked(str(s.value("pdf", "true")) == "true")

    def _save_settings(self):
        s = self.settings
        s.setValue("lang", self.cb_lang.currentData())
        s.setValue("device", self.cb_device.currentData())
        s.setValue(f"engine_{self.cb_lang.currentData()}", self.cb_engine.currentData())
        s.setValue("gtx_fallback", "true" if self.chk_fallback.isChecked() else "false")
        s.setValue("font", self.ed_font.text())
        s.setValue("upper", "true" if self.chk_upper.isChecked() else "false")
        s.setValue("font_scale", self.sl_scale.value())
        s.setValue("dpi", self.sp_dpi.value())
        s.setValue("fmt", self.cb_fmt.currentText())
        s.setValue("pdf", "true" if self.chk_pdf.isChecked() else "false")

    def _fill_engines(self):
        lang = self.cb_lang.currentData() or "zh"
        self.cb_engine.blockSignals(True)
        self.cb_engine.clear()
        for t, d in ENGINES[lang]:
            self.cb_engine.addItem(t, d)
        self._set_combo(self.cb_engine, self.settings.value(f"engine_{lang}", default_engine(lang)))
        self.cb_engine.blockSignals(False)

    @staticmethod
    def _set_combo(cb, data):
        i = cb.findData(data)
        if i >= 0:
            cb.setCurrentIndex(i)

    def _config(self) -> Config:
        return Config(
            src_lang=self.cb_lang.currentData(),
            device=self.cb_device.currentData(),
            engine=self.cb_engine.currentData() or default_engine(self.cb_lang.currentData()),
            gtx_fallback=self.chk_fallback.isChecked(),
            font_path=self.ed_font.text().strip(),
            uppercase=self.chk_upper.isChecked(),
            font_scale=self.sl_scale.value(),
            pdf_dpi=self.sp_dpi.value(),
            img_format=self.cb_fmt.currentText(),
            export_pdf=self.chk_pdf.isChecked(),
            out_dir=self.ed_out.text().strip(),
        )

    def _busy(self) -> bool:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Đang dịch", "Hãy đợi dịch xong (hoặc bấm Dừng) rồi thao tác.")
            return True
        return False

    # ---------------- chọn nguồn ----------------
    def _last_dir(self):
        d = self.settings.value("last_dir", "")
        return d if d and Path(d).exists() else str(Path.home())

    def pick_folder(self):
        if self._busy():
            return
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục ảnh truyện", self._last_dir())
        if d:
            self.load_folder(d)

    def load_folder(self, d):
        pages = list_images(d)
        if not pages:
            QMessageBox.warning(self, "Không có ảnh", "Thư mục không có ảnh jpg/png/webp/bmp nào.")
            return
        self.settings.setValue("last_dir", str(Path(d).parent))
        self._set_source("folder", d, pages)
        self._set_source_label(f"📁  <b>{Path(d).name}</b><br>{len(pages)} trang ảnh")
        self.ed_out.setText(str(Path(d).parent / (Path(d).name + "_VI")))

    def pick_pdf(self):
        if self._busy():
            return
        f, _ = QFileDialog.getOpenFileName(self, "Chọn file PDF truyện", self._last_dir(), "PDF (*.pdf)")
        if f:
            self.load_pdf(f)

    def load_pdf(self, f):
        self.settings.setValue("last_dir", str(Path(f).parent))
        try:
            n = pdf_page_count(f)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Lỗi PDF", f"Không mở được PDF:\n{e}")
            return
        self._set_source("pdf", f, [])
        self._set_source_label(f"📄  <b>{Path(f).name}</b><br>{n} trang PDF")
        self.ed_out.setText(str(Path(f).parent / (Path(f).stem + "_VI")))

    def _set_source_label(self, html):
        self.lbl_source.setText(html)
        self.lbl_source.setProperty("filled", True)
        self.lbl_source.style().unpolish(self.lbl_source)
        self.lbl_source.style().polish(self.lbl_source)

    def _set_source(self, kind, path, pages):
        self.source_type, self.source_path = kind, path
        self.src_pages, self.done_pages = pages, {}
        self.project, self.project_path = None, None
        self._fill_page_list()

    # kéo thả thư mục / PDF / ảnh vào cửa sổ
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        if self.worker and self.worker.isRunning():
            return
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not urls:
            return
        p = Path(urls[0])
        if p.is_dir():
            self.load_folder(str(p))
        elif p.suffix.lower() == ".pdf":
            self.load_pdf(str(p))
        elif p.suffix.lower() in IMG_EXT:
            self.load_folder(str(p.parent))
        elif p.name == "project.json":
            self._open_project_file(str(p))

    # ---------------- danh sách trang + ảnh thu nhỏ ----------------
    def _fill_page_list(self):
        self.page_list.blockSignals(True)
        self.page_list.clear()
        blank = QPixmap(thumb_size())
        blank.fill(Qt.transparent)
        for i in range(len(self.src_pages)):
            it = QListWidgetItem(QIcon(blank), self._page_label(i))
            it.setSizeHint(QSize(120, thumb_size().height() + 12))
            self.page_list.addItem(it)
        self.page_list.blockSignals(False)
        self.lbl_pages.setText(f"TRANG ({len(self.src_pages)})" if self.src_pages else "TRANG")
        self._thumb_queue = list(range(len(self.src_pages)))
        if self._thumb_queue:
            self._thumb_timer.start(15)
        if self.src_pages:
            self.page_list.setCurrentRow(0)
            self.show_page(0)
        else:
            self.compare.set_images(None, None)
            self.table.setRowCount(0)

    def _page_label(self, i):
        return f"Trang {i + 1}\n{'✓ đã dịch' if i in self.done_pages else '—'}"

    def _load_thumbs(self):
        """Tạo ảnh thu nhỏ dần dần (không làm đơ giao diện khi truyện có hàng trăm trang)."""
        for _ in range(4):
            if not self._thumb_queue:
                self._thumb_timer.stop()
                return
            i = self._thumb_queue.pop(0)
            item = self.page_list.item(i)
            if item is None or i >= len(self.src_pages):
                continue
            path = (self.done_pages.get(i) or {}).get("out") or self.src_pages[i]
            pix = QPixmap(str(path)) if path and Path(path).exists() else QPixmap()
            if not pix.isNull():
                ts = thumb_size()
                pix = pix.scaled(ts.width(), ts.height() * 3, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pix = pix.copy(0, 0, pix.width(), min(pix.height(), ts.height()))
                item.setIcon(QIcon(pix))

    def _refresh_item(self, i):
        item = self.page_list.item(i)
        if item:
            item.setText(self._page_label(i))
            self._thumb_queue.append(i)
            if not self._thumb_timer.isActive():
                self._thumb_timer.start(15)

    def pick_font(self):
        start = str(Path(self.ed_font.text()).parent) if self.ed_font.text() else r"C:\Windows\Fonts"
        f, _ = QFileDialog.getOpenFileName(self, "Chọn font hỗ trợ tiếng Việt", start, "Font (*.ttf *.otf *.ttc)")
        if f:
            self.ed_font.setText(f)

    def pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục kết quả", self.ed_out.text() or self._last_dir())
        if d:
            self.ed_out.setText(d)

    # ---------------- chạy ----------------
    def start(self):
        if self._busy():
            return
        if not self.source_path:
            QMessageBox.information(self, "Chưa chọn truyện", "Hãy chọn thư mục ảnh hoặc file PDF trước "
                                    "(hoặc kéo thả vào cửa sổ).")
            return
        cfg = self._config()
        if not cfg.out_dir:
            QMessageBox.information(self, "Thiếu thư mục", "Hãy chọn thư mục kết quả.")
            return
        if self.source_type == "folder" and Path(cfg.out_dir).resolve() == Path(self.source_path).resolve():
            QMessageBox.warning(self, "Thư mục kết quả",
                                "Thư mục kết quả phải khác thư mục ảnh gốc (tránh ghi đè ảnh gốc).")
            return
        if cfg.font_path and not Path(cfg.font_path).exists():
            QMessageBox.warning(self, "Font", "Không tìm thấy file font đã chọn.")
            return
        self._save_settings()
        self.done_pages = {}
        self._fill_page_list()
        self.project, self.project_path = None, None
        self.progress.setRange(0, 0)  # chạy vòng (đang tải model)
        self.lbl_pct.setText("…")
        self.lbl_eta.setText("")
        self.lbl_progress.setText("Đang khởi động...")
        self._t_start = None
        self.log_box.clear()
        self.tabs.setTabText(1, "📜  Nhật ký")
        self.worker = Worker(cfg, self.source_type, self.source_path)
        self.worker.log.connect(self.log)
        self.worker.progress.connect(self._on_progress)
        self.worker.stage.connect(self._on_stage)
        self.worker.pages_ready.connect(self._on_pages_ready)
        self.worker.page_done.connect(self._on_page_done)
        self.worker.finished_ok.connect(self._on_finished)
        self.b_start.setEnabled(False)
        self.b_start.setText("⏳   ĐANG DỊCH...")
        self.b_stop.setEnabled(True)
        self.worker.start()

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop_event.set()
            self.b_stop.setEnabled(False)
            self.log("Đang dừng sau trang hiện tại...")
            self.lbl_progress.setText("Đang dừng...")

    def _on_stage(self, text):
        self.lbl_progress.setText(text)
        if text.startswith("Đang dịch"):
            self._t_start = time.time()
            n = max(1, len(self.src_pages))
            self.progress.setRange(0, n)
            self.progress.setValue(0)
            self.lbl_pct.setText("0%")
            self.lbl_progress.setText(f"Đang dịch... 0/{len(self.src_pages)} trang")

    @staticmethod
    def _fmt_time(sec):
        sec = int(max(0, sec))
        return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"

    def _on_progress(self, i, n):
        self.progress.setRange(0, max(1, n))
        self.progress.setValue(i)
        pct = 100 * i / max(1, n)
        self.lbl_pct.setText(f"{pct:.0f}%")
        el = time.time() - (self._t_start or time.time())
        txt = f"Trang {i}/{n}"
        if i > 0:
            per = el / i
            txt += f"  •  {per:.1f}s/trang  •  đã chạy {self._fmt_time(el)}"
            self.lbl_eta.setText(f"còn ~{self._fmt_time(per * (n - i))}")
        self.lbl_progress.setText(txt)
        self.setWindowTitle(f"[{pct:.0f}%] {self.base_title}")

    def _on_pages_ready(self, pages):
        self.src_pages = list(pages)
        self._fill_page_list()

    def _on_page_done(self, i, page):
        self.done_pages[i] = page
        self._refresh_item(i)
        if self.page_list.currentRow() == i:
            self.show_page(i)

    def _on_finished(self, ok, project_path):
        self.b_start.setEnabled(True)
        self.b_start.setText("▶   BẮT ĐẦU DỊCH")
        self.b_stop.setEnabled(False)
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
        self.setWindowTitle(self.base_title)
        el = time.time() - self._t_start if self._t_start else 0
        if ok:
            self.lbl_pct.setText("100%")
            self.lbl_eta.setText("")
        self.lbl_progress.setText(("✅ Hoàn tất" if ok else "Đã dừng / có lỗi – xem tab Nhật ký")
                                  + (f"  •  {self._fmt_time(el)}" if el else ""))
        if project_path and Path(project_path).exists():
            self.project_path = project_path
            try:
                self.project = load_project(project_path)
                for p in self.project["pages"]:
                    self.done_pages[p["index"]] = p
            except Exception as e:  # noqa: BLE001
                self.log(f"! Không đọc được project.json: {e}")
        if ok and self.done_pages:
            self.lbl_status.setText(f"✅ Hoàn tất {len(self.done_pages)} trang → {self.ed_out.text()}")
        elif not ok:
            self.tabs.setCurrentIndex(1) if "LỖI" in self.log_box.toPlainText()[-4000:] else None

    # ---------------- xem & sửa ----------------
    def show_page(self, i):
        if i < 0:
            return
        page = self.done_pages.get(i)
        src = page["src"] if page else (self.src_pages[i] if i < len(self.src_pages) else None)
        self.compare.set_images(src, page["out"] if page else None)
        self.table.setRowCount(0)
        if not page:
            return
        for k, b in enumerate(page["blocks"]):
            self.table.insertRow(k)
            num = QTableWidgetItem(str(k + 1))
            num.setFlags(num.flags() & ~Qt.ItemIsEditable)
            num.setTextAlignment(Qt.AlignCenter)
            orig = QTableWidgetItem(b["text"])
            orig.setFlags(orig.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(k, 0, num)
            self.table.setItem(k, 1, orig)
            self.table.setItem(k, 2, QTableWidgetItem(b["translation"]))
        self.table.resizeRowsToContents()

    def _project_page(self, i):
        if not self.project:
            return None
        for p in self.project["pages"]:
            if p["index"] == i:
                return p
        return None

    def apply_edits(self):
        if self._busy():
            return
        i = self.page_list.currentRow()
        page = self._project_page(i)
        if not page:
            QMessageBox.information(self, "Chưa có bản dịch", "Trang này chưa được dịch.")
            return
        self.table.setCurrentCell(-1, -1)  # chốt ô đang gõ dở
        for k, b in enumerate(page["blocks"]):
            item = self.table.item(k, 2)
            if item is not None:
                b["translation"] = item.text()
        if self._redraw([page]):
            self.lbl_status.setText(f"Đã vẽ lại trang {i + 1}.")

    def redraw_all(self):
        if self._busy() or not self.project:
            return
        if self._redraw(self.project["pages"]):
            self.lbl_status.setText(f"Đã vẽ lại {len(self.project['pages'])} trang.")

    def _redraw(self, pages) -> bool:
        self._save_settings()
        font, upper, scale = self.ed_font.text().strip(), self.chk_upper.isChecked(), self.sl_scale.value()
        ok = True
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for p in pages:
                rerender_page(p, font, upper, scale)
                self.done_pages[p["index"]] = p
                self._refresh_item(p["index"])
            self.project["config"]["font_path"] = font
            self.project["config"]["uppercase"] = upper
            self.project["config"]["font_scale"] = scale
            save_project(self.project, self.project_path)
            out_dir = Path(self.project_path).parent.parent
            write_text_export(self.project, out_dir / "ban_dich.txt")
            if self.project["config"].get("export_pdf"):
                export_pdf([p["out"] for p in self.project["pages"]],
                           out_dir / f"{self.project.get('source', 'truyen')}_vi.pdf")
        except Exception:  # noqa: BLE001
            ok = False
            self.log("LỖI:\n" + traceback.format_exc())
        finally:
            QApplication.restoreOverrideCursor()
        self.show_page(self.page_list.currentRow())
        return ok

    def open_project(self):
        if self._busy():
            return
        f, _ = QFileDialog.getOpenFileName(self, "Mở dự án (project.json trong thư mục _work)",
                                           self._last_dir(), "Dự án (project.json)")
        if f:
            self._open_project_file(f)

    def _open_project_file(self, f):
        try:
            proj = load_project(f)
            pages = proj["pages"]
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Lỗi", f"Không đọc được dự án:\n{e}")
            return
        self.project, self.project_path = proj, f
        n = max((p["index"] for p in pages), default=-1) + 1
        self.src_pages = [""] * n
        self.done_pages = {}
        for p in pages:
            self.src_pages[p["index"]] = p.get("src", "")
            self.done_pages[p["index"]] = p
        cfg = Config.from_dict(proj.get("config"))
        self._set_combo(self.cb_lang, cfg.src_lang)
        self._set_combo(self.cb_engine, cfg.engine)
        if cfg.font_path and Path(cfg.font_path).exists():
            self.ed_font.setText(cfg.font_path)
        self.chk_upper.setChecked(cfg.uppercase)
        self.sl_scale.setValue(int(cfg.font_scale))
        self.chk_pdf.setChecked(cfg.export_pdf)
        self.ed_out.setText(str(Path(f).parent.parent))
        self.source_type, self.source_path = None, None
        self._set_source_label(f"🗂  <b>Dự án: {proj.get('source', '')}</b><br>{len(self.done_pages)} trang đã dịch")
        self._fill_page_list()

    def open_out(self):
        d = self.ed_out.text().strip()
        if d and Path(d).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))
        else:
            QMessageBox.information(self, "Chưa có", "Thư mục kết quả chưa được tạo.")

    def closeEvent(self, e):
        self._save_settings()
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self, "Đang dịch", "Đang dịch dở. Thoát luôn?") != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.stop_event.set()
            if not self.worker.wait(8000):
                os._exit(0)  # luồng đang tải model / gọi mạng -> thoát cứng cho khỏi treo
        for th in (self.probe, self.checker):
            if th is not None and th.isRunning():
                th.wait(3000)
        super().closeEvent(e)


def _excepthook(etype, value, tb):
    """Lỗi không bắt được -> ghi app_log.txt và báo lên màn hình (bản portable không có console)."""
    msg = "".join(traceback.format_exception(etype, value, tb))
    try:
        with open(APP_DIR / "app_log.txt", "a", encoding="utf-8") as f:
            f.write(time.strftime("\n[%Y-%m-%d %H:%M:%S]\n") + msg)
    except OSError:
        pass
    if QApplication.instance():
        QMessageBox.critical(None, "Lỗi", msg[-2000:])


def _screenshot(win, path, demo):
    """Chế độ kiểm tra (dùng cho build tự động): mở cửa sổ, chụp ảnh, thoát."""
    if demo:
        win.load_folder(demo)
        win.lbl_pct.setText("42%")
        win.lbl_eta.setText("còn ~1:05")
        win.progress.setRange(0, 100)
        win.progress.setValue(42)
        win.lbl_progress.setText("Trang 5/12  •  1.4s/trang  •  đã chạy 0:07")
        outs = sorted(Path(demo).parent.glob("demo_out/*.png"))
        for i, o in enumerate(outs[:len(win.src_pages)]):
            win.done_pages[i] = {"index": i, "src": win.src_pages[i], "out": str(o), "blocks": [
                {"text": "他必须得抓紧时间了。", "translation": "Hắn phải tranh thủ thời gian rồi."},
                {"text": "你说什么?", "translation": "Ngươi vừa nói cái gì vậy hả?"}]}
            win._refresh_item(i)
        win.show_page(0)

    def grab():
        QApplication.processEvents()
        win.grab().save(path)
        print("SCREENSHOT_OK", path, flush=True)
        QApplication.instance().quit()
    QTimer.singleShot(2500, grab)


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--screenshot")
    ap.add_argument("--demo")
    args, _ = ap.parse_known_args()
    sys.excepthook = _excepthook
    if sys.platform == "win32":
        try:  # để Windows hiện đúng icon app trên thanh taskbar
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DuyAnh.DichTruyenTranh.2")
        except Exception:  # noqa: BLE001
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Dịch Truyện Tranh")
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    w = MainWindow(check_update=not args.screenshot)
    w.show()
    if args.screenshot:
        _screenshot(w, args.screenshot, args.demo)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
