<p align="center">
  <img src="docs/logo.png" width="120" alt="logo">
</p>

<h1 align="center">Dịch Truyện Tranh v2.0</h1>
<p align="center"><b>by Duy Anh</b> — Dịch truyện tranh <b>Trung · Nhật · Anh → Tiếng Việt</b> ngay trên máy, chạy GPU</p>

<p align="center">
  <a href="https://github.com/laocuumon1982-cpu/DichManga/releases/latest"><img alt="Tải về" src="https://img.shields.io/github/v/release/laocuumon1982-cpu/DichManga?label=T%E1%BA%A3i%20v%E1%BB%81&style=for-the-badge&color=8b5cf6"></a>
  <img alt="Windows" src="https://img.shields.io/badge/Windows-10%20%2F%2011-0ea5e9?style=for-the-badge">
  <img alt="GPU" src="https://img.shields.io/badge/NVIDIA-CUDA-22c55e?style=for-the-badge">
</p>

App tự **nhận dạng chữ** trong khung thoại, **dịch**, **xoá chữ gốc** và **vẽ chữ Việt vừa khít bóng thoại**. Nguồn là thư mục ảnh (đánh số trang) hoặc file PDF – kéo thả vào cửa sổ là xong.

![Giao diện](docs/screenshot.png)

## ⬇️ Tải về (bản Portable – không cần cài đặt)

Vào **[Releases](https://github.com/laocuumon1982-cpu/DichManga/releases/latest)** và chọn:

| Bản | File | Dùng cho |
|---|---|---|
| **GPU** (khuyên dùng) | `DichTruyenTranh_v2.0_Portable_GPU.7z.001`, `.002`… | Card NVIDIA **GTX 16xx / RTX 20xx trở lên** – nhanh nhất |
| **CPU** | `DichTruyenTranh_v2.0_Portable_CPU.zip` | Máy không có card NVIDIA |

**Bản GPU** được chia nhiều phần (GitHub giới hạn 2 GB/file): tải **tất cả** các phần `.7z.001`, `.7z.002`… vào cùng một thư mục, rồi dùng [7-Zip](https://www.7-zip.org/) bấm chuột phải vào file **`.7z.001`** → *Extract Here*.

Sau đó mở **`DichTruyenTranh.exe`**. Lần dịch đầu tiên app tự tải model (cần Internet), lưu trong thư mục `models\` – chép cả thư mục sang USB / máy khác vẫn chạy được.

> Nếu app không mở: cài [Microsoft Visual C++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe), hoặc chạy `Chay_xem_loi.bat` để xem lỗi.

### 🔄 Cập nhật
Bấm nút **⟳ Cập nhật** ở góc trên app. App tự kiểm tra bản mới trên GitHub; khi có bản mới, nút đổi thành **⬆ Có bản mới** – bấm để tải gói cập nhật nhỏ (vài trăm KB) và khởi động lại, không cần tải lại cả bản portable.

## ✨ Tính năng
- **Kéo thả** thư mục ảnh / file PDF / dự án cũ vào cửa sổ.
- **OCR trên GPU**: EasyOCR (Trung, Anh), manga-ocr (Nhật, đọc tốt chữ dọc). Ảnh webtoon dài tự cắt đoạn.
- **Dịch chạy trên máy**, theo lô fp16 trên GPU (CPU dùng CTranslate2 INT8):

  | Ngôn ngữ | Bộ dịch |
  |---|---|
  | Trung | **HachimiMT-60** (mặc định), HachimiMT-30, HachimiMT-60-QT (giọng convert ta/ngươi/hắn), NLLB-200 |
  | Nhật | **NLLB-200 600M** (mặc định), Opus-MT ja→vi |
  | Anh | **GTX Google** |
  | Tất cả | GTX Google (online, miễn phí) – cũng dùng để dịch bù câu bị bỏ trống |
- **Vẽ chữ vừa bóng thoại**: lấy đúng hình lòng bóng (tròn, elip, dọc, có đuôi, viền hở, nền lưới chấm), chữ chia đều các dòng, chỉnh được **cỡ chữ tối đa**.
- **3 công đoạn chạy song song** (đọc chữ → dịch → vẽ), hiển thị **% tiến độ, giây/trang, thời gian còn lại**.
- Xem **gốc / đã dịch cạnh nhau** (cuộn đồng bộ), **sửa bản dịch** trong bảng rồi vẽ lại, đổi font / cỡ chữ / IN HOA và **vẽ lại tất cả** không cần dịch lại.
- Xuất ảnh JPG/PNG, **gộp PDF**, file `ban_dich.txt` (gốc + bản dịch).

## 🛠 Chạy từ mã nguồn
1. Cài **Python 3.11 hoặc 3.12** (tick *Add python.exe to PATH*), cập nhật driver NVIDIA.
2. Chạy `install.bat` – tự nhận card và cài PyTorch phù hợp (RTX → CUDA 12.8, GTX 9xx/10xx → CUDA 12.6, không có NVIDIA → CPU). Tạo lối tắt **Dich Truyen Tranh** ngoài Desktop.
3. Mở bằng lối tắt hoặc `run.bat`.

Tự tạo bản portable trên máy: `build_portable.bat` (tự nhận GPU, hỏi tải sẵn model) – kết quả ở `dist\`.

## 📁 Kết quả
- `0001.jpg, 0002.jpg …` – các trang đã dịch
- `<tên truyện>_vi.pdf` – PDF gộp
- `ban_dich.txt` – chữ gốc + bản dịch theo trang
- `_work\project.json` – mở lại bằng **Dự án cũ** để sửa tiếp

## ⚠️ Giới hạn
- Chữ hiệu ứng (SFX) vẽ tay, chữ nghiêng mạnh có thể bị bỏ sót / đọc sai – sửa tay trong bảng.
- GTX là endpoint không chính thức của Google, có thể bị chặn tạm thời khi dịch rất nhiều trang liên tục.

## 🙏 Cảm ơn
[HachimiMT](https://huggingface.co/ngocdang83) (ngocdang83, CC-BY-4.0) · [NLLB-200](https://huggingface.co/facebook/nllb-200-distilled-600M) (Meta) · [Opus-MT](https://huggingface.co/Helsinki-NLP/opus-mt-ja-vi) · [EasyOCR](https://github.com/JaidedAI/EasyOCR) · [manga-ocr](https://github.com/kha-white/manga-ocr) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [PySide6](https://doc.qt.io/qtforpython-6/)
