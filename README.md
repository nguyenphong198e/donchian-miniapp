# Donchian H4 · Telegram Mini App (paper)

Bảng theo dõi cho chiến lược Donchian của bot máy 1, chạy miễn phí trên GitHub. Không cần API key Binance, không đụng tới tài khoản thật.

- `engine/donchian_paper.py`: mỗi giờ tải nến H4/H1 và funding công khai của Binance Futures, tính lại toàn bộ lệnh paper từ `PAPER_START`, ghi `docs/data/dashboard.json`. Luật giống hệt `bot/trendmode.py` của máy 1. Đã đối chiếu với các lệnh thật SOL, NEAR, AVAX, BNB tháng 9–10/2026: giá vào và giá ra khớp.
- `docs/index.html`: giao diện Mini App gồm vốn, đường vốn, vị thế mở (giá Binance cập nhật 5 giây/lần), radar khoảng cách tới đỉnh 100 nến, lịch sử lệnh. Tự lấy màu theo theme Telegram.
- `.github/workflows/donchian_paper.yml`: chạy engine mỗi giờ và commit file JSON.

## Cài đặt (khoảng 5 phút)

1. Tạo repo GitHub **public** mới (ví dụ `donchian-miniapp`) và đẩy toàn bộ thư mục này lên nhánh `main`.
2. **Settings → Pages**: Source `Deploy from a branch`, branch `main`, folder `/docs`. Link sẽ có dạng `https://<user>.github.io/donchian-miniapp/`.
3. **Settings → Secrets and variables → Actions**:
   - Secrets (không bắt buộc, chỉ cần nếu muốn nhận tin báo lệnh paper): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Nên dùng một bot riêng cho paper, đừng dùng chung bot đang trade tiền thật.
   - Variables: `WEBAPP_URL` = link Pages ở bước 2. Có thể thêm `RISK_PCT` (mặc định `2`) và `PAPER_START` (mặc định `2026-01-01`).
4. **Actions → Donchian H4 Paper → Run workflow** để chạy lần đầu.
5. Gắn vào Telegram: chat với `@BotFather` → `/mybots` → chọn bot → **Bot Settings → Menu Button** → dán link Pages. Từ đó mở bot là có nút mở bảng.

## Chạy thử trên máy

```
pip install numpy pandas requests
python engine/donchian_paper.py
python -m http.server 8765 --directory docs
```

Mở `http://localhost:8765`.

## Lưu ý

- Đây là mô phỏng. Lệnh có nhãn **QUÁ KHỨ** được tính lại từ dữ liệu trước ngày bật bot. Giá thoát lấy đúng mức stop, nên lệnh thật sẽ kém hơn một chút vì trượt giá.
- Mỗi lần chạy, engine tính lại toàn bộ lịch sử, nên lỡ một lần chạy cũng không làm sai dữ liệu.
- Ngày giờ hiển thị theo UTC.
