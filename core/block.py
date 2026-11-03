"""Cấu trúc dữ liệu cho một khung chữ (bóng thoại) trên trang truyện."""
from dataclasses import dataclass, field
from statistics import median


@dataclass
class TextBlock:
    x0: int
    y0: int
    x1: int
    y1: int
    lines: list = field(default_factory=list)  # [[x0, y0, x1, y1], ...] từng dòng/cột chữ
    vertical: bool = False
    text: str = ""
    translation: str = ""

    @property
    def w(self) -> int:
        return self.x1 - self.x0

    @property
    def h(self) -> int:
        return self.y1 - self.y0

    def char_size(self) -> int:
        """Ước lượng cỡ một ký tự gốc (px) = cạnh ngắn của mỗi dòng/cột."""
        if not self.lines:
            return max(8, min(self.w, self.h))
        return int(max(8, median(min(r[2] - r[0], r[3] - r[1]) for r in self.lines)))

    @classmethod
    def from_lines(cls, lines, vertical=None):
        x0 = min(r[0] for r in lines)
        y0 = min(r[1] for r in lines)
        x1 = max(r[2] for r in lines)
        y1 = max(r[3] for r in lines)
        if vertical is None:
            ratios = [(r[3] - r[1]) / max(1, r[2] - r[0]) for r in lines]
            if len(lines) == 1:
                vertical = ratios[0] > 1.5
            else:
                vertical = median(ratios) > 1.2
        # Sắp xếp thứ tự đọc: cột dọc đọc phải → trái, dòng ngang đọc trên → dưới
        if vertical:
            lines = sorted(lines, key=lambda r: -(r[0] + r[2]))
        else:
            lines = sorted(lines, key=lambda r: (r[1] + r[3]))
            rows = []  # gom các mảnh cùng hàng (lệch tâm < nửa chiều cao) rồi xếp trái → phải
            for r in lines:
                cy, hh = (r[1] + r[3]) / 2, r[3] - r[1]
                if rows and abs(cy - rows[-1][0]) < 0.5 * max(hh, rows[-1][1]):
                    rows[-1][2].append(r)
                else:
                    rows.append([cy, hh, [r]])
            lines = [r for _, _, row in rows for r in sorted(row, key=lambda q: q[0])]
        return cls(x0, y0, x1, y1, [list(map(int, r)) for r in lines], bool(vertical))

    def to_dict(self) -> dict:
        return {
            "rect": [self.x0, self.y0, self.x1, self.y1],
            "lines": self.lines,
            "vertical": self.vertical,
            "text": self.text,
            "translation": self.translation,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TextBlock":
        x0, y0, x1, y1 = d["rect"]
        return cls(x0, y0, x1, y1, d.get("lines", []), d.get("vertical", False),
                   d.get("text", ""), d.get("translation", ""))
