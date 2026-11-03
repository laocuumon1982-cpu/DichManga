"""Hộp thoại Cập nhật và Giới thiệu."""
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QTextBrowser, QVBoxLayout)

from core import APP_AUTHOR, APP_NAME, APP_VERSION, GITHUB_URL
from core import updater
from core.paths import ICON_PATH, IS_PORTABLE


class UpdateChecker(QThread):
    """Hỏi GitHub xem có bản mới không (chạy nền)."""
    result = Signal(object, str)   # (info | None, lỗi)

    def run(self):
        try:
            self.result.emit(updater.check_latest(), "")
        except Exception as e:  # noqa: BLE001
            self.result.emit(None, str(e))


class UpdateWorker(QThread):
    progress = Signal(int, int)
    log = Signal(str)
    done = Signal(bool, str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self.stop_event = threading.Event()

    def run(self):
        try:
            tmp = Path(tempfile.mkdtemp(prefix="dtt_dl_")) / updater.UPDATE_ASSET
            self.log.emit("Đang tải gói cập nhật...")
            updater.download(self.url, tmp, self.progress.emit, self.stop_event)
            self.log.emit("Đang cài đặt...")
            need_pip = updater.apply_update(tmp, self.log.emit)
            if need_pip:
                self.log.emit("Bản mới cần thêm thư viện – đang cài (có thể mất vài phút)...")
                if not updater.install_requirements(self.log.emit):
                    self.done.emit(False, "Cài thư viện thất bại – xem nhật ký bên trên.")
                    return
            self.done.emit(True, "")
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, str(e))


def _logo(size=56):
    lb = QLabel()
    if ICON_PATH.exists():
        lb.setPixmap(QPixmap(str(ICON_PATH)).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    return lb


class UpdateDialog(QDialog):
    def __init__(self, parent=None, info=None):
        super().__init__(parent)
        self.setWindowTitle("Cập nhật – " + APP_NAME)
        self.resize(560, 460)
        self.info = info
        self.worker = None
        self.checker = None
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(_logo(52))
        self.title = QLabel("Đang kiểm tra bản mới...")
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        self.sub = QLabel(f"Phiên bản hiện tại: v{APP_VERSION}")
        self.sub.setObjectName("cardHint")
        tv = QVBoxLayout()
        tv.addWidget(self.title)
        tv.addWidget(self.sub)
        top.addLayout(tv, 1)
        v.addLayout(top)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        v.addWidget(self.notes, 1)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        v.addWidget(self.bar)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumHeight(110)
        self.logbox.setVisible(False)
        v.addWidget(self.logbox)
        row = QHBoxLayout()
        self.b_web = QPushButton("🌐 Trang tải về")
        self.b_web.clicked.connect(self.open_web)
        self.b_close = QPushButton("Để sau")
        self.b_close.clicked.connect(self.reject)
        self.b_update = QPushButton("⬇  Cập nhật ngay")
        self.b_update.setObjectName("primary")
        self.b_update.setEnabled(False)
        self.b_update.clicked.connect(self.start_update)
        row.addWidget(self.b_web)
        row.addStretch(1)
        row.addWidget(self.b_close)
        row.addWidget(self.b_update)
        v.addLayout(row)
        if info is None:
            self.checker = UpdateChecker()
            self.checker.result.connect(self.show_info)
            self.checker.start()
        else:
            self.show_info(info, "")

    def show_info(self, info, err):
        self.info = info
        if info is None:
            self.title.setText("Không kiểm tra được bản mới")
            self.notes.setMarkdown(f"Lỗi: `{err}`\n\nKiểm tra kết nối Internet rồi thử lại, "
                                   f"hoặc mở trang tải về: {updater.RELEASES_URL}")
            return
        if not info.get("version"):
            self.title.setText("Chưa có bản phát hành nào trên GitHub")
            self.notes.setMarkdown(f"Trang dự án: {GITHUB_URL}")
            return
        if not info["newer"]:
            self.title.setText(f"✅ Bạn đang dùng bản mới nhất (v{APP_VERSION})")
            self.sub.setText(f"Bản mới nhất trên GitHub: {info['tag']}  •  {info.get('published', '')}")
            self.notes.setMarkdown(info.get("notes") or "")
            self.b_close.setText("Đóng")
            return
        self.title.setText(f"🎉 Có bản mới {info['tag']}")
        self.sub.setText(f"Hiện tại: v{APP_VERSION}  →  Mới: {info['tag']}  •  {info.get('published', '')}")
        self.notes.setMarkdown(info.get("notes") or "_(Không có ghi chú)_")
        if info.get("app_update"):
            size = info["app_update"].get("size", 0) / 1024
            self.b_update.setText(f"⬇  Cập nhật ngay ({size:.0f} KB)")
            self.b_update.setEnabled(True)
        else:
            self.b_update.setText("Mở trang tải bản mới")
            self.b_update.setEnabled(True)

    def open_web(self):
        url = (self.info or {}).get("url") or updater.RELEASES_URL
        QDesktopServices.openUrl(QUrl(url))

    def start_update(self):
        if not self.info or not self.info.get("app_update"):
            self.open_web()
            return
        self.b_update.setEnabled(False)
        self.b_close.setEnabled(False)
        self.bar.setVisible(True)
        self.logbox.setVisible(True)
        self.worker = UpdateWorker(self.info["app_update"]["url"])
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self.logbox.appendPlainText)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_progress(self, done, total):
        if total:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(done * 100 / total))
        else:
            self.bar.setRange(0, 0)

    def _on_done(self, ok, err):
        self.b_close.setEnabled(True)
        if not ok:
            self.bar.setVisible(False)
            QMessageBox.warning(self, "Cập nhật lỗi", f"Không cập nhật được:\n{err}\n\n"
                                "Bạn có thể tải bản mới thủ công ở trang tải về.")
            self.b_update.setEnabled(True)
            return
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        if QMessageBox.question(self, "Đã cập nhật",
                                f"Đã cập nhật lên {self.info['tag']}.\nKhởi động lại app ngay bây giờ?") \
                == QMessageBox.Yes:
            updater.restart_app()
            QApplication.instance().quit()
        else:
            self.accept()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            e.ignore()
            return
        super().closeEvent(e)


class AboutDialog(QDialog):
    def __init__(self, parent=None, gpu_text=""):
        super().__init__(parent)
        self.setWindowTitle("Giới thiệu")
        self.setFixedWidth(460)
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 24, 26, 20)
        v.setSpacing(10)
        v.addWidget(_logo(84), 0, Qt.AlignHCenter)
        t = QLabel(f"{APP_NAME}")
        t.setObjectName("appTitle")
        t.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        b = QLabel(f"v{APP_VERSION} by {APP_AUTHOR}")
        b.setObjectName("versionBadge")
        b.setAlignment(Qt.AlignCenter)
        b.setFixedHeight(22)
        v.addWidget(b, 0, Qt.AlignHCenter)
        txt = QLabel(
            "Dịch truyện tranh <b>Trung / Nhật / Anh → Việt</b>: nhận dạng chữ, dịch, xoá chữ gốc "
            "và vẽ chữ Việt vừa khít bóng thoại.<br><br>"
            "• OCR: EasyOCR, manga-ocr (GPU)<br>"
            "• Dịch: HachimiMT, NLLB-200, Opus-MT (chạy trên máy) hoặc Google GTX<br>"
            f"• Bản: {'Portable' if IS_PORTABLE else 'Cài đặt'}{('  •  ' + gpu_text) if gpu_text else ''}<br><br>"
            f"<a style='color:#a78bfa' href='{GITHUB_URL}'>{GITHUB_URL}</a>")
        txt.setWordWrap(True)
        txt.setOpenExternalLinks(True)
        txt.setObjectName("cardHint")
        v.addWidget(txt)
        ok = QPushButton("Đóng")
        ok.clicked.connect(self.accept)
        v.addWidget(ok, 0, Qt.AlignRight)
