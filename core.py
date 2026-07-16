from __future__ import annotations

import csv
from contextlib import contextmanager
from difflib import SequenceMatcher
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from openpyxl import Workbook, load_workbook

APP_NAME = "Giám sát dịch bệnh"
VERSION = "0.4.0"


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()


def _user_data_root() -> Path:
    """Thư mục dữ liệu tách khỏi bộ cài để cài mới/cập nhật không đụng CSDL."""
    override = os.environ.get("GIAM_SAT_DICH_BENH_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "CDC_HaiPhong" / "GiamSatDichBenh"
    return Path.home() / ".giam_sat_dich_benh"


USER_DATA_DIR = _user_data_root()
DATA_DIR = USER_DATA_DIR / "data"
BACKUP_DIR = USER_DATA_DIR / "backups"
UPDATE_CACHE_DIR = USER_DATA_DIR / "update_cache"
DB_PATH = DATA_DIR / "giam_sat_dich_benh.db"

for directory in (DATA_DIR, BACKUP_DIR, UPDATE_CACHE_DIR):
    directory.mkdir(parents=True, exist_ok=True)


CASE_FIELDS: list[tuple[str, str]] = [
    ("STT", "source_stt"),
    ("Mã số", "case_code"),
    ("Họ tên", "full_name"),
    ("Ngày sinh", "birth_date_raw"),
    ("Nghề nghiệp", "occupation"),
    ("Nơi làm việc/ Học tập", "workplace"),
    ("Tỉnh (Nơi làm việc)", "workplace_province"),
    ("Xã (Nơi làm việc)", "workplace_commune"),
    ("Thôn (Nơi làm việc)", "workplace_village"),
    ("Dân tộc", "ethnicity"),
    ("Giới tính", "gender"),
    ("CMND", "national_id"),
    ("Điện thoại", "phone"),
    ("Nơi ở hiện nay", "current_address"),
    ("Tỉnh", "province"),
    ("Xã", "commune"),
    ("Thôn", "village"),
    ("Kinh độ", "longitude"),
    ("Vĩ độ", "latitude"),
    ("Chẩn đoán chính", "main_diagnosis"),
    ("Phân độ bệnh", "severity"),
    ("Chẩn đoán bệnh kèm theo", "comorbidity_diagnosis"),
    ("Tình trạng tiêm chủng", "vaccination_status"),
    ("Số lần tiêm, uống", "vaccination_doses"),
    ("Phân loại chẩn đoán", "diagnosis_classification"),
    ("Lấy mẫu xét nghiệm", "sample_collected"),
    ("Ngày lấy mẫu", "sample_date"),
    ("Đơn vị xét nghiệm", "lab_unit"),
    ("Loại xét nghiệm", "test_type"),
    ("Kết quả", "test_result"),
    ("Ghi chú", "notes"),
    ("Tình trạng hiện nay", "current_status"),
    ("Tiền sử dịch tễ", "epidemiological_history"),
    ("Ngày khởi phát", "onset_date"),
    ("Ngày nhập viện", "admission_date"),
    ("Ngày ra viện/tử vong", "discharge_or_death_date"),
    ("Biến chứng", "complications"),
    ("Tên người báo cáo", "reporter_name"),
    ("SĐT người báo cáo", "reporter_phone"),
    ("Email người báo cáo", "reporter_email"),
    ("Đơn vị báo cáo", "reporting_unit"),
    ("Tỉnh đơn vị báo cáo", "reporting_province"),
    ("Cơ sở điều trị", "treatment_facility"),
    ("Trạng thái", "record_status"),
    ("Thời gian báo cáo", "report_datetime"),
    ("Chẩn đoán thay đổi gần nhất", "latest_diagnosis_change"),
    ("Tình trạng thay đổi gần nhất", "latest_status_change"),
    ("Thời gian sửa", "modified_datetime"),
]

OUTBREAK_FIELDS: list[tuple[str, str]] = [
    ("STT", "source_stt"),
    ("Tên bệnh", "disease"),
    ("Địa điểm xảy ra ổ dịch", "location"),
    ("Ngày khởi phát trường hợp bệnh đầu tiên", "first_onset_date"),
    ("Ngày ổ dịch kết thúc hoạt động", "end_date"),
    ("Trạng thái", "status"),
    ("Số ca mắc", "case_count"),
    ("Số ca tử vong", "death_count"),
    ("Số mẫu XN", "sample_count"),
    ("Số mẫu (+)", "positive_count"),
    ("Ngày báo cáo", "report_datetime"),
    ("Đơn vị báo cáo", "reporting_unit"),
    ("Tỉnh báo cáo", "reporting_province"),
    ("Ngày nhận báo cáo ổ dịch bệnh đầu tiên", "first_report_received_date"),
    ("Ngày khởi phát trường hợp bệnh cuối cùng", "last_onset_date"),
]

CASE_LABELS = {db: label for label, db in CASE_FIELDS}
OUTBREAK_LABELS = {db: label for label, db in OUTBREAK_FIELDS}

DATE_FIELDS = {
    "sample_date",
    "onset_date",
    "admission_date",
    "discharge_or_death_date",
    "first_onset_date",
    "end_date",
    "first_report_received_date",
    "last_onset_date",
}
DATETIME_FIELDS = {"report_datetime", "modified_datetime"}
INTEGER_FIELDS = {"source_stt", "case_count", "death_count", "sample_count", "positive_count"}
FLOAT_FIELDS = {"longitude", "latitude"}


@dataclass
class ImportSummary:
    file_name: str
    entity_type: str
    detected_sheet: str
    rows_read: int = 0
    inserted: int = 0
    duplicates: int = 0
    skipped: int = 0
    issues: int = 0

    def as_text(self) -> str:
        kind = "ca bệnh" if self.entity_type == "case" else "ổ dịch"
        return (
            f"{self.file_name} — {kind}: đọc {self.rows_read}, thêm {self.inserted}, "
            f"trùng {self.duplicates}, bỏ qua {self.skipped}, cảnh báo {self.issues}."
        )


@contextmanager
def _connect(db_path: Path | str = DB_PATH):
    """Mở kết nối SQLite theo phạm vi và luôn đóng file khi rời khối with.

    sqlite3.Connection.__exit__ chỉ commit/rollback chứ không đóng kết nối;
    trên Windows điều đó giữ khóa file .db và làm sao lưu/xóa thất bại.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_stt INTEGER,
                case_code TEXT,
                full_name TEXT,
                birth_date_raw TEXT,
                birth_year INTEGER,
                occupation TEXT,
                workplace TEXT,
                workplace_province TEXT,
                workplace_commune TEXT,
                workplace_village TEXT,
                ethnicity TEXT,
                gender TEXT,
                national_id TEXT,
                phone TEXT,
                current_address TEXT,
                province TEXT,
                commune TEXT,
                village TEXT,
                longitude REAL,
                latitude REAL,
                main_diagnosis TEXT,
                severity TEXT,
                comorbidity_diagnosis TEXT,
                vaccination_status TEXT,
                vaccination_doses TEXT,
                diagnosis_classification TEXT,
                sample_collected TEXT,
                sample_date TEXT,
                lab_unit TEXT,
                test_type TEXT,
                test_result TEXT,
                notes TEXT,
                current_status TEXT,
                epidemiological_history TEXT,
                onset_date TEXT,
                admission_date TEXT,
                discharge_or_death_date TEXT,
                complications TEXT,
                reporter_name TEXT,
                reporter_phone TEXT,
                reporter_email TEXT,
                reporting_unit TEXT,
                reporting_province TEXT,
                treatment_facility TEXT,
                record_status TEXT,
                report_datetime TEXT,
                latest_diagnosis_change TEXT,
                latest_status_change TEXT,
                modified_datetime TEXT,
                source_file TEXT NOT NULL,
                source_sheet TEXT,
                source_row INTEGER,
                row_hash TEXT NOT NULL UNIQUE,
                imported_at TEXT NOT NULL,
                raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS outbreaks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_stt INTEGER,
                disease TEXT,
                location TEXT,
                admin_area TEXT,
                first_onset_date TEXT,
                end_date TEXT,
                status TEXT,
                case_count INTEGER DEFAULT 0,
                death_count INTEGER DEFAULT 0,
                sample_count INTEGER DEFAULT 0,
                positive_count INTEGER DEFAULT 0,
                report_datetime TEXT,
                reporting_unit TEXT,
                reporting_province TEXT,
                first_report_received_date TEXT,
                last_onset_date TEXT,
                source_file TEXT NOT NULL,
                source_sheet TEXT,
                source_row INTEGER,
                row_hash TEXT NOT NULL UNIQUE,
                imported_at TEXT NOT NULL,
                raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                file_path TEXT,
                entity_type TEXT NOT NULL,
                sheet_name TEXT,
                rows_read INTEGER DEFAULT 0,
                inserted INTEGER DEFAULT 0,
                duplicates INTEGER DEFAULT 0,
                skipped INTEGER DEFAULT 0,
                issue_count INTEGER DEFAULT 0,
                imported_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS data_quality_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id INTEGER,
                source_file TEXT,
                source_row INTEGER,
                severity TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS duplicate_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                keep_id INTEGER NOT NULL,
                removed_ids_json TEXT NOT NULL,
                backup_file TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cases_name ON cases(full_name);
            CREATE INDEX IF NOT EXISTS idx_cases_code ON cases(case_code);
            CREATE INDEX IF NOT EXISTS idx_cases_diag ON cases(main_diagnosis);
            CREATE INDEX IF NOT EXISTS idx_cases_onset ON cases(onset_date);
            CREATE INDEX IF NOT EXISTS idx_cases_commune ON cases(commune);
            CREATE INDEX IF NOT EXISTS idx_outbreaks_disease ON outbreaks(disease);
            CREATE INDEX IF NOT EXISTS idx_outbreaks_status ON outbreaks(status);
            CREATE INDEX IF NOT EXISTS idx_outbreaks_onset ON outbreaks(first_onset_date);
            CREATE INDEX IF NOT EXISTS idx_outbreaks_admin ON outbreaks(admin_area);
            CREATE INDEX IF NOT EXISTS idx_quality_type ON data_quality_issues(entity_type, severity);
            """
        )


def strip_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_key(value: Any) -> str:
    text = strip_text(value).lower()
    text = text.replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_header(value: Any) -> str:
    """Chuẩn hóa tiêu đề Excel, chịu được xuống dòng, dấu *, /, ngoặc và đánh số cột."""
    text = normalize_key(value).replace("\n", " ").replace("\r", " ")
    text = re.sub(r"^\s*\d+[\.\)]\s*", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date_value(value: Any, with_time: bool = False) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes") if with_time else value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = strip_text(value)
    fmts = (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%H:%M %d/%m/%Y",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    )
    for fmt in fmts:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.isoformat(sep=" ", timespec="minutes") if with_time else dt.date().isoformat()
        except ValueError:
            continue
    return text


def parse_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(float(str(value).replace(",", ".")))
    except (ValueError, TypeError):
        return 0


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def extract_birth_year(value: Any) -> int | None:
    text = strip_text(value)
    years = re.findall(r"(?:19|20)\d{2}", text)
    if years:
        return int(years[-1])
    return None


def extract_admin_area(location: str) -> str:
    if not location:
        return ""
    parts = [p.strip() for p in re.split(r"\s+-\s+", location) if p.strip()]
    if len(parts) >= 2:
        if "hải phòng" in normalize_key(parts[-1]) and len(parts) >= 2:
            return parts[-2]
        return parts[-1]
    patterns = re.findall(r"(?:Phường|Xã|Đặc khu|Thị trấn)\s+[^,;]+", location, flags=re.I)
    return patterns[-1].strip() if patterns else ""


def _row_hash(entity_type: str, payload: dict[str, Any]) -> str:
    canonical = {k: payload.get(k, "") for k in sorted(payload) if k not in {"source_file", "source_sheet", "source_row"}}
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(entity_type.encode("utf-8") + b"|" + raw).hexdigest()


CASE_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "source_stt": ("số thứ tự", "stt."),
    "case_code": ("mã ca bệnh", "mã bệnh nhân", "mã trường hợp", "mã số ca bệnh"),
    "full_name": ("họ và tên", "tên bệnh nhân", "họ tên bệnh nhân"),
    "birth_date_raw": ("năm sinh", "ngày tháng năm sinh"),
    "national_id": ("cccd", "cmnd cccd", "số cmnd", "số cccd", "cccd cmnd"),
    "phone": ("số điện thoại", "sđt", "điện thoại liên hệ"),
    "current_address": ("địa chỉ hiện nay", "nơi cư trú hiện nay", "địa chỉ nơi ở hiện nay"),
    "province": ("tỉnh thành phố", "tỉnh tp", "tỉnh nơi ở"),
    "commune": ("phường xã", "xã phường", "xã nơi ở"),
    "village": ("thôn tổ", "thôn xóm", "tổ dân phố"),
    "main_diagnosis": ("tên bệnh", "chẩn đoán", "bệnh chẩn đoán chính"),
    "onset_date": ("ngày phát bệnh", "ngày bắt đầu khởi phát"),
    "report_datetime": ("ngày báo cáo", "thời điểm báo cáo", "ngày giờ báo cáo"),
    "reporting_unit": ("cơ quan báo cáo", "đơn vị gửi báo cáo"),
    "record_status": ("trạng thái bản ghi", "tình trạng bản ghi"),
}

OUTBREAK_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "source_stt": ("số thứ tự", "stt."),
    "disease": ("bệnh", "tên dịch bệnh"),
    "location": ("địa điểm ổ dịch", "nơi xảy ra ổ dịch", "địa chỉ ổ dịch"),
    "first_onset_date": ("ngày khởi phát ca đầu tiên", "ngày khởi phát trường hợp đầu tiên"),
    "end_date": ("ngày kết thúc ổ dịch", "ngày ổ dịch kết thúc"),
    "case_count": ("số mắc", "tổng số ca mắc"),
    "death_count": ("số tử vong", "tổng số ca tử vong"),
    "sample_count": ("số mẫu xét nghiệm", "tổng số mẫu xn"),
    "positive_count": ("số mẫu dương tính", "số mẫu dương", "số mẫu xn dương tính"),
    "report_datetime": ("thời gian báo cáo", "ngày giờ báo cáo"),
    "reporting_province": ("tỉnh đơn vị báo cáo", "tỉnh thành báo cáo"),
    "first_report_received_date": ("ngày nhận báo cáo đầu tiên", "ngày nhận báo cáo ổ dịch đầu tiên"),
    "last_onset_date": ("ngày khởi phát ca cuối cùng", "ngày khởi phát trường hợp cuối cùng"),
}


def _make_header_map(fields: Sequence[tuple[str, str]], aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for label, db_field in fields:
        result[normalize_header(label)] = db_field
        for alias in aliases.get(db_field, ()):
            result[normalize_header(alias)] = db_field
    return result


def _mapping_for_row(row: Sequence[Any], header_map: dict[str, str]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    used_fields: set[str] = set()
    for idx, value in enumerate(row):
        key = normalize_header(value)
        field = header_map.get(key)
        if field and field not in used_fields:
            mapping[idx] = field
            used_fields.add(field)
    return mapping


def _find_header_row(ws) -> tuple[str, int, dict[int, str]] | None:
    case_map = _make_header_map(CASE_FIELDS, CASE_HEADER_ALIASES)
    outbreak_map = _make_header_map(OUTBREAK_FIELDS, OUTBREAK_HEADER_ALIASES)
    best: tuple[int, str, int, dict[int, str]] | None = None

    # Một số hệ thống xuất XLSX khai báo dimension=A1 dù thực tế có nhiều cột/dòng.
    # reset_dimensions buộc openpyxl đọc theo dữ liệu XML thực tế.
    reset = getattr(ws, "reset_dimensions", None)
    if callable(reset):
        reset()

    for row_no, row in enumerate(ws.iter_rows(min_row=1, max_row=60, values_only=True), start=1):
        case_mapping = _mapping_for_row(row, case_map)
        outbreak_mapping = _mapping_for_row(row, outbreak_map)
        case_fields = set(case_mapping.values())
        outbreak_fields = set(outbreak_mapping.values())

        case_core = len(case_fields & {
            "case_code", "full_name", "birth_date_raw", "main_diagnosis",
            "onset_date", "report_datetime", "reporting_unit"
        })
        outbreak_core = len(outbreak_fields & {
            "disease", "location", "first_onset_date", "case_count",
            "report_datetime", "reporting_unit"
        })

        if "full_name" in case_fields and case_core >= 3 and len(case_fields) >= 6:
            candidate = (len(case_fields), "case", row_no, case_mapping)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if {"disease", "location"}.issubset(outbreak_fields) and outbreak_core >= 4 and len(outbreak_fields) >= 5:
            candidate = (len(outbreak_fields), "outbreak", row_no, outbreak_mapping)
            if best is None or candidate[0] > best[0]:
                best = candidate

    if best:
        _, entity_type, row_no, mapping = best
        return entity_type, row_no, mapping
    return None


def detect_excel(path: Path | str) -> tuple[str, str, int, dict[int, str]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    diagnostics: list[str] = []
    try:
        for ws in wb.worksheets:
            found = _find_header_row(ws)
            if found:
                entity_type, header_row, mapping = found
                return entity_type, ws.title, header_row, mapping
            diagnostics.append(ws.title)
    finally:
        wb.close()
    sheets = ", ".join(diagnostics) if diagnostics else "không có trang tính"
    raise ValueError(
        "Không nhận diện được cấu trúc file ca bệnh hoặc ổ dịch. "
        f"Đã kiểm tra: {sheets}. Hãy bảo đảm file có hàng tiêu đề chứa các cột như "
        "Họ tên/Mã số/Ngày khởi phát hoặc Tên bệnh/Địa điểm xảy ra ổ dịch."
    )


def _normalize_payload(entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if key in DATE_FIELDS:
            clean[key] = parse_date_value(value, with_time=False)
        elif key in DATETIME_FIELDS:
            clean[key] = parse_date_value(value, with_time=True)
        elif key in INTEGER_FIELDS:
            clean[key] = parse_int(value)
        elif key in FLOAT_FIELDS:
            clean[key] = parse_float(value)
        else:
            clean[key] = strip_text(value)
    if entity_type == "case":
        clean["birth_year"] = extract_birth_year(clean.get("birth_date_raw"))
    else:
        clean["admin_area"] = extract_admin_area(clean.get("location", ""))
    return clean


def _is_empty_payload(entity_type: str, payload: dict[str, Any]) -> bool:
    if entity_type == "case":
        fields = ("case_code", "full_name", "main_diagnosis", "onset_date", "report_datetime")
    else:
        fields = ("disease", "location", "first_onset_date", "report_datetime")
    return not any(payload.get(k) not in (None, "", 0) for k in fields)


def _date_obj(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _quality_checks(entity_type: str, payload: dict[str, Any]) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    if entity_type == "case":
        if not payload.get("full_name"):
            issues.append(("error", "Thiếu họ tên", "Ca bệnh chưa có họ tên."))
        if not payload.get("case_code"):
            issues.append(("warning", "Thiếu mã số", "Ca bệnh chưa có mã số trên hệ thống."))
        if not payload.get("main_diagnosis"):
            issues.append(("error", "Thiếu chẩn đoán", "Ca bệnh chưa có chẩn đoán chính."))
        if not payload.get("onset_date"):
            issues.append(("warning", "Thiếu ngày khởi phát", "Không xác định được ngày khởi phát."))
        onset = _date_obj(payload.get("onset_date", ""))
        report = _date_obj(payload.get("report_datetime", ""))
        if onset and report:
            delay = (report.date() - onset.date()).days
            if delay < 0:
                issues.append(("error", "Ngày báo cáo không hợp lệ", "Thời gian báo cáo trước ngày khởi phát."))
            elif delay > 2:
                issues.append(("warning", "Báo cáo muộn", f"Báo cáo sau khởi phát {delay} ngày."))
        lon, lat = payload.get("longitude"), payload.get("latitude")
        if lon is not None and not (-180 <= lon <= 180):
            issues.append(("error", "Kinh độ không hợp lệ", f"Kinh độ {lon} ngoài khoảng -180 đến 180."))
        if lat is not None and not (-90 <= lat <= 90):
            issues.append(("error", "Vĩ độ không hợp lệ", f"Vĩ độ {lat} ngoài khoảng -90 đến 90."))
    else:
        if not payload.get("disease"):
            issues.append(("error", "Thiếu tên bệnh", "Ổ dịch chưa có tên bệnh."))
        if not payload.get("location"):
            issues.append(("error", "Thiếu địa điểm", "Ổ dịch chưa có địa điểm xảy ra."))
        if payload.get("positive_count", 0) > payload.get("sample_count", 0):
            issues.append(("error", "Số mẫu không hợp lệ", "Số mẫu dương tính lớn hơn tổng số mẫu xét nghiệm."))
        if payload.get("death_count", 0) > payload.get("case_count", 0):
            issues.append(("error", "Số tử vong không hợp lệ", "Số tử vong lớn hơn số ca mắc."))
        status = normalize_key(payload.get("status"))
        if "da ket thuc" in status and not payload.get("end_date"):
            issues.append(("error", "Thiếu ngày kết thúc", "Ổ dịch đã kết thúc nhưng chưa có ngày kết thúc hoạt động."))
        if "dang hoat dong" in status and payload.get("end_date"):
            issues.append(("error", "Trạng thái không khớp", "Ổ dịch đang hoạt động nhưng đã có ngày kết thúc."))
        first = _date_obj(payload.get("first_onset_date", ""))
        last = _date_obj(payload.get("last_onset_date", ""))
        end = _date_obj(payload.get("end_date", ""))
        report = _date_obj(payload.get("report_datetime", ""))
        if first and last and last < first:
            issues.append(("error", "Ngày khởi phát không hợp lệ", "Ca cuối khởi phát trước ca đầu."))
        if first and end and end < first:
            issues.append(("error", "Ngày kết thúc không hợp lệ", "Ngày kết thúc trước ngày khởi phát ca đầu."))
        if last and end and end < last:
            issues.append(("error", "Ngày kết thúc không hợp lệ", "Ngày kết thúc trước ngày khởi phát ca cuối."))
        if first and report:
            delay = (report.date() - first.date()).days
            if delay < 0:
                issues.append(("error", "Ngày báo cáo không hợp lệ", "Ngày báo cáo trước ngày khởi phát ca đầu."))
            elif delay > 2:
                issues.append(("warning", "Báo cáo muộn", f"Báo cáo ổ dịch sau khởi phát ca đầu {delay} ngày."))
        if not payload.get("first_report_received_date"):
            issues.append(("info", "Thiếu ngày nhận báo cáo", "Chưa có ngày nhận báo cáo ổ dịch bệnh đầu tiên."))
        if not payload.get("last_onset_date"):
            issues.append(("info", "Thiếu ngày khởi phát ca cuối", "Chưa có ngày khởi phát trường hợp bệnh cuối cùng."))
    return issues


def import_excel(path: Path | str, db_path: Path | str = DB_PATH) -> ImportSummary:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    init_db(db_path)
    entity_type, sheet_name, header_row, mapping = detect_excel(path)
    summary = ImportSummary(path.name, entity_type, sheet_name)
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet_name]
    reset = getattr(ws, "reset_dimensions", None)
    if callable(reset):
        reset()
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    consecutive_empty = 0
    try:
        with _connect(db_path) as conn:
            for row_no, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
                raw_payload = {field: row[idx] if idx < len(row) else None for idx, field in mapping.items()}
                payload = _normalize_payload(entity_type, raw_payload)
                if _is_empty_payload(entity_type, payload):
                    consecutive_empty += 1
                    if consecutive_empty >= 100:
                        break
                    continue
                consecutive_empty = 0
                summary.rows_read += 1
                payload["source_file"] = path.name
                payload["source_sheet"] = sheet_name
                payload["source_row"] = row_no
                payload["imported_at"] = now
                payload["raw_json"] = json.dumps({str(k): strip_text(v) for k, v in raw_payload.items()}, ensure_ascii=False)
                payload["row_hash"] = _row_hash(entity_type, payload)
                table = "cases" if entity_type == "case" else "outbreaks"
                cols = list(payload)
                placeholders = ",".join("?" for _ in cols)
                try:
                    cur = conn.execute(
                        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
                        [payload[c] for c in cols],
                    )
                    entity_id = cur.lastrowid
                    summary.inserted += 1
                except sqlite3.IntegrityError as exc:
                    if "row_hash" in str(exc).lower() or "unique" in str(exc).lower():
                        summary.duplicates += 1
                        continue
                    summary.skipped += 1
                    continue
                for severity, issue_type, description in _quality_checks(entity_type, payload):
                    conn.execute(
                        """INSERT INTO data_quality_issues
                           (entity_type, entity_id, source_file, source_row, severity, issue_type, description, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (entity_type, entity_id, path.name, row_no, severity, issue_type, description, now),
                    )
                    summary.issues += 1
            conn.execute(
                """INSERT INTO import_batches
                   (file_name, file_path, entity_type, sheet_name, rows_read, inserted, duplicates, skipped, issue_count, imported_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    path.name,
                    str(path),
                    entity_type,
                    sheet_name,
                    summary.rows_read,
                    summary.inserted,
                    summary.duplicates,
                    summary.skipped,
                    summary.issues,
                    now,
                ),
            )
    finally:
        wb.close()
    return summary


def dashboard_stats(db_path: Path | str = DB_PATH) -> dict[str, Any]:
    init_db(db_path)
    with _connect(db_path) as conn:
        cases = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        outbreaks = conn.execute("SELECT COUNT(*) FROM outbreaks").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM outbreaks WHERE status LIKE '%Đang hoạt động%'").fetchone()[0]
        total_cases = conn.execute("SELECT COALESCE(SUM(case_count),0) FROM outbreaks").fetchone()[0]
        deaths = conn.execute("SELECT COALESCE(SUM(death_count),0) FROM outbreaks").fetchone()[0]
        issues = conn.execute("SELECT COUNT(*) FROM data_quality_issues WHERE severity IN ('error','warning')").fetchone()[0]
        return {
            "case_records": cases,
            "outbreak_records": outbreaks,
            "active_outbreaks": active,
            "reported_cases": total_cases,
            "deaths": deaths,
            "quality_issues": issues,
        }


def disease_summary(db_path: Path | str = DB_PATH, limit: int = 15) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT disease, COUNT(*) AS outbreak_count,
                      COALESCE(SUM(case_count),0) AS case_count,
                      COALESCE(SUM(death_count),0) AS death_count,
                      SUM(CASE WHEN status LIKE '%Đang hoạt động%' THEN 1 ELSE 0 END) AS active_count
               FROM outbreaks
               GROUP BY disease
               ORDER BY outbreak_count DESC, disease
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def monthly_outbreak_summary(db_path: Path | str = DB_PATH, limit: int = 18) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT substr(first_onset_date,1,7) AS month,
                      COUNT(*) AS outbreak_count,
                      COALESCE(SUM(case_count),0) AS case_count
               FROM outbreaks
               WHERE first_onset_date <> ''
               GROUP BY substr(first_onset_date,1,7)
               ORDER BY month DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def recent_active_outbreaks(db_path: Path | str = DB_PATH, limit: int = 20) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT id, disease, location, first_onset_date, case_count, status, reporting_unit
               FROM outbreaks WHERE status LIKE '%Đang hoạt động%'
               ORDER BY first_onset_date DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


CASE_TABLE_COLUMNS = [
    "id", "case_code", "full_name", "birth_date_raw", "gender", "province", "commune",
    "main_diagnosis", "onset_date", "current_status", "report_datetime", "reporting_unit",
]
OUTBREAK_TABLE_COLUMNS = [
    "id", "disease", "location", "admin_area", "first_onset_date", "last_onset_date", "end_date",
    "status", "case_count", "death_count", "sample_count", "positive_count", "report_datetime", "reporting_unit",
]


def _safe_table(entity_type: str) -> tuple[str, list[str]]:
    if entity_type == "case":
        return "cases", CASE_TABLE_COLUMNS
    if entity_type == "outbreak":
        return "outbreaks", OUTBREAK_TABLE_COLUMNS
    raise ValueError("entity_type không hợp lệ")


def list_filter_values(entity_type: str, field: str, db_path: Path | str = DB_PATH) -> list[str]:
    table, columns = _safe_table(entity_type)
    allowed = set(columns) | {"record_status", "current_status", "main_diagnosis", "disease", "status", "admin_area", "reporting_unit"}
    if field not in allowed:
        raise ValueError("Trường lọc không hợp lệ")
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT DISTINCT {field} FROM {table} WHERE COALESCE({field},'') <> '' ORDER BY {field}"
        ).fetchall()
        return [str(r[0]) for r in rows]


def query_records(
    entity_type: str,
    *,
    search: str = "",
    disease: str = "",
    status: str = "",
    admin_area: str = "",
    page: int = 1,
    page_size: int = 200,
    db_path: Path | str = DB_PATH,
) -> tuple[list[dict[str, Any]], int]:
    table, columns = _safe_table(entity_type)
    where: list[str] = []
    params: list[Any] = []
    if search:
        like = f"%{search}%"
        if entity_type == "case":
            where.append("(full_name LIKE ? OR case_code LIKE ? OR national_id LIKE ? OR current_address LIKE ? OR commune LIKE ?)")
            params.extend([like] * 5)
        else:
            where.append("(disease LIKE ? OR location LIKE ? OR reporting_unit LIKE ? OR admin_area LIKE ?)")
            params.extend([like] * 4)
    if disease:
        field = "main_diagnosis" if entity_type == "case" else "disease"
        where.append(f"{field} = ?")
        params.append(disease)
    if status:
        if entity_type == "case":
            where.append("(record_status = ? OR current_status = ?)")
            params.extend([status, status])
        else:
            where.append("status = ?")
            params.append(status)
    if admin_area:
        field = "commune" if entity_type == "case" else "admin_area"
        where.append(f"{field} = ?")
        params.append(admin_area)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    order = "onset_date DESC, id DESC" if entity_type == "case" else "first_onset_date DESC, id DESC"
    page = max(1, page)
    page_size = max(10, min(2000, page_size))
    with _connect(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM {table}{where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT {','.join(columns)} FROM {table}{where_sql} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        return [dict(r) for r in rows], total


def get_record(entity_type: str, record_id: int, db_path: Path | str = DB_PATH) -> dict[str, Any] | None:
    table, _ = _safe_table(entity_type)
    with _connect(db_path) as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        return dict(row) if row else None


def save_outbreak(data: dict[str, Any], record_id: int | None = None, db_path: Path | str = DB_PATH) -> int:
    init_db(db_path)
    allowed = {db for _, db in OUTBREAK_FIELDS}
    payload = _normalize_payload("outbreak", {k: v for k, v in data.items() if k in allowed})
    payload["source_file"] = data.get("source_file") or "Nhập trực tiếp"
    payload["source_sheet"] = data.get("source_sheet") or "Ứng dụng"
    payload["source_row"] = data.get("source_row") or 0
    payload["imported_at"] = datetime.now().isoformat(sep=" ", timespec="seconds")
    payload["raw_json"] = json.dumps(data, ensure_ascii=False, default=str)
    payload["row_hash"] = _row_hash("outbreak", payload)
    with _connect(db_path) as conn:
        if record_id:
            cols = [c for c in payload if c not in {"row_hash", "imported_at"}]
            conn.execute(
                f"UPDATE outbreaks SET {','.join(f'{c}=?' for c in cols)} WHERE id=?",
                [payload[c] for c in cols] + [record_id],
            )
            conn.execute("DELETE FROM data_quality_issues WHERE entity_type='outbreak' AND entity_id=?", (record_id,))
            entity_id = record_id
        else:
            cols = list(payload)
            cur = conn.execute(
                f"INSERT INTO outbreaks ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                [payload[c] for c in cols],
            )
            entity_id = int(cur.lastrowid)
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        for severity, issue_type, description in _quality_checks("outbreak", payload):
            conn.execute(
                """INSERT INTO data_quality_issues
                   (entity_type, entity_id, source_file, source_row, severity, issue_type, description, created_at)
                   VALUES ('outbreak', ?, ?, ?, ?, ?, ?, ?)""",
                (entity_id, payload["source_file"], payload["source_row"], severity, issue_type, description, now),
            )
        return entity_id


def delete_record(entity_type: str, record_id: int, db_path: Path | str = DB_PATH) -> None:
    table, _ = _safe_table(entity_type)
    create_backup(db_path)
    with _connect(db_path) as conn:
        conn.execute(f"DELETE FROM {table} WHERE id=?", (record_id,))
        conn.execute("DELETE FROM data_quality_issues WHERE entity_type=? AND entity_id=?", (entity_type, record_id))



def _match_text(value: Any) -> str:
    text = normalize_key(value)
    return re.sub(r"[^a-z0-9]+", "", text)


def _match_digits(value: Any) -> str:
    return re.sub(r"\D+", "", strip_text(value))


def _disease_match_text(value: Any) -> str:
    text = _match_text(value)
    return re.sub(r"^benh", "", text)


def _date_distance_days(left: Any, right: Any) -> int | None:
    a = _date_obj(strip_text(left))
    b = _date_obj(strip_text(right))
    if not a or not b:
        return None
    return abs((a.date() - b.date()).days)


def _case_pair_score(a: dict[str, Any], b: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    code_a, code_b = _match_text(a.get("case_code")), _match_text(b.get("case_code"))
    id_a, id_b = _match_digits(a.get("national_id")), _match_digits(b.get("national_id"))
    phone_a, phone_b = _match_digits(a.get("phone"))[-9:], _match_digits(b.get("phone"))[-9:]
    name_a, name_b = _match_text(a.get("full_name")), _match_text(b.get("full_name"))

    if code_a and code_a == code_b:
        return 100, ["Trùng mã ca bệnh"]
    if len(id_a) >= 9 and id_a == id_b:
        return 100, ["Trùng CCCD/CMND"]
    if name_a and name_a == name_b:
        score += 35
        reasons.append("Trùng họ tên")
    elif name_a and name_b:
        ratio = SequenceMatcher(None, name_a, name_b).ratio()
        if ratio >= 0.92:
            score += 28
            reasons.append(f"Họ tên gần giống {ratio:.0%}")

    if len(phone_a) >= 7 and phone_a == phone_b:
        score += 35
        reasons.append("Trùng số điện thoại")
    if a.get("birth_year") and a.get("birth_year") == b.get("birth_year"):
        score += 15
        reasons.append("Trùng năm sinh")
    if _match_text(a.get("gender")) and _match_text(a.get("gender")) == _match_text(b.get("gender")):
        score += 5
        reasons.append("Trùng giới tính")
    if _match_text(a.get("commune")) and _match_text(a.get("commune")) == _match_text(b.get("commune")):
        score += 8
        reasons.append("Trùng xã/phường")
    if _match_text(a.get("main_diagnosis")) and _match_text(a.get("main_diagnosis")) == _match_text(b.get("main_diagnosis")):
        score += 7
        reasons.append("Trùng chẩn đoán")
    days = _date_distance_days(a.get("onset_date"), b.get("onset_date"))
    if days == 0:
        score += 15
        reasons.append("Trùng ngày khởi phát")
    elif days is not None and days <= 3:
        score += 10
        reasons.append(f"Khởi phát lệch {days} ngày")
    elif days is not None and days <= 14:
        score += 4
        reasons.append(f"Khởi phát trong {days} ngày")
    addr_a, addr_b = _match_text(a.get("current_address")), _match_text(b.get("current_address"))
    if addr_a and addr_b and SequenceMatcher(None, addr_a, addr_b).ratio() >= 0.85:
        score += 5
        reasons.append("Địa chỉ gần giống")
    return min(score, 99), reasons


def _outbreak_pair_score(a: dict[str, Any], b: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    disease_a, disease_b = _disease_match_text(a.get("disease")), _disease_match_text(b.get("disease"))
    location_a, location_b = _match_text(a.get("location")), _match_text(b.get("location"))
    if disease_a and disease_a == disease_b:
        score += 30
        reasons.append("Trùng tên bệnh")
    else:
        return 0, []
    if location_a and location_a == location_b:
        score += 45
        reasons.append("Trùng địa điểm ổ dịch")
    elif location_a and location_b:
        ratio = SequenceMatcher(None, location_a, location_b).ratio()
        if ratio >= 0.88:
            score += 35
            reasons.append(f"Địa điểm gần giống {ratio:.0%}")
        elif ratio >= 0.75:
            score += 20
            reasons.append(f"Địa điểm tương tự {ratio:.0%}")
    if _match_text(a.get("admin_area")) and _match_text(a.get("admin_area")) == _match_text(b.get("admin_area")):
        score += 10
        reasons.append("Trùng địa bàn")
    days = _date_distance_days(a.get("first_onset_date"), b.get("first_onset_date"))
    if days == 0:
        score += 20
        reasons.append("Trùng ngày khởi phát ca đầu")
    elif days is not None and days <= 7:
        score += 15
        reasons.append(f"Khởi phát ca đầu lệch {days} ngày")
    elif days is not None and days <= 14:
        score += 8
        reasons.append(f"Khởi phát ca đầu trong {days} ngày")
    if _match_text(a.get("reporting_unit")) and _match_text(a.get("reporting_unit")) == _match_text(b.get("reporting_unit")):
        score += 5
        reasons.append("Trùng đơn vị báo cáo")
    return min(score, 99), reasons


def find_duplicate_groups(
    entity_type: str,
    *,
    min_score: int = 65,
    max_records: int = 20000,
    db_path: Path | str = DB_PATH,
) -> list[dict[str, Any]]:
    """Phát hiện nhóm trùng nghiệp vụ; không tự động xóa hoặc gộp."""
    table, _ = _safe_table(entity_type)
    min_score = max(50, min(100, int(min_score)))
    if entity_type == "case":
        fields = [
            "id", "case_code", "full_name", "birth_date_raw", "birth_year", "gender",
            "national_id", "phone", "current_address", "commune", "main_diagnosis",
            "onset_date", "report_datetime", "reporting_unit", "source_file", "source_row",
        ]
    else:
        fields = [
            "id", "disease", "location", "admin_area", "first_onset_date", "last_onset_date",
            "status", "case_count", "report_datetime", "reporting_unit", "source_file", "source_row",
        ]
    with _connect(db_path) as conn:
        rows = [dict(r) for r in conn.execute(
            f"SELECT {','.join(fields)} FROM {table} ORDER BY id LIMIT ?", (max_records,)
        ).fetchall()]
    if len(rows) < 2:
        return []

    buckets: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        keys: set[str] = set()
        if entity_type == "case":
            code = _match_text(row.get("case_code"))
            national_id = _match_digits(row.get("national_id"))
            phone = _match_digits(row.get("phone"))[-9:]
            name = _match_text(row.get("full_name"))
            year = row.get("birth_year") or ""
            commune = _match_text(row.get("commune"))
            if code: keys.add("code:" + code)
            if len(national_id) >= 9: keys.add("nid:" + national_id)
            if len(phone) >= 7: keys.add("phone:" + phone)
            if name and year: keys.add(f"nameyear:{name}:{year}")
            if name and commune: keys.add(f"namearea:{name}:{commune}")
            if name: keys.add("name:" + name)
        else:
            disease = _disease_match_text(row.get("disease"))
            location = _match_text(row.get("location"))
            area = _match_text(row.get("admin_area"))
            if disease and location: keys.add(f"event:{disease}:{location}")
            if disease and area: keys.add(f"eventarea:{disease}:{area}")
        for key in keys:
            buckets.setdefault(key, []).append(index)

    candidate_pairs: set[tuple[int, int]] = set()
    for indexes in buckets.values():
        if len(indexes) > 250:
            indexes = indexes[:250]
        for pos, left in enumerate(indexes):
            for right in indexes[pos + 1:]:
                candidate_pairs.add((min(left, right), max(left, right)))

    edges: list[tuple[int, int, int, list[str]]] = []
    scorer = _case_pair_score if entity_type == "case" else _outbreak_pair_score
    for left, right in candidate_pairs:
        score, reasons = scorer(rows[left], rows[right])
        if score >= min_score:
            edges.append((left, right, score, reasons))
    if not edges:
        return []

    parent = list(range(len(rows)))
    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb: parent[rb] = ra
    for left, right, _, _ in edges:
        union(left, right)

    groups: dict[int, set[int]] = {}
    for left, right, _, _ in edges:
        root = find(left)
        groups.setdefault(root, set()).update((left, right))

    result: list[dict[str, Any]] = []
    for group_no, indexes in enumerate(sorted(groups.values(), key=lambda g: min(rows[i]["id"] for i in g)), start=1):
        group_edges = [edge for edge in edges if edge[0] in indexes and edge[1] in indexes]
        best_score = max(edge[2] for edge in group_edges)
        all_reasons: list[str] = []
        for _, _, _, edge_reasons in sorted(group_edges, key=lambda e: e[2], reverse=True):
            for reason in edge_reasons:
                if reason not in all_reasons:
                    all_reasons.append(reason)
        records = [rows[i] for i in sorted(indexes, key=lambda i: rows[i]["id"])]
        if entity_type == "case":
            summary = " / ".join(str(r.get("full_name") or r.get("case_code") or r["id"]) for r in records[:3])
        else:
            summary = " / ".join(str(r.get("location") or r["id"]) for r in records[:3])
        result.append({
            "group_id": group_no,
            "entity_type": entity_type,
            "confidence": "Trùng chắc chắn" if best_score >= 85 else "Nghi trùng",
            "score": best_score,
            "record_count": len(records),
            "record_ids": [int(r["id"]) for r in records],
            "summary": summary,
            "reasons": "; ".join(all_reasons[:8]),
            "records": records,
        })
    return sorted(result, key=lambda g: (-int(g["score"]), int(g["group_id"])))


def remove_duplicate_records(
    entity_type: str,
    keep_id: int,
    remove_ids: Sequence[int],
    db_path: Path | str = DB_PATH,
) -> dict[str, Any]:
    table, _ = _safe_table(entity_type)
    keep_id = int(keep_id)
    ids = sorted({int(v) for v in remove_ids if int(v) != keep_id})
    if not ids:
        raise ValueError("Chưa chọn bản ghi trùng để xóa.")
    with _connect(db_path) as conn:
        existing = {int(r[0]) for r in conn.execute(
            f"SELECT id FROM {table} WHERE id IN ({','.join('?' for _ in [keep_id, *ids])})",
            [keep_id, *ids],
        ).fetchall()}
    if keep_id not in existing:
        raise ValueError("Bản ghi cần giữ không tồn tại.")
    missing = [record_id for record_id in ids if record_id not in existing]
    if missing:
        raise ValueError(f"Bản ghi cần xóa không tồn tại: {missing}")
    backup = create_backup(db_path)
    with _connect(db_path) as conn:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", ids)
        conn.execute(
            f"DELETE FROM data_quality_issues WHERE entity_type=? AND entity_id IN ({placeholders})",
            [entity_type, *ids],
        )
        conn.execute(
            """INSERT INTO duplicate_actions
               (entity_type, keep_id, removed_ids_json, backup_file, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (entity_type, keep_id, json.dumps(ids), str(backup), datetime.now().isoformat(sep=" ", timespec="seconds")),
        )
    return {"kept_id": keep_id, "removed_ids": ids, "removed_count": len(ids), "backup_file": str(backup)}


def list_quality_issues(
    *, severity: str = "", entity_type: str = "", limit: int = 2000, db_path: Path | str = DB_PATH
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if severity:
        where.append("severity=?")
        params.append(severity)
    if entity_type:
        where.append("entity_type=?")
        params.append(entity_type)
    sql_where = " WHERE " + " AND ".join(where) if where else ""
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT id, entity_type, entity_id, severity, issue_type, description, source_file, source_row, created_at
                FROM data_quality_issues{sql_where}
                ORDER BY CASE severity WHEN 'error' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END, id DESC LIMIT ?""",
            [*params, limit],
        ).fetchall()
        return [dict(r) for r in rows]


def list_import_batches(db_path: Path | str = DB_PATH, limit: int = 50) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM import_batches ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def execute_select(sql: str, db_path: Path | str = DB_PATH, max_rows: int = 5000) -> tuple[list[str], list[list[Any]]]:
    cleaned = sql.strip().rstrip(";")
    if not re.match(r"^(SELECT|WITH)\b", cleaned, flags=re.I):
        raise ValueError("Chỉ cho phép câu lệnh SELECT hoặc WITH ... SELECT.")
    forbidden = re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|ATTACH|DETACH|PRAGMA|REPLACE|VACUUM|CREATE)\b", cleaned, flags=re.I)
    if forbidden:
        raise ValueError(f"Không cho phép từ khóa {forbidden.group(1).upper()} trong truy vấn.")
    with _connect(db_path) as conn:
        cur = conn.execute(cleaned)
        columns = [d[0] for d in cur.description or []]
        rows = [list(r) for r in cur.fetchmany(max_rows)]
        return columns, rows


def export_rows(path: Path | str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    path = Path(path)
    rows = list(rows)
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)
        return
    wb = Workbook()
    ws = wb.active
    ws.title = "Dữ liệu"
    ws.append(list(columns))
    for row in rows:
        ws.append(list(row))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.font = cell.font.copy(bold=True)
    for col in ws.columns:
        values = [str(c.value or "") for c in col[:200]]
        width = min(max(max((len(v) for v in values), default=8) + 2, 10), 45)
        ws.column_dimensions[col[0].column_letter].width = width
    wb.save(path)


def export_filtered_records(
    path: Path | str,
    entity_type: str,
    *,
    search: str = "",
    disease: str = "",
    status: str = "",
    admin_area: str = "",
    db_path: Path | str = DB_PATH,
) -> int:
    table, _ = _safe_table(entity_type)
    where: list[str] = []
    params: list[Any] = []
    if search:
        like = f"%{search}%"
        if entity_type == "case":
            where.append("(full_name LIKE ? OR case_code LIKE ? OR national_id LIKE ? OR current_address LIKE ? OR commune LIKE ?)")
            params.extend([like] * 5)
        else:
            where.append("(disease LIKE ? OR location LIKE ? OR reporting_unit LIKE ? OR admin_area LIKE ?)")
            params.extend([like] * 4)
    if disease:
        field = "main_diagnosis" if entity_type == "case" else "disease"
        where.append(f"{field} = ?")
        params.append(disease)
    if status:
        if entity_type == "case":
            where.append("(record_status = ? OR current_status = ?)")
            params.extend([status, status])
        else:
            where.append("status = ?")
            params.append(status)
    if admin_area:
        field = "commune" if entity_type == "case" else "admin_area"
        where.append(f"{field} = ?")
        params.append(admin_area)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    order = "onset_date DESC, id DESC" if entity_type == "case" else "first_onset_date DESC, id DESC"
    hidden = {"row_hash", "raw_json"}
    with _connect(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM {table}{where_sql}", params).fetchone()[0]
        if total == 0:
            raise ValueError("Không có dữ liệu phù hợp để xuất.")
        if total > 50_000:
            raise ValueError("Bộ lọc có trên 50.000 dòng. Hãy thu hẹp bộ lọc trước khi xuất.")
        db_columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall() if r[1] not in hidden]
        values = conn.execute(
            f"SELECT {','.join(db_columns)} FROM {table}{where_sql} ORDER BY {order}", params
        ).fetchall()
    labels = CASE_LABELS if entity_type == "case" else OUTBREAK_LABELS
    extra_labels = {
        "id": "ID",
        "birth_year": "Năm sinh",
        "admin_area": "Địa bàn chuẩn hóa",
        "source_file": "File nguồn",
        "source_sheet": "Sheet nguồn",
        "source_row": "Dòng nguồn",
        "imported_at": "Thời điểm nhập",
    }
    out_headers = [labels.get(c, extra_labels.get(c, c)) for c in db_columns]
    export_rows(path, out_headers, [[row[c] for c in db_columns] for row in values])
    return total


def create_backup(db_path: Path | str = DB_PATH) -> Path:
    db_path = Path(db_path)
    init_db(db_path)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = BACKUP_DIR / f"giam_sat_dich_benh_{stamp}.db"
    source = sqlite3.connect(db_path)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    backups = sorted(BACKUP_DIR.glob("giam_sat_dich_benh_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[10:]:
        old.unlink(missing_ok=True)
    return target


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')


init_db()
