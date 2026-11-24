"""Thư viện font: font kèm app (thư mục fonts/, giấy phép OFL) + font người dùng thêm vào đó.
Tự kiểm tra font có đủ chữ có dấu tiếng Việt không (thiếu dấu -> chữ hiện ô vuông)."""
from pathlib import Path

from PIL import ImageFont

from .paths import APP_DIR

FONTS_DIR = APP_DIR / "fonts"
FONT_EXT = (".ttf", ".otf", ".ttc")
DEFAULT_FONT_FILE = "BeVietnamPro-Bold.ttf"
VI_CHARS = ("ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ"
            "ĂÂĐÊÔƠƯÀẢÃÁẠẰẲẴẮẶẦẨẪẤẬÈẺẼÉẸỀỂỄẾỆÌỈĨÍỊÒỎÕÓỌỒỔỖỐỘỜỞỠỚỢÙỦŨÚỤỪỬỮỨỰỲỶỸÝỴ")
# tên hiển thị đẹp cho font kèm app
NICE = {
    "BeVietnamPro-Bold": "Be Vietnam Pro – đậm (mặc định)",
    "BeVietnamPro-SemiBold": "Be Vietnam Pro – vừa",
    "Mali-Bold": "Mali – tròn, kiểu truyện tranh",
    "Mali-SemiBold": "Mali – tròn, mảnh hơn",
    "Itim-Regular": "Itim – viết tay mềm",
    "Pangolin-Regular": "Pangolin – viết tay",
    "PatrickHand-Regular": "Patrick Hand – viết tay",
    "Sriracha-Regular": "Sriracha – viết tay nghiêng",
    "Mansalva-Regular": "Mansalva – bút lông (SFX)",
    "FuzzyBubbles-Bold": "Fuzzy Bubbles – nét tròn",
    "Bangers-Regular": "Bangers – hét, hành động",
    "VinaSans-Regular": "Vina Sans – chữ cao, hẹp",
    "SigmarOne-Regular": "Sigmar One – rất đậm (SFX)",
    "Bungee-Regular": "Bungee – khối vuông (SFX)",
    "ChakraPetch-Bold": "Chakra Petch – kỹ thuật",
}
_vi_cache = {}


def list_fonts():
    """[(tên hiển thị, đường dẫn)] – font mặc định đứng đầu."""
    out = []
    if FONTS_DIR.is_dir():
        for p in sorted(FONTS_DIR.iterdir(), key=lambda x: x.name.lower()):
            if p.suffix.lower() in FONT_EXT:
                out.append((NICE.get(p.stem, p.stem), str(p)))
    out.sort(key=lambda t: (Path(t[1]).name != DEFAULT_FONT_FILE, t[0].lower()))
    return out


def vi_missing(path: str) -> str:
    """Các chữ tiếng Việt mà font KHÔNG có (so với glyph '.notdef' – ô vuông). Rỗng = đủ dấu."""
    try:
        key = (path, Path(path).stat().st_mtime)
    except OSError:
        return VI_CHARS
    if key in _vi_cache:
        return _vi_cache[key]
    try:
        f = ImageFont.truetype(path, 32)
        nd = f.getmask("")  # ký tự vùng riêng -> gần như chắc chắn là glyph .notdef
        nd_sig = (nd.size, bytes(nd))
        miss = []
        for ch in VI_CHARS:
            m = f.getmask(ch)
            if m.size == (0, 0) or (m.size, bytes(m)) == nd_sig:
                miss.append(ch)
        res = "".join(miss)
    except Exception:  # noqa: BLE001
        res = VI_CHARS
    _vi_cache[key] = res
    return res
