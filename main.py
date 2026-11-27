"""Dịch Truyện Tranh v2.2 by Duy Anh – dịch truyện tranh Trung / Nhật / Hàn / Anh sang tiếng Việt.

Nguồn: thư mục ảnh (đánh số trang), file PDF, truyện nén CBZ/ZIP, hoặc cả hàng đợi nhiều chương
(kéo thả vào cửa sổ cũng được).
Dịch: model chạy trên máy (HachimiMT cho tiếng Trung, NLLB-200 cho tiếng Nhật) trên GPU,
AI (LLM: Ollama / LM Studio / DeepSeek / Gemini / OpenAI / Claude) dịch cả chương theo ngữ cảnh,
hoặc GTX Google Translate (miễn phí, online). OCR + xoá chữ (LaMa) chạy trên GPU NVIDIA nếu máy có.
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
from PySide6.QtGui import (QColor, QDesktopServices, QFontDatabase, QIcon, QKeySequence, QPixmap,  # noqa: E402
                           QShortcut)
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QMenu,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from core.loader import ARCHIVE_EXT, IMG_EXT, archive_images, export_pdf, list_images, pdf_page_count  # noqa: E402,F401
from core.pipeline import (Config, Pipeline, default_engine, gpu_info, load_project,  # noqa: E402
                           rerender_page, save_project, write_text_export)
from core.fonts import list_fonts, vi_missing  # noqa: E402
from core import ollama as OL  # noqa: E402
from core.llm import PROVIDERS, LLMClient, friendly_error  # noqa: E402
from core.store import JsonSettings  # noqa: E402
from core.typeset import KIND_VI, find_default_font  # noqa: E402
from ui.dialogs import AboutDialog, UpdateChecker, UpdateDialog  # noqa: E402
from ui.glossary import GlossaryDialog  # noqa: E402
from ui.tools import (STYLE_PRESETS, FindReplaceDialog, LogoDialog, PronounDialog,  # noqa: E402
                      ShortcutsDialog, WebtoonDialog)
from ui.theme import QSS  # noqa: E402
from ui.widgets import Card, CompareView, field, thumb_size  # noqa: E402

LANGS = [("🇨🇳  Tiếng Trung (giản thể)", "zh"), ("🇹🇼  Tiếng Trung (phồn thể)", "zh_tw"),
         ("🇯🇵  Tiếng Nhật", "ja"), ("🇰🇷  Tiếng Hàn (manhwa)", "ko"), ("🇬🇧  Tiếng Anh", "en")]
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
    "ko": [
        ("NLLB-200 600M (Meta) – chạy trên máy, khuyên dùng", "local:facebook/nllb-200-distilled-600M"),
        ("GTX Google – online, miễn phí", "gtx"),
    ],
}
ENGINES["zh_tw"] = ENGINES["zh"]
ENGINES["en"] = [("GTX Google – online, miễn phí", "gtx")]
LLM_ITEM = ("🤖 AI (LLM) – dịch cả chương theo ngữ cảnh", "llm")
for _k in ENGINES:
    ENGINES[_k] = ENGINES[_k] + [LLM_ITEM]
TAB_VIEW, TAB_STATUS, TAB_LOG = 0, 1, 2
DEVICES = [("⚡ Tự động – ưu tiên GPU", "auto"), ("Chỉ GPU (CUDA)", "cuda"), ("Chỉ CPU", "cpu")]
RUN_MODES = [("🌐 Dịch + lồng chữ", "translate"), ("🧽 Chỉ xoá chữ (RAW sạch)", "clean")]
READINGS = [("Tự động (Nhật: phải → trái)", "auto"), ("Phải → trái (manga)", "rtl"),
            ("Trái → phải (manhwa, comic)", "ltr")]
SRC_FILTER = "Truyện (*.pdf *.cbz *.zip);;PDF (*.pdf);;Truyện nén (*.cbz *.zip)"


# =====================================================================
#  Luồng nền
# =====================================================================
class Worker(QThread):
    log = Signal(str)
    progress = Signal(int, int, str)
    pages_ready = Signal(list)
    page_done = Signal(int, object)
    finished_ok = Signal(bool, str)
    stage = Signal(str)
    chapter = Signal(int, int, str)   # chương thứ k / tổng, tên (hàng đợi nhiều chương)

    def __init__(self, cfg: Config, source_type: str = "", source_path: str = "", api_key: str = "",
                 project=None, project_path: str = "", jobs=None):
        super().__init__()
        self.cfg, self.source_type, self.source_path = cfg, source_type, source_path
        self.jobs = jobs or [(source_type, source_path, cfg.out_dir)]
        self.api_key = api_key
        self.project, self.project_path = project, project_path  # có project -> chế độ Dịch lại
        self.stop_event = threading.Event()

    def _prog(self, d, n, text=""):
        self.progress.emit(int(d), int(n), text or "")

    def run(self):
        project_path = self.project_path
        try:
            pipe = Pipeline(self.cfg, log=self.log.emit, stop_event=self.stop_event, api_key=self.api_key)
            if self.project is not None:  # dịch lại dự án đã có – không đọc chữ / xoá chữ lại
                self.cfg.run_mode = "translate"
                pipe = Pipeline(self.cfg, log=self.log.emit, stop_event=self.stop_event, api_key=self.api_key)
                pipe.project_path = self.project_path
                pipe.source_name = self.project.get("source", "truyen")
                self.stage.emit("Đang tải bộ dịch...")
                pipe.load_models(need_ocr=False, need_clean=False)
                self.stage.emit("Đang dịch...")
                ok = pipe.retranslate(self.project, progress=self._prog, page_done=self.page_done.emit)
                self.finished_ok.emit(ok, project_path)
                return
            ok_all = True
            n = len(self.jobs)
            for k, (kind, path, out_dir) in enumerate(self.jobs):
                if self.stop_event.is_set():
                    ok_all = False
                    break
                cfg = Config.from_dict({**self.cfg.__dict__, "out_dir": out_dir})
                pipe = Pipeline(cfg, log=self.log.emit, stop_event=self.stop_event, api_key=self.api_key)
                project_path = pipe.project_path
                if n > 1:
                    self.chapter.emit(k + 1, n, Path(path).name)
                    self.log.emit(f"\n========== Chương {k + 1}/{n}: {Path(path).name} ==========")
                self.stage.emit("Đang chuẩn bị trang...")
                pages = pipe.prepare_pages(kind, path)
                self.pages_ready.emit(pages)
                if self.stop_event.is_set():
                    ok_all = False
                    break
                self.stage.emit("Đang tải model (lần đầu có thể mất vài phút)...")
                pipe.load_models()
                self.stage.emit("Đang dịch...")
                ok = pipe.run(pages, progress=self._prog, page_done=self.page_done.emit)
                ok_all = ok_all and ok
            self.finished_ok.emit(ok_all, project_path)
        except Exception:  # noqa: BLE001
            self.log.emit("LỖI:\n" + traceback.format_exc())
            self.finished_ok.emit(False, project_path)


class OllamaAuto(QThread):
    """Tự kết nối Ollama: mở nếu chưa chạy, liệt kê model đã cài, chọn model hợp nhất."""
    done = Signal(object)

    def __init__(self, url, model):
        super().__init__()
        self.url, self.model = url, model

    def run(self):
        try:
            self.done.emit(OL.auto_connect(self.url, self.model, log=lambda m: None))
        except Exception as e:  # noqa: BLE001
            self.done.emit({"ok": False, "models": [], "model": "", "message": friendly_error(e)})


class OllamaPull(QThread):
    """Tải model về Ollama, báo % tiến độ."""
    progress = Signal(float, str)   # -1 = chưa biết %
    done = Signal(bool, str)

    def __init__(self, url, model):
        super().__init__()
        self.url, self.model = url, model
        self.stop_event = threading.Event()

    def run(self):
        try:
            if not OL.start_server(self.url, log=lambda m: None):
                raise RuntimeError("Không mở được Ollama – hãy cài / mở Ollama trước")
            OL.pull(self.url, self.model, lambda pct, txt: self.progress.emit(-1.0 if pct is None else pct, txt),
                    self.stop_event, log=lambda msg: self.progress.emit(-1.0, msg))
            self.done.emit(True, f"✅ Đã tải xong {self.model}")
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, f"❌ Tải {self.model} lỗi: {friendly_error(e)}")


class LlmProbe(QThread):
    """Thử kết nối AI / lấy danh sách model (chạy nền)."""
    done = Signal(bool, object, str)   # ok, danh sách model, thông báo

    def __init__(self, provider, url, model, key, chat_test=False):
        super().__init__()
        self.args = (provider, url, model, key)
        self.chat_test = chat_test

    def run(self):
        try:
            c = LLMClient(*self.args, timeout=120)
            models = []
            try:
                models = c.list_models()
            except Exception:  # noqa: BLE001  (vài máy chủ không có /models)
                if not self.chat_test:
                    raise
            msg = f"Kết nối được – {len(models)} model" if models else "Kết nối được"
            if self.chat_test:
                t0 = time.time()
                rep = c.chat("Bạn là dịch giả.", "Dịch sang tiếng Việt, chỉ trả lời bản dịch: 你好，朋友")
                rep = rep.split("</think>")[-1].strip()
                msg = f"✅ AI trả lời sau {time.time() - t0:.1f}s: “{rep[:60]}”"
            self.done.emit(True, models, msg)
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, [], "❌ " + friendly_error(e))


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
        # cài đặt ở config.json (sửa tay được); lần đầu tự nhập cài đặt cũ từ registry
        self.settings = JsonSettings(legacy=QSettings("DuyAnh", "DichTruyenTranh"))
        self.llm_probe = None
        self.ollama_auto = None
        self.ollama_pull = None
        self._ollama_connected = False
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
        self.queue = []
        self._build_ui()
        self._load_settings()
        self._setup_shortcuts()
        QTimer.singleShot(400, self._maybe_auto_ollama)  # đang chọn AI + Ollama -> tự kết nối luôn
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
        body.setSizes([410, 180, 900])
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
        sub = QLabel(f"by {APP_AUTHOR}  •  Trung · Nhật · Hàn · Anh  →  Tiếng Việt")
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
        scroll.setMinimumWidth(390)
        scroll.setMaximumWidth(480)
        inner = QWidget()
        inner.setMinimumWidth(0)
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 10, 0)
        v.setSpacing(12)

        # --- 1. nguồn truyện ---
        c = Card("Nguồn truyện", icon="📚")
        row = QGridLayout()
        row.setHorizontalSpacing(8)
        row.setVerticalSpacing(8)
        b_folder = QPushButton("📁  Thư mục ảnh")
        b_folder.setObjectName("bigSource")
        b_folder.clicked.connect(self.pick_folder)
        b_pdf = QPushButton("📄  PDF / CBZ")
        b_pdf.setObjectName("bigSource")
        b_pdf.setToolTip("File PDF, truyện nén .cbz / .zip")
        b_pdf.clicked.connect(self.pick_pdf)
        b_multi = QPushButton("📚  Nhiều chương")
        b_multi.setObjectName("bigSource")
        b_multi.setToolTip("Chọn thư mục chứa nhiều chương (mỗi thư mục con / file PDF / CBZ là 1 chương)\n"
                           "– dịch lần lượt cả hàng đợi. Kéo thả nhiều thư mục / file vào cửa sổ cũng được.")
        b_multi.clicked.connect(self.pick_multi)
        b_proj = QPushButton("🗂  Dự án cũ")
        b_proj.setObjectName("bigSource")
        b_proj.setToolTip("Mở project.json trong thư mục _work để sửa tiếp bản dịch")
        b_proj.clicked.connect(self.open_project)
        for k, b in enumerate((b_folder, b_pdf, b_multi, b_proj)):
            b.setMinimumHeight(44)
            b.setMinimumWidth(0)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            row.addWidget(b, k // 2, k % 2)
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
        self.cb_mode = QComboBox()
        for t, d in RUN_MODES:
            self.cb_mode.addItem(t, d)
        self.cb_mode.setToolTip("Chỉ xoá chữ: xuất bản RAW sạch (không dịch) – nhập kịch bản để lồng chữ sau")
        self.cb_reading = QComboBox()
        for t, d in READINGS:
            self.cb_reading.addItem(t, d)
        self.cb_reading.setToolTip("Thứ tự đọc các ô thoại trong trang – để AI hiểu đúng mạch truyện")
        g.addWidget(field("Chế độ", self.cb_mode), 2, 0)
        g.addWidget(field("Thứ tự đọc", self.cb_reading), 2, 1)
        c.add(g)
        for cb in (self.cb_lang, self.cb_engine, self.cb_device, self.cb_mode, self.cb_reading):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(6)
        self.cb_engine.currentIndexChanged.connect(self._engine_changed)
        c.add(self._build_llm_box())
        self.chk_fallback = QCheckBox("Câu bỏ trống → GTX dịch bù (cần mạng)")
        self.chk_fallback.setChecked(True)
        c.add(self.chk_fallback)
        gr = QHBoxLayout()
        self.chk_glossary = QCheckBox("Dùng bảng thuật ngữ")
        self.chk_glossary.setChecked(True)
        self.chk_glossary.setToolTip("Tên riêng, xưng hô cố định cho AI; tự sửa chữ Việt sau khi dịch (mọi bộ dịch)")
        b_gl = QPushButton("📖  Thuật ngữ")
        b_gl.setToolTip("Mở bảng thuật ngữ (lưu trong data.db)")
        b_gl.clicked.connect(self.open_glossary)
        b_pr = QPushButton("👥  Xưng hô")
        b_pr.setToolTip("Cách các nhân vật gọi nhau (A ↔ B) cho AI dịch đúng vai vế  (F6)")
        b_pr.clicked.connect(self.open_pronouns)
        gr.addWidget(self.chk_glossary, 1)
        gr.addWidget(b_gl)
        gr.addWidget(b_pr)
        c.add(gr)
        v.addWidget(c)

        # --- 3. chữ ---
        c = Card("Hiển thị chữ", icon="🔤")
        self.cb_font = QComboBox()
        self.cb_font.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_font.setMinimumContentsLength(8)
        for name, path in list_fonts():
            self.cb_font.addItem(name, path)
        self.cb_font.currentIndexChanged.connect(self._font_changed)
        b_font = QPushButton("Khác…")
        b_font.setToolTip("Chọn file font .ttf/.otf khác (nên có đủ dấu tiếng Việt)")
        b_font.clicked.connect(self.pick_font)
        fr = QHBoxLayout()
        fr.setSpacing(6)
        fr.addWidget(self.cb_font, 1)
        fr.addWidget(b_font)
        c.add(field("Font chữ", fr))
        self.lbl_font_preview = QLabel("Ngươi vừa nói gì? Ầm ẦM!")
        self.lbl_font_preview.setObjectName("fontPreview")
        self.lbl_font_preview.setMinimumHeight(34)
        c.add(self.lbl_font_preview)
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
        self.chk_lama = QCheckBox("Xoá chữ trên hình bằng AI (LaMa)")
        self.chk_lama.setChecked(True)
        self.chk_lama.setToolTip("Chữ nằm trên hình / nền lưới chấm được AI vẽ lại nền sạch sẽ.\n"
                                 "Lần đầu tải model ~200 MB. Tắt thì dùng cách cũ (nhanh hơn, dễ nhoè).")
        c.add(self.chk_lama)
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
        self.cb_fmt.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_fmt.setMinimumContentsLength(4)
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
        xr = QHBoxLayout()
        self.chk_xlsx = QCheckBox("Excel lời thoại")
        self.chk_xlsx.setChecked(True)
        self.chk_xlsx.setToolTip("File .xlsx: trang, ô, loại, chữ gốc, bản dịch – để rà soát / chia sẻ nhóm dịch")
        self.chk_psd = QCheckBox("PSD 3 lớp")
        self.chk_psd.setToolTip("Mỗi trang 1 file PSD: Gốc / Nền sạch / Chữ dịch – sửa tiếp trong Photoshop")
        xr.addWidget(self.chk_xlsx)
        xr.addWidget(self.chk_psd)
        xr.addStretch(1)
        c.add(xr)
        xr2 = QHBoxLayout()
        self.chk_cbz = QCheckBox("Đóng gói .cbz")
        self.chk_cbz.setToolTip("File truyện nén .cbz – đọc bằng Tachiyomi/Mihon, CDisplayEx, Komga...")
        self.chk_script = QCheckBox("Kịch bản .tsv/.txt")
        self.chk_script.setChecked(True)
        self.chk_script.setToolTip("Kịch bản lời thoại – sửa xong nạp lại bằng 🧰 Công cụ → Nhập kịch bản")
        xr2.addWidget(self.chk_cbz)
        xr2.addWidget(self.chk_script)
        xr2.addStretch(1)
        c.add(xr2)
        lr = QHBoxLayout()
        b_logo = QPushButton("🏷  Logo nhóm dịch…")
        b_logo.setToolTip("Đóng dấu logo / credit nhóm dịch lên trang")
        b_logo.clicked.connect(self.open_logo)
        self.lbl_logo = QLabel("")
        self.lbl_logo.setObjectName("cardHint")
        lr.addWidget(b_logo)
        lr.addWidget(self.lbl_logo, 1)
        c.add(lr)
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

    def _build_llm_box(self):
        box = QFrame()
        box.setObjectName("subCard")
        g = QGridLayout(box)
        g.setContentsMargins(10, 10, 10, 10)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        self.cb_provider = QComboBox()
        for pid, (name, *_rest) in PROVIDERS.items():
            self.cb_provider.addItem(name, pid)
        self.cb_provider.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_provider.setMinimumContentsLength(6)
        self.cb_provider.currentIndexChanged.connect(self._provider_changed)
        self.ed_llm_url = QLineEdit()
        self.cb_llm_model = QComboBox()
        self.cb_llm_model.setEditable(True)
        self.cb_llm_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_llm_model.setMinimumContentsLength(6)
        b_models = QToolButton()
        b_models.setText("⟳")
        b_models.setToolTip("Kết nối lại & lấy danh sách model (Ollama: tự mở Ollama, tự chọn model đã cài)")
        b_models.clicked.connect(self._refresh_models)
        mr = QHBoxLayout()
        mr.setSpacing(6)
        mr.addWidget(self.cb_llm_model, 1)
        mr.addWidget(b_models)
        self.ed_llm_key = QLineEdit()
        self.ed_llm_key.setEchoMode(QLineEdit.Password)
        self.ed_llm_key.setPlaceholderText("API key (lưu trong config.json trên máy này)")
        self.ed_llm_style = QLineEdit()
        self.ed_llm_style.setPlaceholderText("vd. cổ trang, xưng ta – ngươi; hoặc trẻ trung, học đường")
        self.ed_llm_notes = QLineEdit()
        self.ed_llm_notes.setPlaceholderText("vd. A là nữ, B là sư phụ của A...")
        b_test = QPushButton("🔌  Thử dịch")
        b_test.setToolTip("Gửi 1 câu thử để chắc chắn AI dịch được")
        b_test.clicked.connect(lambda: self._probe_llm(True))
        self.b_pull = QToolButton()
        self.b_pull.setText("⬇  Tải model")
        self.b_pull.setToolTip("Tải model về Ollama (gợi ý cho card 12 GB)")
        self.b_pull.setPopupMode(QToolButton.InstantPopup)
        self.b_pull.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        menu = QMenu(self.b_pull)
        for name, size, desc in OL.RECOMMENDED:
            act = menu.addAction(f"{name}   ({size}) – {desc}")
            act.triggered.connect(lambda _=False, n=name: self._pull_model(n))
        self.b_pull.setMenu(menu)
        self.pull_bar = QProgressBar()
        self.pull_bar.setTextVisible(True)
        self.pull_bar.setVisible(False)
        tr = QHBoxLayout()
        tr.setSpacing(6)
        tr.addWidget(self.b_pull, 1)
        tr.addWidget(b_test, 1)
        self.lbl_llm = QLabel("")
        self.lbl_llm.setObjectName("cardHint")
        self.lbl_llm.setWordWrap(True)
        g.addWidget(field("Nhà cung cấp AI", self.cb_provider), 0, 0, 1, 2)
        g.addWidget(field("Địa chỉ máy chủ (URL)", self.ed_llm_url), 1, 0, 1, 2)
        g.addWidget(field("Model", mr), 2, 0, 1, 2)
        self.key_field = field("API key", self.ed_llm_key)
        g.addWidget(self.key_field, 3, 0, 1, 2)
        b_style = QToolButton()
        b_style.setText("✨ Mẫu")
        b_style.setToolTip("Chọn nhanh văn phong theo thể loại truyện")
        b_style.setPopupMode(QToolButton.InstantPopup)
        sm = QMenu(b_style)
        for name, txt in STYLE_PRESETS:
            act = sm.addAction(name)
            act.setToolTip(txt)
            act.triggered.connect(lambda _=False, t=txt: self.ed_llm_style.setText(t))
        b_style.setMenu(sm)
        st_row = QHBoxLayout()
        st_row.setSpacing(6)
        st_row.addWidget(self.ed_llm_style, 1)
        st_row.addWidget(b_style)
        g.addWidget(field("Văn phong", st_row), 4, 0, 1, 2)
        g.addWidget(field("Ghi chú về truyện (nhân vật, quan hệ)", self.ed_llm_notes), 5, 0, 1, 2)
        g.addLayout(tr, 6, 0, 1, 2)
        g.addWidget(self.pull_bar, 7, 0, 1, 2)
        g.addWidget(self.lbl_llm, 8, 0, 1, 2)
        self.llm_box = box
        box.setVisible(False)
        return box

    def _build_pages(self):
        box = QWidget()
        box.setMinimumWidth(176)
        box.setMaximumWidth(240)
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
        cap = QLabel("BẢN DỊCH CỦA TRANG – bấm đúp để sửa  •  tick 'Giữ' để giữ nguyên chữ gốc (logo, SFX...)")
        cap.setObjectName("viewCaption")
        ev.addWidget(cap)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Loại", "Giữ", "Chữ gốc (OCR)", "Bản dịch"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        for col in (0, 1, 2):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        ev.addWidget(self.table, 1)
        row = QHBoxLayout()
        b_apply = QPushButton("💾  Lưu bản sửa && vẽ lại trang")
        b_apply.clicked.connect(self.apply_edits)
        b_redraw_all = QPushButton("🎨  Vẽ lại tất cả")
        b_redraw_all.setToolTip("Vẽ lại mọi trang sau khi đổi font / cỡ chữ / in hoa – không cần dịch lại")
        b_redraw_all.clicked.connect(self.redraw_all)
        self.b_retrans = QPushButton("🔁  Dịch lại cả chương")
        self.b_retrans.setToolTip("Dịch lại mọi ô bằng bộ dịch đang chọn (vd. sau khi sửa bảng thuật ngữ\n"
                                  "hoặc đổi sang AI) – không đọc chữ / xoá chữ lại")
        self.b_retrans.clicked.connect(self.retranslate)
        b_tools = QToolButton()
        b_tools.setText("🧰  Công cụ")
        b_tools.setPopupMode(QToolButton.InstantPopup)
        tm = QMenu(b_tools)
        for text, fn in (("📥  Nhập kịch bản (bản dịch làm sẵn)…\tCtrl+I", self.import_script),
                         ("🔍  Tìm && thay thế cả chương…\tCtrl+H", self.open_find),
                         ("☑  Soát lỗi cả chương\tF7", self.open_qc),
                         ("🪄  Tự sửa dấu câu / khoảng trắng\tF8", self.auto_fix_punct),
                         ("👥  Xưng hô nhân vật…\tF6", self.open_pronouns),
                         ("📜  Cắt / ghép webtoon…\tF12", self.open_webtoon),
                         ("⌨  Phím tắt\tF1", self.show_shortcuts)):
            tm.addAction(text).triggered.connect(fn)
        b_tools.setMenu(tm)
        row.addWidget(b_apply)
        row.addWidget(b_redraw_all)
        row.addWidget(self.b_retrans)
        row.addWidget(b_tools)
        row.addStretch(1)
        ev.addLayout(row)
        split.addWidget(edit)
        split.setSizes([620, 250])
        vv.addWidget(split)
        self.tabs.addTab(view, "🖼  Xem && sửa")
        # --- tab tình trạng ---
        stw = QWidget()
        sv = QVBoxLayout(stw)
        sv.setContentsMargins(8, 8, 8, 8)
        self.lbl_status_tab = QLabel("Chưa có dữ liệu – dịch xong sẽ liệt kê các ô cần xem lại.")
        self.lbl_status_tab.setObjectName("cardHint")
        self.lbl_status_tab.setWordWrap(True)
        qr = QHBoxLayout()
        qr.addWidget(self.lbl_status_tab, 1)
        self.cb_qc = QComboBox()
        self.cb_qc.addItem("Mọi lỗi", 0)
        self.cb_qc.addItem("❌ Nên sửa trước khi xuất", 1)
        self.cb_qc.addItem("⚠ Lệch / tràn khung", 2)
        self.cb_qc.addItem("✎ Kiểm tra lại", 3)
        self.cb_qc.currentIndexChanged.connect(self._refresh_status)
        b_fix = QPushButton("🪄  Tự sửa dấu câu")
        b_fix.setToolTip("Bỏ khoảng trắng thừa, sửa '....' / '!!!!!', thêm cách sau dấu phẩy, viết hoa đầu câu (F8)")
        b_fix.clicked.connect(self.auto_fix_punct)
        qr.addWidget(self.cb_qc)
        qr.addWidget(b_fix)
        sv.addLayout(qr)
        self.status_table = QTableWidget(0, 4)
        self.status_table.setHorizontalHeaderLabels(["Trang", "Ô", "Vấn đề", "Chữ gốc → bản dịch"])
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.status_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        sh = self.status_table.horizontalHeader()
        for col in (0, 1, 2):
            sh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        sh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.status_table.cellDoubleClicked.connect(self._goto_issue)
        sv.addWidget(self.status_table, 1)
        self.tabs.addTab(stw, "✅  Soát lỗi")
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
            self.tabs.setTabText(TAB_LOG, "📜  Nhật ký  ⚠")

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
        self.chk_fallback.setChecked(s.get_bool("gtx_fallback", True))
        self.chk_glossary.setChecked(s.get_bool("use_glossary", True))
        self.chk_lama.setChecked(s.get_bool("use_lama", True))
        font = s.value("font", "") or ""
        self._set_font_path(font if font and Path(font).exists() else find_default_font())
        self.chk_upper.setChecked(s.get_bool("upper", False))
        self.sl_scale.setValue(s.get_int("font_scale", 70))
        self.sp_dpi.setValue(s.get_int("dpi", 200))
        self.cb_fmt.setCurrentText(s.value("fmt", "jpg"))
        self.chk_pdf.setChecked(s.get_bool("pdf", True))
        self.chk_xlsx.setChecked(s.get_bool("export_xlsx", True))
        self.chk_psd.setChecked(s.get_bool("export_psd", False))
        self.chk_cbz.setChecked(s.get_bool("export_cbz", False))
        self.chk_script.setChecked(s.get_bool("export_script", True))
        self._set_combo(self.cb_mode, s.value("run_mode", "translate"))
        self._set_combo(self.cb_reading, s.value("reading", "auto"))
        self._update_logo_label()
        self._set_combo(self.cb_provider, s.value("llm_provider", "ollama"))
        self._provider_changed()
        self.ed_llm_style.setText(s.value("llm_style", ""))
        self.ed_llm_notes.setText(s.value("llm_notes", ""))
        self._engine_changed()

    def _save_settings(self):
        s = self.settings
        s.setValue("lang", self.cb_lang.currentData())
        s.setValue("device", self.cb_device.currentData())
        s.setValue(f"engine_{self.cb_lang.currentData()}", self.cb_engine.currentData())
        s.setValue("gtx_fallback", self.chk_fallback.isChecked())
        s.setValue("use_glossary", self.chk_glossary.isChecked())
        s.setValue("use_lama", self.chk_lama.isChecked())
        s.setValue("font", self._font_path())
        s.setValue("upper", self.chk_upper.isChecked())
        s.setValue("font_scale", self.sl_scale.value())
        s.setValue("dpi", self.sp_dpi.value())
        s.setValue("fmt", self.cb_fmt.currentText())
        s.setValue("pdf", self.chk_pdf.isChecked())
        s.setValue("export_xlsx", self.chk_xlsx.isChecked())
        s.setValue("export_psd", self.chk_psd.isChecked())
        s.setValue("export_cbz", self.chk_cbz.isChecked())
        s.setValue("export_script", self.chk_script.isChecked())
        s.setValue("run_mode", self.cb_mode.currentData())
        s.setValue("reading", self.cb_reading.currentData())
        self._store_provider_fields()
        s.setValue("llm_provider", self.cb_provider.currentData())
        s.setValue("llm_style", self.ed_llm_style.text().strip())
        s.setValue("llm_notes", self.ed_llm_notes.text().strip())
        try:
            s.save()
        except OSError as e:
            self.log(f"! Không lưu được config.json: {e}")

    # ---- AI (LLM): mỗi nhà cung cấp nhớ URL / model / key riêng ----
    def _store_provider_fields(self):
        pid = getattr(self, "_cur_provider", None)
        if not pid:
            return
        llm = dict(self.settings.value("llm", {}) or {})
        llm[pid] = {"url": self.ed_llm_url.text().strip(), "model": self.cb_llm_model.currentText().strip(),
                    "key": self.ed_llm_key.text().strip()}
        self.settings.setValue("llm", llm)

    def _provider_changed(self):
        self._store_provider_fields()
        pid = self.cb_provider.currentData()
        name, def_url, def_model, need_key, _api = PROVIDERS[pid]
        saved = (self.settings.value("llm", {}) or {}).get(pid, {})
        self.ed_llm_url.setText(saved.get("url") or def_url)
        self.cb_llm_model.clear()
        self.cb_llm_model.setEditText(saved.get("model") or def_model)
        self.ed_llm_key.setText(saved.get("key", ""))
        self.key_field.setVisible(need_key or pid == "custom")
        self.b_pull.setVisible(pid == "ollama")
        self.lbl_llm.setText(
            "Ollama: app tự mở Ollama, tự chọn model đã cài; chưa có model thì bấm ⬇ Tải model." if pid == "ollama"
            else "LM Studio: mở LM Studio, bật Local Server, nạp model rồi bấm ⟳." if pid == "lmstudio"
            else "Cần API key của bạn – chữ trong truyện được gửi lên máy chủ của nhà cung cấp để dịch.")
        self._cur_provider = pid
        self._ollama_connected = False
        self._maybe_auto_ollama()

    def _engine_changed(self):
        is_llm = self.cb_engine.currentData() == "llm"
        self.llm_box.setVisible(is_llm)
        if is_llm:
            QTimer.singleShot(0, self._maybe_auto_ollama)
        self.chk_fallback.setText("Câu AI bỏ sót → GTX dịch bù (cần mạng)" if is_llm
                                  else "Câu bỏ trống → GTX dịch bù (cần mạng)")

    # ---- Ollama: tự kết nối / tải model ----
    def _maybe_auto_ollama(self):
        if (not getattr(self, "llm_box", None) or self.cb_engine.currentData() != "llm"
                or self.cb_provider.currentData() != "ollama" or self._ollama_connected):
            return
        self._ollama_auto_connect()

    def _ollama_auto_connect(self, prefer_model: str = ""):
        if self.ollama_auto is not None and self.ollama_auto.isRunning():
            return
        self.lbl_llm.setText("⏳ Đang tìm Ollama trên máy...")
        self.ollama_auto = OllamaAuto(self.ed_llm_url.text().strip() or OL.DEFAULT_URL,
                                      prefer_model or self.cb_llm_model.currentText().strip())
        self.ollama_auto.done.connect(self._on_ollama_auto)
        self.ollama_auto.start()

    def _on_ollama_auto(self, res):
        if not res.get("ok"):
            self._ollama_connected = False
            self.lbl_llm.setText("❌ " + res.get("message", ""))
            return
        self._ollama_connected = True
        models = res.get("models", [])
        self.cb_llm_model.blockSignals(True)
        self.cb_llm_model.clear()
        for name, gb in models:
            self.cb_llm_model.addItem(name)
            self.cb_llm_model.setItemData(self.cb_llm_model.count() - 1, f"{gb} GB", Qt.ToolTipRole)
        if res.get("model"):
            self.cb_llm_model.setEditText(res["model"])
        self.cb_llm_model.blockSignals(False)
        self.lbl_llm.setText(("✅ " if models else "⚠ ") + res.get("message", ""))
        self._store_provider_fields()

    def _refresh_models(self):
        if self.cb_provider.currentData() == "ollama":
            self._ollama_connected = False
            self._ollama_auto_connect()
        else:
            self._probe_llm(False)

    def _pull_model(self, name):
        if self.ollama_pull is not None and self.ollama_pull.isRunning():
            QMessageBox.information(self, "Đang tải", "Đang tải một model khác, chờ xong đã.")
            return
        if QMessageBox.question(self, "Tải model", f"Tải model {name} về Ollama?\n"
                                "Dung lượng vài GB, chỉ tải 1 lần.") != QMessageBox.Yes:
            return
        self.pull_bar.setVisible(True)
        self.pull_bar.setRange(0, 0)
        self.b_pull.setEnabled(False)
        self.lbl_llm.setText(f"⏳ Đang tải {name}...")
        self.ollama_pull = OllamaPull(self.ed_llm_url.text().strip() or OL.DEFAULT_URL, name)
        self.ollama_pull.progress.connect(self._on_pull_progress)
        self.ollama_pull.done.connect(lambda ok, msg, n=name: self._on_pull_done(ok, msg, n))
        self.ollama_pull.start()

    def _on_pull_progress(self, pct, txt):
        if pct < 0:
            self.pull_bar.setRange(0, 0)
        else:
            self.pull_bar.setRange(0, 1000)
            self.pull_bar.setValue(int(pct * 10))
            self.pull_bar.setFormat(f"{pct:.0f}%")
        self.lbl_llm.setText(f"⏳ {txt}")

    def _on_pull_done(self, ok, msg, name):
        self.pull_bar.setVisible(False)
        self.b_pull.setEnabled(True)
        self.lbl_llm.setText(msg)
        self.log(msg)
        if not ok:
            QMessageBox.warning(self, "Không tải được model",
                                f"{msg}\n\nCó thể tải tay: mở Command Prompt (CMD) gõ\n    ollama pull {name}\n"
                                "xong quay lại app bấm ⟳.")
        if ok:
            self._ollama_connected = False
            self._ollama_auto_connect(prefer_model=name)

    def _probe_llm(self, chat_test):
        if self.llm_probe is not None and self.llm_probe.isRunning():
            return
        self.lbl_llm.setText("⏳ Đang kết nối..." if not chat_test
                             else "⏳ Đang hỏi thử AI (model chạy máy có thể mất 10–60 giây)...")
        self.llm_probe = LlmProbe(self.cb_provider.currentData(), self.ed_llm_url.text(),
                                  self.cb_llm_model.currentText(), self.ed_llm_key.text(), chat_test)
        self.llm_probe.done.connect(self._on_llm_probe)
        self.llm_probe.start()

    def _on_llm_probe(self, ok, models, msg):
        self.lbl_llm.setText(msg)
        if ok and models:
            cur = self.cb_llm_model.currentText()
            self.cb_llm_model.clear()
            self.cb_llm_model.addItems(models)
            self.cb_llm_model.setEditText(cur if cur else models[0])

    def open_glossary(self):
        GlossaryDialog(self).exec()

    # ---- font ----
    def _font_path(self) -> str:
        return self.cb_font.currentData() or ""

    def _set_font_path(self, path):
        if not path:
            return
        i = self.cb_font.findData(path)
        if i < 0:
            self.cb_font.addItem(f"📄 {Path(path).name}", path)
            i = self.cb_font.count() - 1
        self.cb_font.setCurrentIndex(i)
        self._font_changed()

    def _font_changed(self):
        path = self._font_path()
        if not path or not Path(path).exists():
            return
        fid = QFontDatabase.addApplicationFont(path)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        # stylesheet chung của app đè setFont() -> đặt font riêng bằng stylesheet của nhãn
        fam = fams[0].replace("'", "") if fams else ""
        self.lbl_font_preview.setStyleSheet(f"font-family: '{fam}'; font-size: 21px;" if fam else "")
        miss = vi_missing(path)
        if miss:
            self.lbl_font_preview.setText(f"⚠ Font thiếu {len(miss)} chữ có dấu: {miss[:10]}…")
            self.lbl_font_preview.setProperty("warn", True)
        else:
            self.lbl_font_preview.setText("Ngươi vừa nói gì? Ầm ẦM!")
            self.lbl_font_preview.setProperty("warn", False)
        self.lbl_font_preview.style().unpolish(self.lbl_font_preview)
        self.lbl_font_preview.style().polish(self.lbl_font_preview)

    def _fill_engines(self):
        lang = self.cb_lang.currentData() or "zh"
        self.cb_engine.blockSignals(True)
        self.cb_engine.clear()
        for t, d in ENGINES[lang]:
            self.cb_engine.addItem(t, d)
        self._set_combo(self.cb_engine, self.settings.value(f"engine_{lang}", default_engine(lang)))
        self.cb_engine.blockSignals(False)
        if hasattr(self, "llm_box"):
            self._engine_changed()

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
            use_lama=self.chk_lama.isChecked(),
            use_glossary=self.chk_glossary.isChecked(),
            llm_provider=self.cb_provider.currentData(),
            llm_url=self.ed_llm_url.text().strip(),
            llm_model=self.cb_llm_model.currentText().strip(),
            llm_style=self.ed_llm_style.text().strip(),
            llm_notes=self.ed_llm_notes.text().strip(),
            export_xlsx=self.chk_xlsx.isChecked(),
            export_psd=self.chk_psd.isChecked(),
            font_path=self._font_path(),
            uppercase=self.chk_upper.isChecked(),
            font_scale=self.sl_scale.value(),
            pdf_dpi=self.sp_dpi.value(),
            img_format=self.cb_fmt.currentText(),
            export_pdf=self.chk_pdf.isChecked(),
            out_dir=self.ed_out.text().strip(),
            **self._extra_config(),
        )

    def _extra_config(self) -> dict:
        """Cài đặt dùng chung cho dịch mới và vẽ lại: chế độ, thứ tự đọc, xuất CBZ/kịch bản, logo."""
        s = self.settings
        logo_on = s.get_bool("logo_on", False) and Path(s.value("logo_path", "") or "").is_file()
        return dict(run_mode=self.cb_mode.currentData(), reading=self.cb_reading.currentData(),
                    export_cbz=self.chk_cbz.isChecked(), export_script=self.chk_script.isChecked(),
                    logo_path=s.value("logo_path", "") if logo_on else "", logo_pos=s.value("logo_pos", "auto"),
                    logo_size=s.get_int("logo_size", 12), logo_opacity=s.get_int("logo_opacity", 85),
                    logo_pages=s.value("logo_pages", "all"), credit=s.value("credit", "") or "")

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
        f, _ = QFileDialog.getOpenFileName(self, "Chọn file truyện (PDF / CBZ / ZIP)", self._last_dir(), SRC_FILTER)
        if f:
            self.load_pdf(f)

    def load_pdf(self, f):
        self.settings.setValue("last_dir", str(Path(f).parent))
        if Path(f).suffix.lower() in ARCHIVE_EXT:
            return self.load_archive(f)
        try:
            n = pdf_page_count(f)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Lỗi PDF", f"Không mở được PDF:\n{e}")
            return
        self._set_source("pdf", f, [])
        self._set_source_label(f"📄  <b>{Path(f).name}</b><br>{n} trang PDF")
        self.ed_out.setText(str(Path(f).parent / (Path(f).stem + "_VI")))

    def load_archive(self, f):
        try:
            n = len(archive_images(f))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Lỗi file nén", f"Không mở được file:\n{e}")
            return
        if not n:
            QMessageBox.warning(self, "Không có ảnh", "File nén không có ảnh jpg/png/webp nào.")
            return
        self._set_source("archive", f, [])
        self._set_source_label(f"🗜  <b>{Path(f).name}</b><br>{n} trang (truyện nén)")
        self.ed_out.setText(str(Path(f).parent / (Path(f).stem + "_VI")))

    # ---- hàng đợi nhiều chương ----
    @staticmethod
    def _source_of(p: Path):
        if p.is_dir():
            return ("folder", str(p)) if list_images(p) else None
        ext = p.suffix.lower()
        if ext == ".pdf":
            return ("pdf", str(p))
        if ext in ARCHIVE_EXT:
            return ("archive", str(p))
        return None

    def pick_multi(self):
        if self._busy():
            return
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa nhiều chương", self._last_dir())
        if not d:
            return
        from core.loader import natural_key

        items = sorted(Path(d).iterdir(), key=lambda x: natural_key(x.name))
        jobs = [j for j in (self._source_of(x) for x in items) if j]
        if not jobs and list_images(d):
            return self.load_folder(d)
        if not jobs:
            QMessageBox.warning(self, "Không có chương", "Thư mục không có thư mục con chứa ảnh / file PDF / CBZ nào.")
            return
        self.settings.setValue("last_dir", d)
        self.load_queue(jobs, Path(d))

    def load_queue(self, jobs, parent: Path):
        if len(jobs) == 1:
            kind, path = jobs[0]
            return self.load_folder(path) if kind == "folder" else self.load_pdf(path)
        kind, path = jobs[0]
        self._set_source(kind, path, list_images(path) if kind == "folder" else [])
        self.queue = list(jobs)
        names = ", ".join(Path(p).name for _k, p in jobs[:4]) + (" …" if len(jobs) > 4 else "")
        self._set_source_label(f"📚  <b>{len(jobs)} chương</b> trong hàng đợi – dịch lần lượt<br>{names}")
        self.ed_out.setText(str(parent / (parent.name + "_VI")))

    def _queue_jobs(self, out_base: str):
        """[(loại, đường dẫn, thư mục kết quả)] – mỗi chương 1 thư mục con trong thư mục kết quả."""
        if not getattr(self, "queue", None):
            return None
        return [(k, p, str(Path(out_base) / (Path(p).stem if k != "folder" else Path(p).name)))
                for k, p in self.queue]

    def _set_source_label(self, html):
        self.lbl_source.setText(html)
        self.lbl_source.setProperty("filled", True)
        self.lbl_source.style().unpolish(self.lbl_source)
        self.lbl_source.style().polish(self.lbl_source)

    def _set_source(self, kind, path, pages):
        self.queue = []
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
        if len(urls) > 1:
            from core.loader import natural_key

            jobs = [j for j in (self._source_of(Path(u)) for u in sorted(urls, key=natural_key)) if j]
            if len(jobs) > 1:
                return self.load_queue(jobs, Path(jobs[0][1]).parent)
        p = Path(urls[0])
        if p.suffix.lower() in ARCHIVE_EXT:
            self.load_archive(str(p))
        elif p.is_dir():
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
            it.setSizeHint(QSize(150, thumb_size().height() + 14))
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
        return f"Trang {i + 1}\n{'✓ Đã dịch' if i in self.done_pages else 'Chưa dịch'}"

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
        cur = self._font_path()
        start = str(Path(cur).parent) if cur else r"C:\Windows\Fonts"
        f, _ = QFileDialog.getOpenFileName(self, "Chọn font hỗ trợ tiếng Việt", start, "Font (*.ttf *.otf *.ttc)")
        if f:
            self._set_font_path(f)
            miss = vi_missing(f)
            if miss:
                QMessageBox.warning(self, "Font thiếu dấu",
                                    f"Font này thiếu {len(miss)} chữ có dấu tiếng Việt ({miss[:20]}...).\n"
                                    "Chữ dịch có thể hiện ô vuông – nên chọn font khác.")

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
        jobs = self._queue_jobs(cfg.out_dir)
        if self.source_type == "folder" and not jobs and \
                Path(cfg.out_dir).resolve() == Path(self.source_path).resolve():
            QMessageBox.warning(self, "Thư mục kết quả",
                                "Thư mục kết quả phải khác thư mục ảnh gốc (tránh ghi đè ảnh gốc).")
            return
        if cfg.font_path and not Path(cfg.font_path).exists():
            QMessageBox.warning(self, "Font", "Không tìm thấy file font đã chọn.")
            return
        if not self._check_llm(cfg):
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
        self.tabs.setTabText(TAB_LOG, "📜  Nhật ký")
        self.worker = Worker(cfg, self.source_type, self.source_path, api_key=self.ed_llm_key.text().strip(),
                             jobs=jobs)
        self.worker.chapter.connect(self._on_chapter)
        self._wire_worker()
        self.worker.start()

    def _check_llm(self, cfg) -> bool:
        if cfg.engine != "llm":
            return True
        need_key = PROVIDERS[cfg.llm_provider][3]
        if need_key and not self.ed_llm_key.text().strip():
            QMessageBox.information(self, "Thiếu API key", "Nhập API key của nhà cung cấp AI đã chọn "
                                    "(hoặc chọn Ollama / LM Studio chạy trên máy).")
            return False
        if not cfg.llm_model:
            QMessageBox.information(self, "Thiếu model", "Nhập tên model AI (bấm ⟳ để lấy danh sách).")
            return False
        return True

    def _wire_worker(self):
        self.worker.log.connect(self.log)
        self.worker.progress.connect(self._on_progress)
        self.worker.stage.connect(self._on_stage)
        self.worker.pages_ready.connect(self._on_pages_ready)
        self.worker.page_done.connect(self._on_page_done)
        self.worker.finished_ok.connect(self._on_finished)
        self.b_start.setEnabled(False)
        self.b_retrans.setEnabled(False)
        self.b_start.setText("⏳   ĐANG DỊCH...")
        self.b_stop.setEnabled(True)

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
            self.lbl_progress.setText("Đang dịch...")

    @staticmethod
    def _fmt_time(sec):
        sec = int(max(0, sec))
        return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"

    def _on_progress(self, i, n, text=""):
        self.progress.setRange(0, max(1, n))
        self.progress.setValue(i)
        pct = 100 * i / max(1, n)
        self.lbl_pct.setText(f"{pct:.0f}%")
        el = time.time() - (self._t_start or time.time())
        txt = text or f"Trang {i}/{n}"
        if i > 0:
            per = el / i
            if not text or text.startswith("Trang"):
                txt += f"  •  {per:.1f}s/trang"
            txt += f"  •  đã chạy {self._fmt_time(el)}"
            self.lbl_eta.setText(f"còn ~{self._fmt_time(per * (n - i))}")
        self.lbl_progress.setText(txt)
        self.setWindowTitle(f"[{pct:.0f}%] {self.base_title}")

    def _on_chapter(self, k, n, name):
        self.done_pages = {}
        self.lbl_status.setText(f"📚 Chương {k}/{n}: {name}")
        self.setWindowTitle(f"[{k}/{n}] {self.base_title}")

    def _on_pages_ready(self, pages):
        self.src_pages = list(pages)
        self.done_pages = {}
        self._fill_page_list()

    def _on_page_done(self, i, page):
        self.done_pages[i] = page
        self._refresh_item(i)
        if self.page_list.currentRow() == i:
            self.show_page(i)

    def _on_finished(self, ok, project_path):
        self.b_start.setEnabled(True)
        self.b_retrans.setEnabled(True)
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
        self._refresh_status()
        if ok and self.done_pages:
            self.lbl_status.setText(f"✅ Hoàn tất {len(self.done_pages)} trang → {self.ed_out.text()}")
        elif not ok:
            self.tabs.setCurrentIndex(TAB_LOG) if "LỖI" in self.log_box.toPlainText()[-4000:] else None

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
        warn_bg, miss_bg = QColor("#3a2e10"), QColor("#3a1820")
        for k, b in enumerate(page["blocks"]):
            self.table.insertRow(k)
            num = QTableWidgetItem(str(k + 1))
            num.setTextAlignment(Qt.AlignCenter)
            kind = QTableWidgetItem(KIND_VI.get(b.get("kind", ""), "–"))
            keep = QTableWidgetItem()
            keep.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            keep.setCheckState(Qt.Checked if b.get("keep") else Qt.Unchecked)
            keep.setToolTip("Giữ nguyên chữ gốc (không dịch, không xoá)")
            orig = QTableWidgetItem(b["text"])
            for it in (num, kind, orig):
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            tr = QTableWidgetItem(b["translation"])
            if b.get("overflow"):
                tr.setToolTip("Chữ dịch quá dài so với bóng thoại – nên rút gọn")
                for it in (num, tr):
                    it.setBackground(warn_bg)
            elif not b.get("translation") and not b.get("keep"):
                tr.setToolTip("Chưa dịch – gõ bản dịch rồi bấm Lưu")
                for it in (num, tr):
                    it.setBackground(miss_bg)
            for c, it in enumerate((num, kind, keep, orig, tr)):
                self.table.setItem(k, c, it)
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
            item = self.table.item(k, 4)
            if item is not None:
                b["translation"] = item.text()
            keep = self.table.item(k, 2)
            if keep is not None:
                b["keep"] = keep.checkState() == Qt.Checked
        if self._redraw([page]):
            self.lbl_status.setText(f"Đã vẽ lại trang {i + 1}.")

    def redraw_all(self):
        if self._busy() or not self.project:
            return
        if self._redraw(self.project["pages"]):
            self.lbl_status.setText(f"Đã vẽ lại {len(self.project['pages'])} trang.")

    def _redraw(self, pages) -> bool:
        self._save_settings()
        font, upper, scale = self._font_path(), self.chk_upper.isChecked(), self.sl_scale.value()
        ok = True
        cfg = self.project.setdefault("config", {})
        extra = self._extra_config()
        extra.pop("run_mode")  # giữ chế độ của dự án (bản RAW sạch thì ô trống vẫn sạch)
        extra.pop("reading")
        cfg.update(extra)
        total = len(self.project["pages"])
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for p in pages:
                rerender_page(p, font, upper, scale, cfg, total)
                self.done_pages[p["index"]] = p
                self._refresh_item(p["index"])
            self.project["config"]["font_path"] = font
            self.project["config"]["uppercase"] = upper
            self.project["config"]["font_scale"] = scale
            self.project["config"]["export_xlsx"] = self.chk_xlsx.isChecked()
            self.project["config"]["export_psd"] = self.chk_psd.isChecked()
            save_project(self.project, self.project_path)
            from core.exporter import export_extras

            export_extras(self.project, Path(self.project_path).parent.parent, self.project["config"], self.log)
        except Exception:  # noqa: BLE001
            ok = False
            self.log("LỖI:\n" + traceback.format_exc())
        finally:
            QApplication.restoreOverrideCursor()
        self.show_page(self.page_list.currentRow())
        self._refresh_status()
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
            self._set_font_path(cfg.font_path)
        self.chk_upper.setChecked(cfg.uppercase)
        self.sl_scale.setValue(int(cfg.font_scale))
        self.chk_pdf.setChecked(cfg.export_pdf)
        self._set_combo(self.cb_reading, cfg.reading)
        self.ed_out.setText(str(Path(f).parent.parent))
        self.source_type, self.source_path = None, None
        self.queue = []
        self._set_source_label(f"🗂  <b>Dự án: {proj.get('source', '')}</b><br>{len(self.done_pages)} trang đã dịch")
        self._fill_page_list()
        self._refresh_status()

    def retranslate(self):
        if self._busy():
            return
        if not self.project or not self.project_path:
            QMessageBox.information(self, "Chưa có bản dịch", "Hãy dịch một truyện (hoặc mở Dự án cũ) trước.")
            return
        cfg = self._config()
        cfg.out_dir = str(Path(self.project_path).parent.parent)
        if not self._check_llm(cfg):
            return
        name = self.cb_engine.currentText()
        if QMessageBox.question(self, "Dịch lại cả chương",
                                f"Dịch lại {len(self.project['pages'])} trang bằng:\n{name}\n\n"
                                "Mọi bản dịch (kể cả đã sửa tay) sẽ được thay mới. Tiếp tục?") != QMessageBox.Yes:
            return
        self._save_settings()
        self.progress.setRange(0, 0)
        self.lbl_pct.setText("…")
        self.lbl_eta.setText("")
        self._t_start = None
        self.worker = Worker(cfg, api_key=self.ed_llm_key.text().strip(), project=self.project,
                             project_path=self.project_path)
        self._wire_worker()
        self.worker.start()

    def _qc_terms(self):
        if not self.chk_glossary.isChecked():
            return []
        try:
            from core.store import Glossary

            lang = (self.project or {}).get("config", {}).get("src_lang") or self.cb_lang.currentData()
            return Glossary().terms_for(lang)
        except Exception:  # noqa: BLE001
            return []

    def _refresh_status(self):
        """Tab Soát lỗi: chạy bộ soát lỗi cả chương (chưa dịch, còn chữ gốc, tràn khung, dấu câu...)."""
        from core.script import QC_CODES, qc_check

        pages = sorted(self.done_pages.values(), key=lambda p: p["index"])
        total = sum(len(p.get("blocks", [])) for p in pages)
        issues = qc_check({"pages": pages}, self._qc_terms()) if pages else []
        grp = self.cb_qc.currentData() if hasattr(self, "cb_qc") else 0
        shown = [x for x in issues if not grp or QC_CODES[x[2]][0] == grp]
        self.status_table.setRowCount(0)
        for r, (pi, k, code, txt) in enumerate(shown):
            self.status_table.insertRow(r)
            for c, val in enumerate((str(pi + 1), str(k + 1), QC_CODES[code][1], txt)):
                it = QTableWidgetItem(val)
                it.setData(Qt.UserRole, (pi, k))
                if c == 2:
                    it.setToolTip(code)
                self.status_table.setItem(r, c, it)
        n_block = len({(pi, k) for pi, k, _c, _t in issues})
        if not pages:
            self.lbl_status_tab.setText("Chưa có dữ liệu – dịch xong sẽ liệt kê các ô cần xem lại.")
            self.tabs.setTabText(TAB_STATUS, "✅  Soát lỗi")
        elif issues:
            n1 = sum(1 for x in issues if QC_CODES[x[2]][0] == 1)
            self.lbl_status_tab.setText(
                f"{len(issues)} lỗi ở {n_block}/{total} ô ({n1} nên sửa trước khi xuất) – bấm đúp để mở đúng ô, "
                "sửa bản dịch rồi bấm Lưu (Ctrl+S). Lỗi dấu câu: bấm 🪄 Tự sửa.")
            self.tabs.setTabText(TAB_STATUS, f"⚠  Soát lỗi ({len(issues)})")
        else:
            self.lbl_status_tab.setText(f"✅ Tốt – {total} ô đều đã dịch, vừa khung, không thấy lỗi.")
            self.tabs.setTabText(TAB_STATUS, "✅  Soát lỗi")

    def _goto_issue(self, row, _col):
        it = self.status_table.item(row, 0)
        if it is None:
            return
        pi, k = it.data(Qt.UserRole)
        self.page_list.setCurrentRow(pi)
        self.show_page(pi)
        self.tabs.setCurrentIndex(TAB_VIEW)
        if k < self.table.rowCount():
            self.table.selectRow(k)
            self.table.scrollToItem(self.table.item(k, 4))

    # ---------------- công cụ ----------------
    def _need_project(self) -> bool:
        if self._busy():
            return False
        if not self.project or not self.project_path:
            QMessageBox.information(self, "Chưa có bản dịch", "Hãy dịch một truyện (hoặc mở Dự án cũ) trước.")
            return False
        return True

    def _pages_by_index(self, idxs):
        want = set(idxs)
        return [p for p in self.project["pages"] if p["index"] in want]

    def open_pronouns(self):
        PronounDialog(self).exec()

    def open_logo(self):
        if LogoDialog(self, self.settings).exec():
            self._update_logo_label()
            if self.project and QMessageBox.question(
                    self, "Logo", "Vẽ lại tất cả trang để áp dụng logo?") == QMessageBox.Yes:
                self.redraw_all()

    def _update_logo_label(self):
        s = self.settings
        on = s.get_bool("logo_on", False) and Path(s.value("logo_path", "") or "").is_file()
        self.lbl_logo.setText(f"✅ {Path(s.value('logo_path')).name}" if on else "Tắt")

    def import_script(self):
        if not self._need_project():
            return
        f, _ = QFileDialog.getOpenFileName(
            self, "Nhập kịch bản (bản dịch làm sẵn)", str(Path(self.project_path).parent.parent),
            "Kịch bản (*.xlsx *.tsv *.csv *.txt *.md *.json *.docx);;Tất cả (*.*)")
        if not f:
            return
        from core.script import apply_script, read_script

        try:
            entries = read_script(f)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Lỗi kịch bản", f"Không đọc được file:\n{e}")
            return
        if not entries:
            QMessageBox.warning(self, "Kịch bản trống", "Không tìm thấy câu dịch nào trong file.")
            return
        keyed = sum(1 for pg, bx, _t in entries if pg is not None and bx is not None)
        how = ("theo đúng số trang / số ô" if keyed == len(entries)
               else "lần lượt theo thứ tự đọc (bỏ qua ô 'Giữ')")
        n_blocks = sum(len(p["blocks"]) for p in self.project["pages"])
        if QMessageBox.question(self, "Nhập kịch bản",
                                f"Đọc được {len(entries)} câu – sẽ điền {how}.\nChương có {n_blocks} ô.\n\n"
                                "Bản dịch hiện tại của các ô này sẽ bị thay. Tiếp tục?") != QMessageBox.Yes:
            return
        changed, touched = apply_script(self.project, entries)
        if touched:
            self._redraw(self._pages_by_index(touched))
        self.lbl_status.setText(f"📥 Đã nhập kịch bản: đổi {changed} ô trên {len(touched)} trang.")
        self.log(f"Nhập kịch bản {Path(f).name}: đổi {changed} ô trên {len(touched)} trang")

    def open_find(self):
        if not self._need_project():
            return
        FindReplaceDialog(self, self.project, lambda touched: self._redraw(self._pages_by_index(touched))).exec()

    def open_qc(self):
        self._refresh_status()
        self.tabs.setCurrentIndex(TAB_STATUS)

    def auto_fix_punct(self):
        if not self._need_project():
            return
        from core.script import auto_fix

        n, touched = auto_fix(self.project)
        if not n:
            self.lbl_status.setText("🪄 Không có lỗi dấu câu nào cần sửa.")
            self._refresh_status()
            return
        self._redraw(self._pages_by_index(touched))
        self.lbl_status.setText(f"🪄 Đã tự sửa dấu câu {n} ô trên {len(touched)} trang.")

    def open_webtoon(self):
        if not self._need_project():
            return
        WebtoonDialog(self, self.project, str(Path(self.project_path).parent.parent)).exec()

    def show_shortcuts(self):
        ShortcutsDialog(self).exec()

    def _nav_page(self, step):
        n = self.page_list.count()
        if n:
            self.page_list.setCurrentRow(max(0, min(n - 1, self.page_list.currentRow() + step)))

    def _setup_shortcuts(self):
        for keys, fn in (("Ctrl+O", self.pick_folder), ("Ctrl+Shift+O", self.pick_pdf),
                         ("Ctrl+Return", self.start), ("Ctrl+Enter", self.start),
                         ("Ctrl+S", self.apply_edits), ("Ctrl+Shift+S", self.redraw_all),
                         ("Alt+Left", lambda: self._nav_page(-1)), ("Alt+Right", lambda: self._nav_page(1)),
                         ("Ctrl+H", self.open_find), ("Ctrl+F", self.open_find), ("Ctrl+I", self.import_script),
                         ("F6", self.open_pronouns), ("F7", self.open_qc), ("F8", self.auto_fix_punct),
                         ("F12", self.open_webtoon), ("F1", self.show_shortcuts)):
            QShortcut(QKeySequence(keys), self, activated=fn)

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
        if self.ollama_pull is not None and self.ollama_pull.isRunning():
            self.ollama_pull.stop_event.set()
        for th in (self.probe, self.checker, self.llm_probe, self.ollama_auto, self.ollama_pull):
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
                {"text": "他必须得抓紧时间了。", "translation": "Hắn phải tranh thủ thời gian rồi.", "kind": "speech"},
                {"text": "你说什么?", "translation": "Ngươi vừa nói cái gì vậy hả?", "kind": "shout",
                 "overflow": i == 1},
                {"text": "轰隆", "translation": "", "kind": "sfx", "keep": i != 2}]}
            win._refresh_item(i)
        win.show_page(0)
        win._refresh_status()
        if os.environ.get("DTT_DEMO_LLM"):
            win._set_combo(win.cb_engine, "llm")
        if os.environ.get("DTT_DEMO_TAB"):
            win.tabs.setCurrentIndex(int(os.environ["DTT_DEMO_TAB"]))

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
