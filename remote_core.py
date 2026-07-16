from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import core as local_core
from deployment_config import load_config

APP_NAME = local_core.APP_NAME
VERSION = local_core.VERSION
CASE_FIELDS = local_core.CASE_FIELDS
OUTBREAK_FIELDS = local_core.OUTBREAK_FIELDS
CASE_LABELS = local_core.CASE_LABELS
OUTBREAK_LABELS = local_core.OUTBREAK_LABELS
DATE_FIELDS = local_core.DATE_FIELDS
DATETIME_FIELDS = local_core.DATETIME_FIELDS
USER_DATA_DIR = local_core.USER_DATA_DIR
DATA_DIR = local_core.DATA_DIR
BACKUP_DIR = local_core.BACKUP_DIR
UPDATE_CACHE_DIR = local_core.UPDATE_CACHE_DIR
BASE_DIR = local_core.BASE_DIR
DB_PATH = "Máy chủ LAN"


def _request(path: str, payload: dict[str, Any] | None = None, timeout: int = 120) -> Any:
    config = load_config()
    url = config.server_url.rstrip("/") + path
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if config.password:
        headers["X-GSBTN-Password"] = config.password
    request = Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error")
        except Exception:
            detail = str(exc)
        raise ConnectionError(detail or f"Máy chủ trả lỗi HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ConnectionError(f"Không kết nối được máy chủ {url}: {exc}") from exc
    if not body.get("ok"):
        raise RuntimeError(body.get("error") or "Máy chủ trả về lỗi không xác định.")
    return body.get("result", body)


def _rpc(function: str, *args: Any, **kwargs: Any) -> Any:
    return _request("/rpc", {"function": function, "args": list(args), "kwargs": kwargs})


def health() -> dict[str, Any]:
    return _request("/health")


def init_db(*args: Any, **kwargs: Any) -> None:
    health()


def dashboard_stats(*args: Any, **kwargs: Any): return _rpc("dashboard_stats")
def disease_summary(*args: Any, **kwargs: Any): kwargs.pop("db_path", None); return _rpc("disease_summary", **kwargs)
def monthly_outbreak_summary(*args: Any, **kwargs: Any): kwargs.pop("db_path", None); return _rpc("monthly_outbreak_summary", **kwargs)
def recent_active_outbreaks(*args: Any, **kwargs: Any): kwargs.pop("db_path", None); return _rpc("recent_active_outbreaks", **kwargs)
def list_filter_values(entity_type: str, field: str, *args: Any, **kwargs: Any): return _rpc("list_filter_values", entity_type, field)


def query_records(entity_type: str, **kwargs: Any):
    kwargs.pop("db_path", None)
    result = _rpc("query_records", entity_type, **kwargs)
    return result[0], int(result[1])


def get_record(entity_type: str, record_id: int, *args: Any, **kwargs: Any): return _rpc("get_record", entity_type, record_id)
def save_outbreak(data: dict[str, Any], record_id: int | None = None, *args: Any, **kwargs: Any): return int(_rpc("save_outbreak", data, record_id))
def delete_record(entity_type: str, record_id: int, *args: Any, **kwargs: Any): return _rpc("delete_record", entity_type, record_id)
def list_quality_issues(**kwargs: Any): kwargs.pop("db_path", None); return _rpc("list_quality_issues", **kwargs)
def list_import_batches(*args: Any, **kwargs: Any): kwargs.pop("db_path", None); return _rpc("list_import_batches", **kwargs)


def execute_select(sql: str, *args: Any, **kwargs: Any):
    result = _rpc("execute_select", sql, max_rows=kwargs.get("max_rows", 5000))
    return result[0], result[1]


def import_excel(path: Path | str, *args: Any, **kwargs: Any):
    path = Path(path)
    result = _request("/import", {
        "file_name": path.name,
        "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }, timeout=300)
    return local_core.ImportSummary(**result)


def create_backup(*args: Any, **kwargs: Any): return Path(str(_rpc("create_backup")))
def find_duplicate_groups(entity_type: str, *args: Any, **kwargs: Any): kwargs.pop("db_path", None); return _rpc("find_duplicate_groups", entity_type, **kwargs)
def remove_duplicate_records(entity_type: str, keep_id: int, remove_ids: list[int], *args: Any, **kwargs: Any): return _rpc("remove_duplicate_records", entity_type, keep_id, remove_ids)


def export_rows(path: Path | str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    local_core.export_rows(path, columns, rows)


def export_filtered_records(path: Path | str, entity_type: str, **kwargs: Any) -> int:
    page, page_size, all_rows = 1, 2000, []
    while True:
        rows, total = query_records(entity_type, page=page, page_size=page_size, **kwargs)
        all_rows.extend(rows)
        if len(all_rows) >= total:
            break
        if len(all_rows) > 50_000:
            raise ValueError("Bộ lọc có trên 50.000 dòng. Hãy thu hẹp bộ lọc trước khi xuất.")
        page += 1
    if not all_rows:
        raise ValueError("Không có dữ liệu phù hợp để xuất.")
    columns = list(all_rows[0])
    labels = CASE_LABELS if entity_type == "case" else OUTBREAK_LABELS
    export_rows(path, [labels.get(c, c) for c in columns], [[r.get(c, "") for c in columns] for r in all_rows])
    return len(all_rows)


def open_folder(path: Path | str) -> None:
    local_core.open_folder(Path(path))
