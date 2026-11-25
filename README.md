# MEKVRO · Telegram Mini App (tài khoản thật + chạy giấy, đã mã hóa)

Bảng theo dõi bot Donchian H4 MEKVRO. Trang nằm trên GitHub Pages công khai, nhưng **mọi số liệu đều được mã hóa**:
người ngoài mở link chỉ thấy ô nhập mật khẩu.

- `engine/donchian_paper.py`: tải nến H4/H1 và funding của Binance Futures, tính lại toàn bộ lệnh chạy giấy từ `PAPER_START`,
  ghi `docs/data/dashboard.json` (chỉ ở máy, không đưa lên GitHub). Luật giống hệt `bot/trendmode.py` của bot, kể cả lọc
  volume nến phá đỉnh (`VOL_MULT`, mặc định 1.5, áp dụng từ 2026-11-25).
- `MEKVRO_bOT/scripts/export_live.py`: ảnh chụp tài khoản thật, **chỉ đọc**: sổ của bot (`data/auto_state.json`,
  `data/trend_book.json`) cùng số dư và vị thế trên Binance. Ghi vào `private/live.json`.
- `engine/seal.py`: mã hóa cả hai thành `docs/data/vault.json` (PBKDF2-SHA256 310.000 vòng + AES-256-GCM) bằng mật khẩu ở
  `private/password.txt`. Đây là file số liệu duy nhất được đẩy lên GitHub.
- `docs/index.html`: Mini App. Nhập mật khẩu một lần (Telegram nhớ), giải mã ngay trên điện thoại bằng WebCrypto.
  Hai tab: **Tài khoản thật** (số dư, lãi/lỗ, đường vốn, vị thế, lịch sử lệnh thật) và **Chạy giấy**. Giá nhảy theo
  Binance mỗi 5 giây.
- `scripts/update_paper.bat`: chạy cả ba bước trên rồi commit và đẩy `vault.json`. Tác vụ Windows "MEKVRO Paper Update"
  gọi nó mỗi giờ, chạy ẩn qua `scripts/update_paper_hidden.vbs`. Nhật ký: `scripts/update_paper.log`.

## Đổi mật khẩu

Sửa `private/password.txt` (ít nhất 12 ký tự), chạy `scripts\update_paper.bat`, rồi trên mini app bấm
"Khóa lại / đổi mật khẩu" và nhập mật khẩu mới.

## Chạy thử trên máy

```
python engine/donchian_paper.py
python engine/seal.py
python -m http.server 8765 --directory docs
```

Mở `http://localhost:8765`.

## Lưu ý

- Thư mục `private/` và `docs/data/dashboard.json` nằm trong `.gitignore`: không bao giờ đưa lên GitHub.
- Chạy giấy là mô phỏng. Lệnh có nhãn **QUÁ KHỨ** được tính lại từ dữ liệu trước ngày bật bot. Giá thoát lấy đúng mức stop.
- Ngày giờ hiển thị theo UTC.
