from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import core
import deployment
from lan_api import LanApiServer, PASSWORD_HEADER

_config = deployment.load_config()
_server: LanApiServer | None = None


def config() -> deployment.DeploymentConfig:
    return _config


def reload_config() -> deployment.DeploymentConfig:
    global _config
    _config = deployment.load_config()
    return _config


def is_workstation() -> bool:
    return _config.mode == deployment.MODE_WORKSTATION


def is_server() -> bool:
    return _config.mode == deployment.MODE_SERVER


def is_standalone() -> bool:
    return _config.mode == deployment.MODE_STANDALONE


def mode_label() -> str:
    return _config.mode_label


def data_source_label() -> str:
    if is_workstation():
        return f"Máy chủ LAN: {_config.server_url}"
    return f"CSDL: {core.DB_PATH}"


def _request(path: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> Any:
    url = _config.server_url.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json", PASSWORD_HEADER: _config.password}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
        method = "POST"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", str(exc))
        except Exception:
            detail = str(exc)
        raise ConnectionError(detail) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ConnectionError(f"Không kết nối được máy chủ {_config.server_url}: {exc}") from exc
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ConnectionError("Máy chủ trả về dữ liệu không hợp lệ.") from exc
    if not result.get("ok"):
        raise ConnectionError(str(result.get("error") or "Máy chủ từ chối yêu cầu."))
    return result.get("result")


def _call(method: str, *args: Any, timeout: int = 30, **kwargs: Any) -> Any:
    return _request("/api/call", {"method": method, "args": list(args), "kwargs": kwargs}, timeout)


def initialize() -> dict[str, Any]:
    global _server
    reload_config()
    if is_workstation():
        return {"mode": _config.mode, "connected": test_connection()}
    core.init_db()
    if is_server() and _config.auto_start_server:
        _server = _server or LanApiServer(
            host="0.0.0.0",
            port=_config.server_port,
            password=_config.password,
            db_path=core.DB_PATH,
        )
        _server.start()
    return {"mode": _config.mode, "connected": True}


def shutdown() -> None:
    global _server
    if _server:
        _server.stop()
        _server = None


def test_connection() -> bool:
    if not is_workstation():
        return True
    _request("/api/health", timeout=5)
    return True


def update_deployment(new_config: deployment.DeploymentConfig) -> Path:
    global _config
    old_mode = _config.mode
    _config = new_config.normalized()
    path = deployment.save_config(_config)
    if old_mode == deployment.MODE_SERVER or _config.mode == deployment.MODE_SERVER:
        if _config.mode == deployment.MODE_SERVER:
            restart_server(_config.server_port, _config.password)
        else:
            stop_server()
    return path


def start_server() -> int:
    global _server
    if not is_server():
        raise RuntimeError("Chỉ chế độ Máy chủ mới được mở API LAN.")
    if _server is None:
        _server = LanApiServer("0.0.0.0", _config.server_port, _config.password, core.DB_PATH)
    return _server.start()


def stop_server() -> None:
    global _server
    if _server:
        _server.stop()
        _server = None


def restart_server(port: int | None = None, password: str | None = None) -> int:
    global _server, _config
    if port is not None:
        _config.server_port = int(port)
    if password is not None:
        _config.password = password
    deployment.save_config(_config)
    if _server:
        return _server.restart(port=_config.server_port, password=_config.password)
    _server = LanApiServer("0.0.0.0", _config.server_port, _config.password, core.DB_PATH)
    return _server.start()


def server_status() -> dict[str, Any]:
    if _server:
        result = _server.status()
    else:
        result = {
            "running": False,
            "host": "0.0.0.0",
            "port": _config.server_port,
            "password_required": bool(_config.password),
            "database": str(core.DB_PATH),
            "clients": [],
            "logs": [],
        }
    result["addresses"] = deployment.public_server_addresses(_config)
    return result


def init_db() -> None:
    if is_workstation():
        test_connection()
    else:
        core.init_db()


def dashboard_stats() -> dict[str, Any]:
    return _call("dashboard_stats") if is_workstation() else core.dashboard_stats()


def disease_summary(limit: int = 15) -> list[dict[str, Any]]:
    return _call("disease_summary", limit) if is_workstation() else core.disease_summary(limit=limit)


def monthly_outbreak_summary(limit: int = 18) -> list[dict[str, Any]]:
    return _call("monthly_outbreak_summary", limit) if is_workstation() else core.monthly_outbreak_summary(limit=limit)


def recent_active_outbreaks(limit: int = 20) -> list[dict[str, Any]]:
    return _call("recent_active_outbreaks", limit) if is_workstation() else core.recent_active_outbreaks(limit=limit)


def query_records(entity_type: str, **kwargs: Any) -> tuple[list[dict[str, Any]], int]:
    if is_workstation():
        value = _call("query_records", entity_type, **kwargs)
        return list(value[0]), int(value[1])
    return core.query_records(entity_type, **kwargs)


def list_filter_values(entity_type: str, field: str) -> list[str]:
    if is_workstation():
        return list(_call("list_filter_values", entity_type, field))
    return core.list_filter_values(entity_type, field)


def get_record(entity_type: str, record_id: int) -> dict[str, Any] | None:
    if is_workstation():
        return _call("get_record", entity_type, record_id)
    return core.get_record(entity_type, record_id)


def save_outbreak(data: dict[str, Any], record_id: int | None = None) -> int:
    if is_workstation():
        return int(_call("save_outbreak", data, record_id))
    return core.save_outbreak(data, record_id)


def delete_record(entity_type: str, record_id: int) -> None:
    if is_workstation():
        _call("delete_record", entity_type, record_id)
    else:
        core.delete_record(entity_type, record_id)


def list_quality_issues(**kwargs: Any) -> list[dict[str, Any]]:
    if is_workstation():
        return list(_call("list_quality_issues", **kwargs))
    return core.list_quality_issues(**kwargs)


def list_import_batches(limit: int = 50) -> list[dict[str, Any]]:
    if is_workstation():
        return list(_call("list_import_batches", limit))
    return core.list_import_batches(limit=limit)


def execute_select(sql: str, max_rows: int = 5000) -> tuple[list[str], list[list[Any]]]:
    if is_workstation():
        value = _call("execute_select", sql, max_rows)
        return list(value[0]), list(value[1])
    return core.execute_select(sql, max_rows=max_rows)


def import_excel(path: Path | str) -> core.ImportSummary:
    path = Path(path)
    if not is_workstation():
        return core.import_excel(path)
    content = path.read_bytes()
    if len(content) > 75 * 1024 * 1024:
        raise ValueError("File Excel vượt quá 75 MB; hãy nhập trực tiếp trên máy chủ.")
    value = _request(
        "/api/import",
        {
            "filename": path.name,
            "content_base64": base64.b64encode(content).decode("ascii"),
        },
        timeout=180,
    )
    return core.ImportSummary(**value)


def export_filtered_records(path: Path | str, entity_type: str, **filters: Any) -> int:
    path = Path(path)
    if not is_workstation():
        return core.export_filtered_records(path, entity_type, **filters)
    value = _request(
        "/api/export",
        {"entity_type": entity_type, "suffix": path.suffix.lower() or ".xlsx", "filters": filters},
        timeout=180,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(value["content_base64"]))
    return int(value["count"])


def export_rows(path: Path | str, columns, rows) -> None:
    core.export_rows(path, columns, rows)


def create_backup() -> Path:
    if is_workstation():
        value = _request("/api/backup", {}, timeout=120)
        return Path(str(value["path"]))
    return core.create_backup()


def open_folder(path: Path | str) -> None:
    if is_workstation():
        raise RuntimeError("Thư mục dữ liệu nằm trên máy chủ; máy trạm không thể mở trực tiếp.")
    core.open_folder(path)


def find_duplicate_groups(entity_type: str, threshold: int = 65, limit: int = 5000) -> list[dict[str, Any]]:
    if is_workstation():
        return list(_call("find_duplicate_groups", entity_type, threshold, limit, timeout=120))
    return core.find_duplicate_groups(entity_type, threshold=threshold, limit=limit)


def delete_duplicate_records(entity_type: str, keep_id: int, remove_ids: list[int]) -> int:
    if is_workstation():
        return int(_call("delete_duplicate_records", entity_type, keep_id, remove_ids, timeout=120))
    return core.delete_duplicate_records(entity_type, keep_id, remove_ids)


def open_local_path(path: Path | str) -> None:
    path = str(path)
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
