# Mô hình dữ liệu

## `cases`

Lưu 48 trường của danh sách ca bệnh cùng `birth_year`, thông tin file nguồn, `row_hash`, thời điểm nhập và JSON nguồn.

## `outbreaks`

Lưu 15 trường ổ dịch, `admin_area`, thông tin file nguồn, `row_hash`, thời điểm nhập và JSON nguồn.

## `import_batches`

Nhật ký nhập Excel: số dòng đọc, thêm mới, trùng tuyệt đối, bỏ qua và cảnh báo.

## `data_quality_issues`

Các lỗi/cảnh báo chất lượng gắn với loại đối tượng và ID bản ghi.

## `duplicate_actions`

Nhật ký xử lý lọc trùng gồm loại đối tượng, ID giữ lại, danh sách ID đã xóa, file sao lưu và thời điểm thao tác.

## Hai lớp chống trùng

### 1. Trùng tuyệt đối khi nhập

`row_hash = SHA256(entity_type + JSON chuẩn hóa toàn bộ nội dung nghiệp vụ)`.

Cơ chế này chỉ bỏ qua một dòng giống hệt đã nhập trước đó.

### 2. Lọc trùng nghiệp vụ

`find_duplicate_groups()` tạo các cặp ứng viên theo khóa chặn rồi chấm điểm:

- Ca bệnh: mã ca/CCCD cho điểm tuyệt đối; các trường họ tên, điện thoại, năm sinh, giới, xã/phường, chẩn đoán, địa chỉ và khoảng cách ngày khởi phát bổ sung điểm.
- Ổ dịch: tên bệnh, độ tương đồng địa điểm, địa bàn, khoảng cách ngày khởi phát và đơn vị báo cáo.

Nhóm có điểm từ 85 được gắn `Trùng chắc chắn`; từ ngưỡng người dùng chọn đến dưới 85 là `Nghi trùng`. Không tự động xóa. `remove_duplicate_records()` sao lưu CSDL, giữ ID được chọn, xóa các ID còn lại và ghi `duplicate_actions`.

## Triển khai LAN

- Máy chủ và máy đơn lẻ sử dụng SQLite cục bộ.
- Máy chủ mở HTTP API; mỗi request dùng một kết nối SQLite riêng và WAL.
- Máy trạm gọi API, không truy cập file `.db` qua thư mục chia sẻ mạng.
- Mật khẩu là tùy chọn; để trống thì API không yêu cầu header xác thực.
