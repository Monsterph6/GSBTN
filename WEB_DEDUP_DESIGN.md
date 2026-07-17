# Thiết kế giai đoạn kế tiếp — Nền tảng Web thu thập & lọc trùng ca bệnh

Tài liệu này thiết kế bước tiếp theo cho hệ thống hiện có (desktop PyQt6 + SQLite + LAN,
xem `README.md`/`SCHEMA.md`): đưa việc **thu thập ca bệnh hằng tuần từ Trạm Y tế xã** và
**lọc trùng tại CDC** lên một nền tảng Web, có cơ chế hàng đợi hai tầng để chịu được tình
trạng máy chủ chính offline.

**Trạng thái**: Giai đoạn 1–4 ở mục 11 đã được cài đặt trong mã nguồn (lọc trùng theo tiêu
chí, xuất Excel chia theo xã, Web nộp dữ liệu + hàng đợi trên `lan_server.py`, máy chủ phụ
Google Apps Script trong `google_apps_script/` + `secondary_sync.py`). Giai đoạn 5 (đối soát,
nhắc nộp báo cáo, giám sát vận hành, xác thực đầy đủ cho Internet) vẫn còn ở dạng thiết kế.

## 1. Bối cảnh và mục tiêu

- Hiện tại: ứng dụng desktop, CSDL SQLite, chia sẻ trong LAN qua `lan_server.py`. Lọc trùng
  dùng **chấm điểm** theo trọng số (`duplicate_config.py`, `_case_pair_score`).
- Mục tiêu giai đoạn mới:
  1. Trạm Y tế xã **nộp danh sách ca bệnh hằng tuần qua Web** thay vì gửi file thủ công.
  2. CDC (admin) **lọc trùng theo tiêu chí do người dùng chọn** (bỏ chấm điểm), mỗi nhóm
     trùng hiển thị **mã ca bệnh (case_code) gốc trong file Excel đã nhập** để tra cứu ngược.
  3. CDC **xuất Excel chia theo xã** (mỗi xã một sheet) để gửi các xã tự lọc trùng trên phần
     mềm của Bộ Y tế; ca trùng khác xã thì lấy theo xã của **ca có ngày vào viện gần nhất**.
  4. Xã nộp dữ liệu lên theo 2 đường: **trực tiếp vào hàng đợi máy chủ chính** khi máy chủ
     online, hoặc **qua máy chủ phụ (Google Apps Script/Sheet/Drive)** khi máy chủ chính
     offline, và đồng bộ ngược khi máy chủ chính online trở lại.

## 2. Vai trò & tổng quan luồng nghiệp vụ

| Vai trò | Quyền | Hành động chính |
|---|---|---|
| **Trạm Y tế xã** | Chỉ thấy/nộp dữ liệu của xã mình | Tải lên danh sách ca bệnh hằng tuần (theo mẫu Excel hiện có, 48 trường `CASE_FIELDS`) |
| **CDC (admin)** | Toàn quyền, xem tất cả các xã | Duyệt hàng đợi → nhập CSDL → lọc trùng theo tiêu chí → xuất Excel chia theo xã → gửi lại các xã |
| **Hệ thống (nền)** | — | Đồng bộ máy chủ phụ ↔ máy chủ chính, ghi nhật ký, nhắc nộp báo cáo |

```
Trạm xã A ─┐                         ┌─► Hàng đợi (import_queue) ─► CDC duyệt/nhập CSDL
Trạm xã B ─┼─ Web nộp Excel tuần ─────┤                                   │
Trạm xã C ─┘   (nếu server chính      │   máy chủ chính offline?         ▼
               offline → máy chủ phụ) └─► Google Sheet/Drive (buffer) ─► Đồng bộ khi online
                                                                          │
CDC lọc trùng theo tiêu chí chọn (không tính điểm) ◄──────────────────────┘
   │
   ▼
Xuất Excel chia theo xã (mỗi xã 1 sheet, ca trùng khác xã → giữ xã có ngày vào viện gần nhất)
   │
   ▼
Gửi lại từng xã → xã lọc trùng trên phần mềm Bộ Y tế → nộp phản hồi (đối soát, mục 10.5)
```

## 3. Kiến trúc tổng thể

```
┌─────────────────┐   HTTPS    ┌───────────────────────────┐
│ Trình duyệt xã   │───────────►│  Web API (FastAPI)        │
│ (form nộp Excel) │            │  - auth theo xã           │
└─────────────────┘            │  - /submissions (nộp tuần)│
                                │  - /queue (hàng đợi)      │
┌─────────────────┐   HTTPS    │  - /dedup (tiêu chí)      │
│ Trình duyệt CDC  │───────────►│  - /export (chia xã)      │
│ (dashboard admin)│            └─────────┬─────────────────┘
└─────────────────┘                       │
                                           ▼
                                ┌───────────────────────────┐
                                │ PostgreSQL (thay SQLite)   │   core.py logic import/
                                │ hoặc SQLite server-mode    │   dedup được tái dùng
                                │ hiện có, tái dùng core.py  │   tối đa, chỉ đổi tầng
                                └─────────┬─────────────────┘   lưu trữ + thêm bảng mới
                                           │ đồng bộ khi online
                                           ▼
                                ┌───────────────────────────┐
                                │ Máy chủ phụ (buffer)       │
                                │ Google Apps Script Web App │
                                │ + Google Sheet (hàng đợi)  │
                                │ + Google Drive (file gốc)  │
                                └───────────────────────────┘
```

**Vì sao không viết lại toàn bộ:** `core.py` đã có sẵn `import_excel`, `find_duplicate_groups`,
`merge_duplicate_records`, `export_rows`… Nên giữ nguyên các hàm này làm "lõi nghiệp vụ", chỉ
thêm một tầng Web API gọi vào (giống cách `lan_server.py` đang bọc RPC quanh `core`), thay vì
viết lại logic nhập/xuất Excel.

## 4. Trạm Y tế xã — nộp danh sách ca bệnh hằng tuần

- Trang `/nop-du-lieu`: chọn tuần báo cáo (ISO week, vd `2026-W29`), tải lên 1 file Excel theo
  mẫu 48 cột hiện có. Validate ngay khi tải lên bằng logic sẵn có (`detect_excel`, cảnh báo
  tiêu đề lệch, dòng trùng SHA-256) để xã sửa lỗi tại chỗ thay vì để CDC phát hiện sau.
- Mỗi lần nộp tạo một bản ghi `weekly_submissions` (xã, tuần, file, thời điểm, người nộp) —
  **không ghi đè**; nộp lại trong cùng tuần tạo phiên bản mới, CDC luôn thấy lịch sử.
- Client tự kiểm tra máy chủ chính còn sống bằng `GET /health` (giống `lan_server.py` hiện tại).
  - **Online** → `POST /queue/submit` thẳng vào hàng đợi máy chủ chính.
  - **Offline** (timeout/lỗi mạng) → fallback gọi Google Apps Script Web App (mục 7) để lưu
    tạm; giao diện báo rõ "Đã lưu tạm, sẽ tự đồng bộ khi hệ thống chính hoạt động lại".
- Dashboard xã: xem trạng thái các lần nộp (chờ nhập / đã nhập / lỗi), tải lại phiếu nộp cũ.

## 5. CDC — Lọc trùng theo tiêu chí chọn (bỏ chấm điểm)

### 5.1 Vì sao bỏ chấm điểm

Chấm điểm (`_case_pair_score`) khó giải thích với người dùng nghiệp vụ ("tại sao 82 điểm là
nghi trùng mà 78 thì không"), và ngưỡng phải tinh chỉnh liên tục. Thay vào đó: CDC **chọn hẳn
những tiêu chí nào coi là trùng**, hệ thống chỉ gộp nhóm theo đúng tiêu chí đã chọn (không quy
đổi ra điểm số).

### 5.2 Tiêu chí chọn được (tái dùng các khóa chặn đã có trong `find_duplicate_groups`)

Các "khóa chặn" (blocking keys) hiện có trong `core.py` (dòng ~1082-1094) vốn đã là các tiêu
chí trùng chính xác — chỉ cần đưa lên UI làm checkbox thay vì dùng nội bộ để rồi chấm điểm:

| Tiêu chí (checkbox) | Điều kiện khớp | Trường dữ liệu |
|---|---|---|
| ☑ Trùng mã ca bệnh | `case_code` giống hệt | `case_code` |
| ☑ Trùng CCCD/CMND | `national_id` (≥9 số) giống hệt | `national_id` |
| ☐ Trùng số điện thoại | 9 số cuối giống hệt | `phone` |
| ☐ Trùng họ tên + năm sinh | `full_name` + `birth_year` giống hệt | `full_name`, `birth_year` |
| ☐ Trùng họ tên + xã/phường | `full_name` + `commune` giống hệt | `full_name`, `commune` |
| ☐ Họ tên gần giống (≥ ngưỡng ký tự) | tỉ lệ khớp chuỗi ≥ mức chọn (mặc định 92%), chỉ so trong cùng xã | `full_name` |
| ☐ Ngày khởi phát trong N ngày | lệch ≤ N ngày (CDC chọn N), chỉ so trong cùng xã | `onset_date` |

- Mặc định bật sẵn 2 tiêu chí "chắc chắn" (mã ca, CCCD) — tương đương quy tắc hiện tại
  `if code_a == code_b: return 100`. Các tiêu chí còn lại CDC tự bật/tắt theo đợt lọc.
- Hai bản ghi được coi là **trùng** nếu khớp **ít nhất một** tiêu chí đang bật (giữ nguyên cách
  gộp nhóm bằng union-find như code hiện tại — chỉ bỏ phần tính điểm/ngưỡng).
- Không còn "Trùng chắc chắn" / "Nghi trùng" theo điểm; thay bằng liệt kê **rõ ràng những tiêu
  chí nào đã khớp** cho từng cặp (vd: "Trùng CCCD; Trùng họ tên + xã"), CDC tự đánh giá.
- Bộ tiêu chí có thể **lưu thành preset** (`dedup_criteria_sets`: tên, danh sách tiêu chí bật,
  N ngày…) để dùng lại mỗi tuần, thay cho `duplicate_rules.json` (trọng số) hiện tại.

### 5.3 Hiển thị mã ID ca bệnh từ file Excel nhập vào

Mỗi bản ghi trong nhóm trùng hiển thị đủ để CDC truy ngược nguồn:

| Cột hiển thị | Nguồn |
|---|---|
| **Mã ca bệnh (case_code)** | Cột "Mã số" trong Excel gốc |
| Xã nộp | `commune` + xã đã nộp bản ghi (`weekly_submissions.commune`) |
| Họ tên, năm sinh, giới tính | `full_name`, `birth_year`, `gender` |
| Ngày vào viện | `admission_date` |
| File nguồn / dòng nguồn | `source_file`, `source_row` (đã có sẵn trong `cases`) |
| Tuần nộp | `weekly_submissions.week` qua liên kết `import_batches` |

`case_code` vốn đã được lưu trong bảng `cases`, chỉ cần thêm cột này vào kết quả trả về của
`find_duplicate_groups` (đã có `case_code` trong `fields` — hiện chỉ chưa hiển thị nổi bật trên
UI). Đây là điểm khác biệt quan trọng với bản chấm điểm cũ: CDC luôn thấy **mã ca bệnh gốc**
để đối chiếu ngược với file Excel xã đã gửi, không chỉ thấy `id` nội bộ CSDL.

## 6. CDC — Xuất Excel chia theo xã

### 6.1 Cấu trúc file xuất

- 1 workbook, **mỗi xã một sheet** (tên sheet = tên xã, cắt theo giới hạn 31 ký tự của Excel).
- Một sheet tổng hợp đầu tiên `Tong_hop` liệt kê: nhóm trùng, các mã ca liên quan, xã được
  chọn, lý do chọn xã (tiêu chí áp dụng ở mục 6.2), để CDC lưu vết quyết định.
- Cột trong mỗi sheet xã: toàn bộ 48 trường `CASE_FIELDS` hiện có + cột `Nhóm trùng` (group_id)
  + cột `Ghi chú lọc trùng` (tiêu chí đã khớp) để cán bộ xã biết vì sao bản ghi bị đánh dấu.

### 6.2 Quy tắc chọn xã khi 2 ca trùng khác xã

> "nếu 2 ca trùng khác xã sẽ lấy địa chỉ xã của ca vào viện gần nhất"

Áp dụng: khi một nhóm trùng có bản ghi thuộc **nhiều xã khác nhau**, xã đại diện cho cả nhóm
khi xuất file = **xã của bản ghi có `admission_date` gần với ngày lập báo cáo nhất (mới nhất)**
— tức bản ghi nhập viện gần đây nhất phản ánh nơi bệnh nhân đang được xử lý/theo dõi thực tế.

- Nếu >2 bản ghi trong nhóm thuộc >2 xã: vẫn áp dụng cùng quy tắc — chọn xã của bản ghi có
  `admission_date` lớn nhất (mới nhất) trong cả nhóm.
- Nếu `admission_date` bằng nhau hoặc thiếu dữ liệu ở bản ghi mới nhất: rơi xuống so
  `onset_date`, rồi đến `report_datetime`, theo đúng thứ tự ưu tiên đó; nếu vẫn không phân định
  được thì giữ nguyên xã của bản ghi có `id` nhỏ nhất (bản ghi vào hệ thống sớm nhất) và gắn cờ
  "cần CDC xác nhận thủ công" trên sheet `Tong_hop`.
- **Cần xác nhận với người dùng**: "gần nhất" ở đây hiểu là *mới nhất/gần hiện tại nhất*
  (nearest-to-now). Nếu ý là "hai ngày vào viện gần nhau nhất giữa 2 ca" thì quy tắc chọn xã sẽ
  khác — nên chốt lại trước khi code hoá (xem mục 12).
- Toàn bộ 48 trường của bản ghi giữ nguyên theo bản ghi được chọn làm đại diện; các bản ghi còn
  lại trong nhóm chỉ liệt kê tham chiếu ở sheet `Tong_hop`, xã nhận file **không** thấy dữ liệu
  cá nhân đầy đủ của ca thuộc xã khác (giảm rủi ro lộ dữ liệu chéo xã).

## 7. Hàng đợi nhập liệu hai tầng

### 7.1 Máy chủ chính online — hàng đợi trực tiếp

- Bảng `import_queue`: `id, commune, week, file_path, source ('server_chinh'|'server_phu'), status ('cho_nhap'|'da_nhap'|'loi'), received_at, imported_at, imported_by`.
- Màn hình CDC `/hang-doi`: bảng dữ liệu **nhóm theo xã**, mỗi dòng = 1 lần nộp, có nút "Nhập
  vào CSDL" (gọi `core.import_excel` hiện có) và "Xem trước" (đọc nhanh vài dòng đầu để soát
  lỗi trước khi nhập chính thức).
- Khi nhập xong, cập nhật `import_batches` như cơ chế sẵn có, chuyển `status = 'da_nhap'`.

### 7.2 Máy chủ chính offline — máy chủ phụ (Google Apps Script)

- Google Sheet `HangDoiPhu` đóng vai trò bảng hàng đợi tạm, cấu trúc cột tương ứng
  `import_queue`; file Excel gốc lưu trong thư mục Google Drive theo cấu trúc
  `HangDoiPhu/<xa>/<tuan>/<ten_file>.xlsx`.
- Google Apps Script publish dưới dạng **Web App** (`doPost`) nhận file (base64, giống cách
  `lan_server.py` đang nhận `/import` hiện nay) từ trình duyệt xã khi client phát hiện máy chủ
  chính không phản hồi; script ghi 1 dòng vào Sheet + lưu file vào Drive, trả về mã xác nhận.
- **Đồng bộ ngược khi máy chủ chính online lại**: một job nền (chạy định kỳ, ví dụ mỗi 5 phút,
  hoặc kích hoạt ngay khi health-check thấy máy chủ chính "up") gọi Google Sheets API (đọc các
  dòng `status = 'cho_dong_bo'`), tải file từ Drive về, tạo bản ghi tương ứng trong
  `import_queue` với `source = 'server_phu'`, rồi đánh dấu dòng trên Sheet là `da_dong_bo` (idempotent — không kéo trùng nếu job chạy nhiều lần).
- Xác thực giữa 2 tầng: Web App của Apps Script yêu cầu một khoá bí mật riêng (không dùng chung
  mật khẩu LAN hiện tại) gửi kèm mỗi request, script kiểm tra trước khi ghi Sheet/Drive.
- Vì đây là dữ liệu y tế cá nhân, giới hạn quyền truy cập Sheet/Drive chỉ tài khoản dịch vụ của
  hệ thống và CDC quản trị; **không chia sẻ công khai**.

### 7.3 Trạng thái hiển thị cho CDC

Màn hình hàng đợi hiển thị rõ nguồn gốc mỗi dòng (`Trực tiếp` / `Qua máy chủ phụ (chưa đồng bộ)`
/ `Qua máy chủ phụ (đã đồng bộ)`) để CDC biết dữ liệu nào đang chờ ở Google Sheet chưa vào hệ
thống chính, tránh nhầm tưởng đã nhận đủ báo cáo tuần.

## 8. Mô hình dữ liệu bổ sung (ngoài các bảng đã có trong `SCHEMA.md`)

- `communes`: danh mục xã (mã xã, tên xã, đơn vị hành chính cấp trên) — chuẩn hoá thay vì chuỗi
  tự do như `commune` hiện tại, giảm sai lệch khi nhóm theo xã.
- `commune_accounts`: tài khoản đăng nhập của Trạm Y tế xã (liên kết `communes`), mật khẩu
  băm, vai trò.
- `weekly_submissions`: xã, tuần (ISO week), file gốc, người nộp, thời điểm, trạng thái, liên
  kết `import_batches` sau khi nhập.
- `import_queue`: như mục 7.1.
- `dedup_criteria_sets`: thay cho phần trọng số trong `duplicate_rules.json` — tên bộ tiêu chí,
  danh sách tiêu chí bật/tắt, tham số (N ngày, ngưỡng % họ tên gần giống).
- `duplicate_actions` (đã có): bổ sung cột `criteria_used_json` thay cho việc suy ra từ điểm số.
- `commune_export_batches`: mỗi lần CDC xuất Excel chia theo xã — lưu thời điểm, người xuất, xã
  nào nhận sheet nào, để đối soát khi xã phản hồi kết quả lọc trùng (mục 10.5).

## 9. Bảo mật, phân quyền, nhật ký

- Web lộ ra Internet (khác LAN nội bộ hiện tại) → bắt buộc HTTPS, đăng nhập cho cả xã và CDC
  (khác với chế độ "không mật khẩu" LAN hiện có), khoá tài khoản sau nhiều lần đăng nhập sai.
- Phân quyền cứng theo xã: tài khoản xã chỉ query/API được dữ liệu `commune` của chính mình;
  CDC mới có quyền xem toàn bộ và chạy lọc trùng liên xã.
- Dữ liệu là thông tin y tế cá nhân (CCCD, SĐT, chẩn đoán) → áp dụng nguyên tắc tối thiểu hoá
  hiển thị (mục 6.2 đã giới hạn xã chỉ thấy dữ liệu xã mình), cân nhắc mã hoá `national_id`,
  `phone` lúc lưu trữ, tuân thủ Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân.
- Nhật ký kiểm toán: ai nộp, ai duyệt hàng đợi, ai đổi tiêu chí lọc trùng, ai gộp/xoá, ai xuất
  Excel — mở rộng từ `duplicate_actions`/`import_batches` sẵn có sang một bảng `audit_log`
  chung cho mọi thao tác ghi trên Web (không chỉ lọc trùng).

## 10. Đề xuất bổ sung

1. **Theo dõi tiến độ nộp báo cáo tuần**: dashboard CDC hiển thị ma trận Xã × Tuần (đã nộp/
   chưa nộp/trễ hạn), có thể gửi email/SMS nhắc tự động vào một ngày cố định mỗi tuần.
2. **Kiểm tra hợp lệ ngay khi xã tải lên** (không đợi CDC phát hiện): tái dùng
   `detect_excel`/cảnh báo tiêu đề lệch/`data_quality_issues` hiện có, hiển thị lỗi ngay trên
   trình duyệt xã để họ sửa và nộp lại trong cùng phiên.
3. **Không ghi đè, luôn versioning**: mỗi lần nộp là một phiên bản trong `weekly_submissions`,
   CDC luôn xem được lịch sử, tránh mất dữ liệu khi xã nộp nhầm/nộp lại.
4. **Đối soát ngược sau khi xã lọc trùng trên phần mềm Bộ Y tế**: xã nộp lại kết quả (hoặc mã
   ca đã được Bộ Y tế xác nhận là bản chính), hệ thống so khớp với `commune_export_batches` để
   biết ca nào đã xử lý xong, ca nào xã chưa phản hồi — tránh lặp lại chu kỳ gửi trùng.
5. **Sao lưu/khôi phục**: giữ cơ chế `backup_manager.py` hiện có nhưng chạy tự động trên máy
   chủ cloud theo lịch, đồng thời đẩy thêm 1 bản sao định kỳ lên Google Drive (đã có sẵn trong
   danh sách đích sao lưu hỗ trợ) làm lớp phòng hộ thứ 2 tách biệt hạ tầng chính.
6. **Không phá vỡ ứng dụng desktop hiện tại**: `core.py` vẫn dùng chung cho cả desktop (LAN) và
   Web; Web API chỉ là một lớp bọc mới (tương tự cách `lan_server.py` bọc RPC quanh `core`),
   giúp triển khai song song, không phải "viết lại từ đầu".
7. **Giám sát vận hành**: cảnh báo khi máy chủ chính rớt mạng quá X phút (kích hoạt luồng máy
   chủ phụ) và khi hàng đợi máy chủ phụ tồn đọng quá lâu chưa đồng bộ được.
8. **Kiểm thử**: viết test cho (a) gộp nhóm theo tiêu chí chọn (thay bộ test điểm số hiện tại
   trong `tests/`), (b) quy tắc chọn xã khi trùng khác xã, (c) đồng bộ hàng đợi phụ → chính
   (idempotent, không nhân đôi khi chạy job 2 lần), trước khi triển khai thật cho các xã.

## 11. Lộ trình triển khai theo giai đoạn

1. **Giai đoạn 1 — Lọc trùng theo tiêu chí (không cần hạ tầng Web mới)**: sửa
   `find_duplicate_groups`/`app.py` để CDC chọn tiêu chí thay vì cấu hình trọng số, hiển thị
   `case_code` trong bảng kết quả. Có thể làm ngay trên ứng dụng desktop hiện tại, giá trị dùng
   được ngay cả trước khi có Web.
2. **Giai đoạn 2 — Xuất Excel chia theo xã**: thêm hàm xuất nhiều sheet + quy tắc chọn xã khi
   trùng khác xã (mục 6), vẫn trong `core.py`, dùng được ngay từ ứng dụng desktop.
3. **Giai đoạn 3 — Web nộp dữ liệu + hàng đợi máy chủ chính**: dựng Web API (FastAPI) bọc
   quanh `core.py`, trang nộp cho xã, màn hình hàng đợi cho CDC, tài khoản/phân quyền.
4. **Giai đoạn 4 — Máy chủ phụ (Google Apps Script/Sheet/Drive) + đồng bộ tự động**.
5. **Giai đoạn 5 — Đối soát, nhắc nộp báo cáo, giám sát vận hành, mở rộng cho toàn bộ các xã.**

Chia nhỏ như trên để mỗi giai đoạn có thể triển khai/nghiệm thu độc lập, giảm rủi ro so với làm
toàn bộ hệ thống Web cùng lúc.

## 12. Điểm cần xác nhận thêm với người dùng trước khi code hoá

- Mục 6.2: "ca vào viện gần nhất" — xác nhận là *ngày nhập viện mới nhất/gần hiện tại nhất*
  (cách hiểu hiện dùng trong tài liệu) hay *khoảng cách ngày nhập viện giữa 2 ca gần nhau nhất*.
- Hạ tầng lưu trữ Web: tiếp tục SQLite (chạy 1 tiến trình server, như mô hình LAN hiện tại) hay
  chuyển hẳn sang PostgreSQL để chịu tải nhiều xã truy cập đồng thời qua Internet.
- Danh sách xã và tài khoản đăng nhập: đã có sẵn danh mục hành chính (mã xã chuẩn) để nạp vào
  bảng `communes`, hay cần CDC cung cấp/nhập tay ban đầu.
- Tần suất/độ trễ chấp nhận được cho việc đồng bộ máy chủ phụ → máy chủ chính (đề xuất 5 phút
  ở mục 7.2, có thể điều chỉnh).
