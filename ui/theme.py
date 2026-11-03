"""Giao diện tối (dark) – tông màu lấy theo icon app (đỏ hồng → tím)."""

C = {
    "bg": "#0e1120",
    "panel": "#151a2d",
    "card": "#1a2036",
    "card2": "#20273f",
    "border": "#2a3150",
    "input": "#11162a",
    "text": "#e7e9f3",
    "muted": "#8e94b0",
    "accent": "#8b5cf6",
    "accent2": "#ec4899",
    "red": "#ef4444",
    "green": "#22c55e",
    "orange": "#f59e0b",
}

QSS = f"""
* {{
    font-family: "Segoe UI", "Inter", "Roboto", "Noto Sans", sans-serif;
    font-size: 13px;
    color: {C['text']};
}}
QMainWindow, QDialog {{ background: {C['bg']}; }}
QWidget#central {{ background: {C['bg']}; }}
QToolTip {{ background: {C['card2']}; color: {C['text']}; border: 1px solid {C['border']}; padding: 6px; border-radius: 6px; }}

/* ---------- thanh tiêu đề ---------- */
QFrame#header {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1b1531, stop:0.55 #171c33, stop:1 #12172b);
    border-bottom: 1px solid {C['border']};
}}
QLabel#appTitle {{ font-size: 20px; font-weight: 700; color: #ffffff; }}
QLabel#appSub {{ color: {C['muted']}; font-size: 12px; }}
QLabel#versionBadge {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {C['red']}, stop:1 {C['accent']});
    color: white; font-weight: 700; font-size: 11px; border-radius: 9px; padding: 2px 9px;
}}
QLabel#chip {{
    background: {C['card2']}; border: 1px solid {C['border']}; border-radius: 13px;
    padding: 4px 12px; color: {C['muted']}; font-size: 12px;
}}
QLabel#chip[state="ok"] {{ color: #86efac; border-color: #1f6b3d; background: #10261b; }}
QLabel#chip[state="warn"] {{ color: #fcd34d; border-color: #6b4f12; background: #241c0c; }}

/* ---------- thẻ (card) ---------- */
QFrame#card {{
    background: {C['card']}; border: 1px solid {C['border']}; border-radius: 14px;
}}
QLabel#cardTitle {{ font-size: 14px; font-weight: 700; color: #ffffff; }}
QLabel#cardHint {{ color: {C['muted']}; font-size: 12px; }}
QLabel#fieldLabel {{ color: {C['muted']}; font-size: 12px; }}
QLabel#sourceInfo {{
    background: {C['input']}; border: 1px dashed {C['border']}; border-radius: 10px;
    padding: 10px; color: {C['muted']};
}}
QLabel#sourceInfo[filled="true"] {{ color: {C['text']}; border-style: solid; border-color: #4c3a8a; }}

/* ---------- ô nhập ---------- */
QLineEdit, QComboBox, QSpinBox {{
    background: {C['input']}; border: 1px solid {C['border']}; border-radius: 8px;
    padding: 6px 10px; min-height: 20px; selection-background-color: {C['accent']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {C['accent']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{
    width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 6px solid {C['muted']}; margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {C['card2']}; border: 1px solid {C['border']}; border-radius: 8px; padding: 4px;
    selection-background-color: #3b2f6b; outline: 0;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QCheckBox {{ spacing: 8px; color: {C['text']}; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px; border: 1px solid {C['border']}; background: {C['input']};
}}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {C['accent2']}, stop:1 {C['accent']});
    border-color: {C['accent']};
}}
QSlider::groove:horizontal {{ height: 6px; background: {C['input']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {C['accent2']}, stop:1 {C['accent']});
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: #ffffff;
    border: 3px solid {C['accent']};
}}

/* ---------- nút ---------- */
QPushButton, QToolButton {{
    background: {C['card2']}; border: 1px solid {C['border']}; border-radius: 9px;
    padding: 7px 14px; color: {C['text']};
}}
QPushButton:hover, QToolButton:hover {{ background: #2a3254; border-color: #3b4470; }}
QPushButton:pressed, QToolButton:pressed {{ background: #232a46; }}
QPushButton:disabled {{ color: #5d6380; background: #171b2d; border-color: #222842; }}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {C['red']}, stop:0.5 {C['accent2']}, stop:1 {C['accent']});
    border: none; border-radius: 12px; color: white; font-size: 15px; font-weight: 700; padding: 12px;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f25c5c, stop:0.5 #f062a8, stop:1 #9b74f8);
}}
QPushButton#primary:disabled {{ background: #2b2f48; color: #7d82a0; }}
QPushButton#danger {{ border-color: #6b2330; color: #fca5a5; }}
QPushButton#danger:hover {{ background: #3a1820; }}
QPushButton#bigSource {{
    background: {C['input']}; border: 1px solid {C['border']}; border-radius: 12px;
    padding: 12px 8px; font-weight: 600; text-align: center;
}}
QPushButton#bigSource:hover {{ border-color: {C['accent']}; background: #1b1c3a; }}
QToolButton#headerBtn {{ background: transparent; border: 1px solid transparent; padding: 6px 12px; border-radius: 8px; }}
QToolButton#headerBtn:hover {{ background: #241f40; border-color: #3b2f6b; }}
QToolButton#headerBtn[update="true"] {{
    color: #ffffff; border-color: #7c3aed;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #be185d, stop:1 #6d28d9);
}}

/* ---------- tiến độ ---------- */
QLabel#bigPercent {{ font-size: 34px; font-weight: 800; color: #ffffff; }}
QLabel#progressText {{ color: {C['muted']}; font-size: 12px; }}
QProgressBar {{
    background: {C['input']}; border: none; border-radius: 5px; height: 10px; max-height: 10px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {C['red']}, stop:0.5 {C['accent2']}, stop:1 {C['accent']});
}}

/* ---------- danh sách trang ---------- */
QListWidget#pageList {{
    background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 12px; padding: 6px; outline: 0;
}}
QListWidget#pageList::item {{ border-radius: 8px; padding: 6px; margin: 2px; color: {C['muted']}; }}
QListWidget#pageList::item:hover {{ background: #1f2540; }}
QListWidget#pageList::item:selected {{ background: #2d2457; color: #ffffff; border: 1px solid #5b44b0; }}

/* ---------- tab ---------- */
QTabWidget::pane {{ border: 1px solid {C['border']}; border-radius: 12px; background: {C['panel']}; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {C['muted']}; padding: 8px 16px; margin-right: 4px;
    border-top-left-radius: 9px; border-top-right-radius: 9px; font-weight: 600;
}}
QTabBar::tab:selected {{ color: #ffffff; background: {C['panel']}; border: 1px solid {C['border']}; border-bottom: none; }}
QTabBar::tab:hover:!selected {{ color: {C['text']}; }}

/* ---------- bảng, log, ảnh ---------- */
QTableWidget {{
    background: {C['panel']}; alternate-background-color: #181d33; border: 1px solid {C['border']};
    border-radius: 10px; gridline-color: {C['border']}; selection-background-color: #2d2457;
}}
QHeaderView::section {{
    background: {C['card2']}; color: {C['muted']}; border: none; border-bottom: 1px solid {C['border']};
    padding: 7px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {C['card2']}; border: none; }}
QPlainTextEdit, QTextBrowser {{
    background: #0b0e1a; border: 1px solid {C['border']}; border-radius: 10px; padding: 8px;
    font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace; font-size: 12px; color: #c9cde0;
}}
QTextBrowser {{ font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 13px; }}
QScrollArea#imageView {{ background: #0b0e1a; border: 1px solid {C['border']}; border-radius: 10px; }}
QScrollArea#imageView > QWidget > QWidget {{ background: #0b0e1a; }}
QLabel#imgPlaceholder {{ color: #545a78; font-size: 14px; }}
QLabel#viewCaption {{ color: {C['muted']}; font-size: 12px; font-weight: 600; padding: 2px 4px; }}
QScrollArea#sidebar {{ background: transparent; border: none; }}
QScrollArea#sidebar > QWidget > QWidget {{ background: transparent; }}

/* ---------- thanh cuộn mảnh ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2e3556; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #424b78; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2e3556; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QStatusBar {{ background: {C['panel']}; border-top: 1px solid {C['border']}; color: {C['muted']}; }}
QStatusBar QLabel {{ color: {C['muted']}; padding: 0 8px; }}
QMessageBox {{ background: {C['card']}; }}
QMessageBox QLabel {{ color: {C['text']}; }}
"""
