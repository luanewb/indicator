# ⚡ Binance Futures Long/Short Tracker Bot (`v2.0.3`)

Hệ thống Bot giao dịch **Binance Futures** theo đúng thuật toán của chỉ báo **Long/Short Tracker v2.0.3**, tích hợp **Nút Đặt Lệnh & Phím tắt (`Alt + B`) ngay trên TradingView** và **Bảng Quản Lý Lệnh kiểu MT5 (MetaTrader 5)**.

---

## 🚀 Tính năng chính

1. **Nút Đặt Lệnh & Phím tắt `Alt + B` ngay trên TradingView**:
   - Đọc trực tiếp thông số `Symbol`, `Entry`, `Stop Loss (SL)`, `Take Profit (TP)`, `Volume`, `Risk %`, `R:R` khi bạn kéo thả chỉ báo `Long/Short Tracker v2.0.3` trên biểu đồ TradingView.
   - Bấm **`⚡ ĐẶT LỆNH LIMIT (Alt+B)`** hoặc ấn phím tắt **`Alt + B`** để gửi thẳng lệnh sang Bot (hoặc **`Alt + M`** để vào lệnh Market ngay kèm SL/TP).
2. **Tự động tính toán chuẩn Long/Short Tracker**:
   - Tự xác định chiều **LONG** (`SL < Entry`) hoặc **SHORT** (`SL > Entry`).
   - Tự tính **Take Profit (TP)** theo tỷ lệ `R:R` (`1:2`, `1:3`, hoặc tùy chỉnh).
   - Tự tính **Khối lượng (Volume)** theo `% Risk` và tự động làm tròn theo đúng `tickSize` & `stepSize` của từng cặp trên Binance Futures.
3. **Giao diện Quản Lý Lệnh kiểu MT5 (`http://localhost:8000`)**:
   - **3 Chế độ chạy**: `PAPER LIVE` (mô phỏng khớp lệnh trên giá thật Binance Futures, không cần API Key), `BINANCE TESTNET` (Demo), và `BINANCE MAINNET` (Tiền thật).
   - **Tab Positions (`ACTIVE`)**: Theo dõi `Floating PnL ($ & R)`, `MFE (+R cao nhất)` / `MAE (-R âm sâu nhất)`, dời SL về Hòa vốn (**`🛡️ BE`**), chốt lời một phần (**`50%`**), sửa SL/TP (**`✏️ Sửa`**), đảo chiều vị thế (**`🔄`**), đóng vị thế Market (**`✖ Đóng`**) hoặc **Close All**.
   - **Tab Pending Orders (`WAITING`)**: Quản lý các lệnh chờ Limit gửi từ TradingView, hỗ trợ **Khớp Market ngay**, **Sửa giá Entry/SL/TP**, hoặc **Hủy lệnh (`✖ Hủy`)**.

---

## 🛠️ Hướng dẫn sử dụng nhanh

### Bước 1: Khởi động Bot & MT5 Dashboard
Chạy file [`run_bot.bat`](file:///d:/app/indicator/bot-trade/run_bot.bat) (hoặc mở Terminal tại thư mục `bot-trade`):
```powershell
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```
Sau đó mở trình duyệt tại: **`http://localhost:8000`**

### Bước 2: Cập nhật Indicator trên TradingView lên `v2.0.3`
Copy toàn bộ mã nguồn trong file [`long-short-tracker.txt`](file:///d:/app/indicator/bot-trade/long-short-tracker.txt) dán vào **Pine Editor** trên TradingView và lưu lại.

### Bước 3: Cài Nút Đặt Lệnh (`Alt + B`) lên TradingView
1. Mở Chrome / Edge / Brave và truy cập: `chrome://extensions`
2. Bật **Developer mode (Chế độ dành cho nhà phát triển)** ở góc trên bên phải.
3. Bấm **Load unpacked (Tải tiện ích đã giải nén)** và chọn thư mục:
   `d:\app\indicator\bot-trade\tradingview-extension`
4. Mở lại biểu đồ TradingView, kéo thả `Entry` & `SL` của chỉ báo `Long/Short Tracker v2.0.3` và nhấn **`Alt + B`** để đặt lệnh!

