# Ứng dụng Giám sát dịch bệnh — phiên bản 0.4.0

Ứng dụng desktop Windows dùng **Python + SQLite + PyQt6** để quản lý ca bệnh, ổ dịch, lọc trùng và chia sẻ dữ liệu trong mạng LAN.

## Cài đặt

Tải `GiamSatDichBenh-Setup-v0.4.0.exe` trong GitHub Releases. Người dùng không cần cài Python hoặc tự build.

Bộ cài yêu cầu chọn một trong ba chế độ:

1. **Máy đơn lẻ**: ứng dụng và CSDL chạy trên một máy, không chia sẻ LAN.
2. **Máy trạm**: nhập địa chỉ máy chủ dạng `http://192.168.1.10:8765` và mật khẩu nếu máy chủ có đặt.
3. **Máy chủ**: tự tạo CSDL trên máy chủ, mở API HTTP trong LAN và hiện thêm tab **Server**. Mật khẩu để trống nghĩa là không yêu cầu mật khẩu.

Máy trạm không mở trực tiếp file SQLite. Mọi thao tác được gửi qua API của máy chủ để tránh nhiều máy cùng ghi trực tiếp vào một file `.db`.

## Vị trí dữ liệu

Bản phát hành không chứa dữ liệu mẫu hoặc dữ liệu thật. Dữ liệu được tạo sau khi cài tại:

```text
%LOCALAPPDATA%\CDC_HaiPhong\GiamSatDichBenh\
├─ deployment.json
├─ data\giam_sat_dich_benh.db
├─ backups\
└─ update_cache\
```

GitHub Actions từ chối phát hành nếu phát hiện `.db`, SQLite, Excel, CSV hoặc các thư mục dữ liệu trong mã nguồn/sản phẩm build.

## Chức năng chính

- Dashboard thống kê ca bệnh, ổ dịch, ca mắc, tử vong và cảnh báo chất lượng.
- Nhập Excel ca bệnh/ổ dịch; nhận diện tiêu đề biến thể và file XLSX khai báo sai phạm vi.
- Chống nhập lại đúng nguyên dòng bằng SHA-256.
- **Lọc trùng nghiệp vụ**:
  - Ca bệnh: mã ca, CCCD/CMND, họ tên, năm sinh, giới, điện thoại, địa bàn, chẩn đoán, ngày khởi phát.
  - Ổ dịch: tên bệnh, địa điểm chuẩn hóa, địa bàn, thời gian khởi phát và đơn vị báo cáo.
  - Phân loại `Trùng chắc chắn` và `Nghi trùng`.
  - Người dùng chọn bản ghi giữ lại; CSDL được sao lưu trước khi xóa bản trùng.
- Tìm kiếm, lọc, phân trang, xem chi tiết và xuất Excel/CSV.
- Thêm, sửa, xóa ổ dịch.
- Kiểm tra chất lượng dữ liệu và SQL chỉ đọc.
- Menu ứng dụng: nhập dữ liệu, lọc trùng, sao lưu, cập nhật, cấu hình máy trạm/máy chủ và trợ giúp.
- Máy chủ LAN có cổng và mật khẩu tùy chọn; tab Server chỉ xuất hiện ở chế độ máy chủ.

## Lưu ý mạng LAN

- Máy chủ mặc định nghe tại cổng `8765` trên mọi card mạng (`0.0.0.0`).
- Khi Windows Firewall hỏi quyền, chỉ cho phép trên **Private networks / Mạng riêng tư**.
- Không chuyển tiếp cổng server ra Internet. API hiện được thiết kế cho mạng LAN tin cậy, không có TLS.
- Nếu không đặt mật khẩu, mọi máy trong LAN biết IP và cổng đều có thể kết nối.

## Phát hành

Workflow `.github/workflows/release.yml` chạy kiểm thử trên Windows, build bằng PyInstaller, tạo Setup bằng Inno Setup, quét dữ liệu cấm và sinh:

- `GiamSatDichBenh-Setup-vX.Y.Z.exe`
- `GiamSatDichBenh-Portable-vX.Y.Z.zip`
- `SHA256SUMS.txt`

Pull request chỉ build/test và tải artifact; chỉ push vào `main` hoặc chạy workflow thủ công mới tạo GitHub Release.

## Kiểm thử

```bat
python -m pytest -q
```

## Cấu trúc

```text
app.py                 Giao diện, menu, lọc trùng, máy trạm và tab Server
core.py                SQLite, nhập/xuất, chất lượng và thuật toán lọc trùng
deployment_config.py   Cấu hình standalone/workstation/server
lan_server.py          HTTP API cho máy chủ LAN
remote_core.py         Lớp gọi API dành cho máy trạm
update_manager.py      Cập nhật ứng dụng
setup.iss              Bộ cài và trang chọn mô hình triển khai
.github/workflows/     Kiểm thử, build và Release tự động
tests/                  Kiểm thử lõi, lọc trùng, cấu hình và LAN
```
