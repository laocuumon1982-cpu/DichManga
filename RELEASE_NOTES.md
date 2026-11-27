## Dịch Truyện Tranh v2.2.0 by Duy Anh

Dịch truyện tranh **Trung · Nhật · Hàn · Anh → Tiếng Việt**, chạy trên máy (GPU NVIDIA hoặc CPU).

### ⬇️ Chọn bản tải
| Bản | File | Máy |
|---|---|---|
| **GPU** (khuyên dùng) | `…_Portable_GPU.7z.001`, `.7z.002`, … | NVIDIA GTX 16xx / RTX 20xx trở lên |
| **CPU** | `…_Portable_CPU.zip` | Không có card NVIDIA |

- **Bản GPU**: tải **tất cả** các phần `.7z.00x` vào cùng thư mục → chuột phải file **`.7z.001`** → 7-Zip → *Extract Here*.
- Mở **`DichTruyenTranh.exe`**. Lần đầu dịch app tự tải model (cần Internet).
- `DichTruyenTranh_app_update.zip` là gói cho nút **Cập nhật** trong app – không cần tải tay.

### ✨ v2.2.0 – Manhwa tiếng Hàn, nhiều chương, kịch bản, soát lỗi, logo nhóm dịch
- **🇰🇷 Tiếng Hàn (manhwa)**: đọc chữ Hàn, dịch bằng NLLB-200 (chạy trên máy), GTX hoặc AI. Chọn **thứ tự đọc** ô thoại: tự động / phải → trái (manga) / trái → phải (manhwa, comic).
- **📚 Dịch nhiều chương một lượt**: nút *Nhiều chương* (chọn thư mục chứa các chương) hoặc kéo thả nhiều thư mục / file vào cửa sổ – app dịch lần lượt, mỗi chương một thư mục kết quả.
- **🗜 Truyện nén .cbz / .zip**: mở trực tiếp, và **đóng gói kết quả thành .cbz** (đọc bằng Tachiyomi/Mihon, CDisplayEx, Komga…).
- **👥 Xưng hô nhân vật** (F6): khai báo từng cặp A ↔ B (A xưng gì, gọi B là gì…), có sẵn mẫu *Anh – Em, Ta – Ngươi, Sư phụ – Đồ nhi, Tớ – Cậu…* → AI dịch đúng vai vế cả chương.
- **✨ Mẫu văn phong** cho AI theo thể loại: tiên hiệp, học đường, shounen, manhwa hiện đại, ngôn tình, kinh dị, hài.
- **📥 Kịch bản**: tự xuất `_kich_ban.tsv` / `_kich_ban.txt`; **nhập kịch bản** (bản dịch làm sẵn hoặc nhóm dịch sửa) từ Excel, TSV, CSV, TXT, Word (.docx), JSON → tự điền vào đúng ô và vẽ lại (Ctrl+I).
- **🧽 Chế độ Chỉ xoá chữ**: xuất bản RAW sạch (không dịch) – sau đó nhập kịch bản để lồng chữ.
- **☑ Soát lỗi cả chương** (F7): 10 loại lỗi – chưa dịch, còn chữ gốc, AI trả thừa chữ, tràn khung, câu quá dài, dấu câu, lặp từ, thuật ngữ chưa đúng bảng, ngoặc lẻ… lọc theo mức độ, bấm đúp mở đúng ô. **🪄 Tự sửa dấu câu** (F8).
- **🔍 Tìm & thay thế cả chương** (Ctrl+H): khớp trọn từ, phân biệt hoa/thường, regex, xem trước từng ô rồi mới thay.
- **🏷 Logo nhóm dịch**: đóng dấu logo PNG lên mọi trang / trang đầu / trang cuối, tự chọn góc trống không đè bóng thoại; tên nhóm ghi vào file .cbz.
- **📜 Cắt / ghép webtoon** (F12): ghép thành 1 ảnh dài, hoặc cắt lại theo chiều cao chọn – **không bao giờ cắt ngang bóng thoại**.
- **⌨ Phím tắt** (F1): Ctrl+S lưu & vẽ lại, Alt+←/→ chuyển trang, Ctrl+Enter bắt đầu dịch…
- Tải model xoá chữ LaMa **tải tiếp được** khi bị ngắt mạng giữa chừng.

### ⚡ v2.1.3 – AI dịch không còn "đứng" ở 45%
- Thanh tiến độ **chạy liên tục trong lúc AI đang viết** (hiện số ký tự đã viết, tốc độ ký tự/giây), không còn đứng yên ở 45%.
- AI chạy trên máy (Ollama / LM Studio): trước khi dịch, app **giải phóng VRAM** của model đọc chữ; model xoá chữ LaMa nạp **sau** khi AI dịch xong → model AI nạp trọn vào GPU, dịch nhanh hơn nhiều.
- Cảnh báo khi model AI **không nạp hết vào GPU** (thiếu VRAM, phải chạy một phần bằng CPU → rất chậm), gợi ý dùng model nhỏ hơn.
- Chia chương thành phần nhỏ hơn cho model chạy máy; bấm **Dừng** là dừng ngay cả khi AI đang viết.

### 🛠 v2.1.2 – Sửa lỗi không tải được model Ollama
- Nút **⬇ Tải model** chạy được với cả Ollama bản cũ (gửi tên model theo cả hai kiểu API).
- Tải qua API lỗi thì **tự chuyển sang lệnh `ollama pull`** (cách tải chuẩn của Ollama), vẫn có % tiến độ.
- Tải xong tự kiểm tra model đã có thật; lỗi thì báo đầy đủ nguyên nhân + cách tải tay, ghi vào Nhật ký.

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
