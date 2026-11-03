"""Các widget dùng chung cho giao diện."""
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)


class Card(QFrame):
    """Khung bo tròn có tiêu đề + dòng gợi ý."""

    def __init__(self, title: str, hint: str = "", icon: str = ""):
        super().__init__()
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 16)
        self.lay.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel(f"{icon}  {title}" if icon else title)
        t.setObjectName("cardTitle")
        head.addWidget(t)
        head.addStretch(1)
        self.lay.addLayout(head)
        self.head = head
        if hint:
            h = QLabel(hint)
            h.setObjectName("cardHint")
            h.setWordWrap(True)
            self.lay.addWidget(h)

    def add(self, w, stretch=0):
        if isinstance(w, QWidget):
            self.lay.addWidget(w, stretch)
        else:
            self.lay.addLayout(w, stretch)
        return w


def field(label: str, widget) -> QWidget:
    """Nhãn nhỏ phía trên + ô nhập."""
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    lb = QLabel(label)
    lb.setObjectName("fieldLabel")
    v.addWidget(lb)
    if isinstance(widget, QWidget):
        v.addWidget(widget)
    else:
        v.addLayout(widget)
    return box


class ImageView(QScrollArea):
    """Xem ảnh vừa chiều ngang khung (cuộn dọc cho trang webtoon dài)."""
    scrolled = Signal(float)

    def __init__(self, placeholder="Chưa có ảnh"):
        super().__init__()
        self.setObjectName("imageView")
        self.setWidgetResizable(True)
        self.placeholder = placeholder
        self.label = QLabel(placeholder)
        self.label.setObjectName("imgPlaceholder")
        self.label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setWidget(self.label)
        self._pix = None
        self._sync = False
        self.verticalScrollBar().valueChanged.connect(self._emit_scroll)

    def set_image(self, path):
        self._pix = None
        if path and Path(path).exists():
            pix = QPixmap(str(path))
            if not pix.isNull():
                self._pix = pix
        if self._pix is None:
            self.label.setPixmap(QPixmap())
            self.label.setText(self.placeholder)
            self.label.setAlignment(Qt.AlignCenter)
        else:
            self.label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self._rescale()

    def _rescale(self):
        if self._pix:
            w = max(100, self.viewport().width() - 2)
            self.label.setPixmap(self._pix.scaledToWidth(w, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def _emit_scroll(self, v):
        if self._sync:
            return
        sb = self.verticalScrollBar()
        self.scrolled.emit(v / sb.maximum() if sb.maximum() else 0.0)

    def scroll_to_ratio(self, r: float):
        sb = self.verticalScrollBar()
        self._sync = True
        sb.setValue(int(r * sb.maximum()))
        self._sync = False


class CompareView(QWidget):
    """Ảnh gốc và ảnh đã dịch đặt cạnh nhau, cuộn đồng bộ."""

    def __init__(self):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 8, 8, 8)
        h.setSpacing(8)
        self.src = ImageView("Ảnh gốc")
        self.out = ImageView("Chưa dịch trang này")
        for cap, view in (("ẢNH GỐC", self.src), ("ĐÃ DỊCH", self.out)):
            col = QVBoxLayout()
            col.setSpacing(4)
            lb = QLabel(cap)
            lb.setObjectName("viewCaption")
            col.addWidget(lb)
            col.addWidget(view, 1)
            h.addLayout(col, 1)
        self.src.scrolled.connect(self.out.scroll_to_ratio)
        self.out.scrolled.connect(self.src.scroll_to_ratio)

    def set_images(self, src, out):
        self.src.set_image(src)
        self.out.set_image(out)


def thumb_size() -> QSize:
    return QSize(54, 76)
