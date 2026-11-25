## Dịch Truyện Tranh v2.1.1 by Duy Anh

Dịch truyện tranh **Trung · Nhật · Anh → Tiếng Việt**, chạy trên máy (GPU NVIDIA hoặc CPU).

### ⬇️ Chọn bản tải
| Bản | File | Máy |
|---|---|---|
| **GPU** (khuyên dùng) | `…_Portable_GPU.7z.001`, `.7z.002`, … | NVIDIA GTX 16xx / RTX 20xx trở lên |
| **CPU** | `…_Portable_CPU.zip` | Không có card NVIDIA |

- **Bản GPU**: tải **tất cả** các phần `.7z.00x` vào cùng thư mục → chuột phải file **`.7z.001`** → 7-Zip → *Extract Here*.
- Mở **`DichTruyenTranh.exe`**. Lần đầu dịch app tự tải model (cần Internet).
- `DichTruyenTranh_app_update.zip` là gói cho nút **Cập nhật** trong app – không cần tải tay.

### 🔌 v2.1.1 – Ollama tự kết nối
- Chọn **AI (LLM) → Ollama** là app **tự tìm và tự mở Ollama**, liệt kê model đã cài và **tự chọn model hợp nhất** (ưu tiên Qwen2.5 14B → Qwen3 → Qwen2.5 7B…). Hết lỗi *404 sai tên model*.
- Chưa có model: bấm **⬇ Tải model** (qwen2.5:14b ~9 GB / qwen2.5:7b ~4.7 GB / qwen3:14b) – có thanh % tiến độ.
- Dịch qua API gốc của Ollama với ngữ cảnh 8192 token (chương dài không bị cắt), giữ model trong VRAM 30 phút cho các lần dịch sau nhanh hơn, tắt chế độ "suy nghĩ" của Qwen3.
- Báo lỗi rõ ràng khi model chưa có.

### ✨ Có gì mới ở v2.1
- **🤖 AI dịch cả chương theo ngữ cảnh**: Ollama / LM Studio chạy trên máy (miễn phí), hoặc DeepSeek / Gemini / OpenAI / Claude (API key của bạn). Gom chữ cả chương, kèm bảng thuật ngữ + văn phong + ghi chú truyện → tên riêng, xưng hô thống nhất.
- **📖 Bảng thuật ngữ** (SQLite): tên riêng cho AI; tự sửa chữ Việt sau khi dịch với mọi bộ dịch; nhập / xuất CSV.
- **🔁 Dịch lại cả chương** không cần đọc chữ / xoá chữ lại.
- **🧽 Xoá chữ bằng AI LaMa (manga)**: chữ trên hình / nền lưới chấm sạch, không còn nhoè.
- **Nhận diện loại ô**: thoại, suy nghĩ, hét, dẫn truyện, chữ trên hình, SFX; tick **Giữ** để giữ nguyên chữ gốc.
- **Tab Tình trạng**: ô chưa dịch / chữ tràn khung, bấm đúp mở đúng trang.
- **15 font tiếng Việt** kèm sẵn có xem trước, cảnh báo font thiếu dấu.
- **Xuất Excel lời thoại** và **PSD 3 lớp** (gốc / nền sạch / chữ dịch).
- GTX bền hơn (thêm đường dự phòng khi Google chặn); tìm bóng thoại chính xác hơn với chữ nhỏ trong bóng to và nền lưới chấm.
- Cài đặt lưu ở `config.json` (sửa tay được), tự nhập cài đặt cũ.

Cập nhật từ v2.0: bấm **⟳ Cập nhật** trong app (tự cài thêm thư viện openpyxl, psd-tools).
