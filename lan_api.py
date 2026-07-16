from __future__ import annotations

import base64
import hmac
import json
import tempfile
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import core

MAX_REQUEST_BYTES = 100 * 1024 * 1024
PASSWORD_HEADER = "X-GSBTN-Password"


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


class _ApiHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, request_handler_class, owner: "LanApiServer"):
        self.owner = owner
        super().__init__(server_address, request_handler_class)


class _Handler(BaseHTTPRequestHandler):
    server_version = "GSBTN-LAN/1.0"

    @property
    def owner(self) -> "LanApiServer":
        return self.server.owner  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        self.owner.add_log(f"{self.client_address[0]} — {fmt % args}")

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(_json_safe(payload), ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _authenticated(self) -> bool:
        expected = self.owner.password
        if not expected:
            return True
        supplied = self.headers.get(PASSWORD_HEADER, "")
        return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

    def _authorize(self) -> bool:
        if self._authenticated():
            self.owner.touch_client(self.client_address[0])
            return True
        self._send(401, {"ok": False, "error": "Sai hoặc thiếu mật khẩu kết nối máy chủ."})
        return False

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        if length > MAX_REQUEST_BYTES:
            raise ValueError("Gói dữ liệu vượt quá 100 MB.")
        raw = self.rfile.read(length)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Nội dung yêu cầu phải là đối tượng JSON.")
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {"/api/health", "/api/status"}:
            self._send(404, {"ok": False, "error": "Không tìm thấy API."})
            return
        if not self._authorize():
            return
        if path == "/api/status":
            self._send(200, {"ok": True, "result": self.owner.status()})
            return
        self._send(
            200,
            {
                "ok": True,
                "result": {
                    "app": core.APP_NAME,
                    "version": core.VERSION,
                    "server_time": datetime.now().isoformat(sep=" ", timespec="seconds"),
                    "password_required": bool(self.owner.password),
                },
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorize():
            return
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/call":
                result = self.owner.call(
                    str(payload.get("method", "")),
                    list(payload.get("args", [])),
                    dict(payload.get("kwargs", {})),
                )
            elif path == "/api/import":
                result = self.owner.import_excel_payload(payload)
            elif path == "/api/export":
                result = self.owner.export_payload(payload)
            elif path == "/api/backup":
                result = {"path": str(core.create_backup(self.owner.db_path))}
            else:
                self._send(404, {"ok": False, "error": "Không tìm thấy API."})
                return
            self._send(200, {"ok": True, "result": result})
        except PermissionError as exc:
            self._send(403, {"ok": False, "error": str(exc)})
        except (ValueError, TypeError, KeyError, FileNotFoundError) as exc:
            self._send(400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # pragma: no cover - hàng rào cuối của tiến trình máy chủ
            self.owner.add_log(f"Lỗi API: {type(exc).__name__}: {exc}")
            self._send(500, {"ok": False, "error": f"Lỗi máy chủ: {exc}"})


class LanApiServer:
    ALLOWED_CALLS: dict[str, Callable[..., Any]] = {
        "dashboard_stats": core.dashboard_stats,
        "disease_summary": core.disease_summary,
        "monthly_outbreak_summary": core.monthly_outbreak_summary,
        "recent_active_outbreaks": core.recent_active_outbreaks,
        "query_records": core.query_records,
        "list_filter_values": core.list_filter_values,
        "get_record": core.get_record,
        "save_outbreak": core.save_outbreak,
        "delete_record": core.delete_record,
        "list_quality_issues": core.list_quality_issues,
        "list_import_batches": core.list_import_batches,
        "execute_select": core.execute_select,
    }

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        password: str = "",
        db_path: Path | str = core.DB_PATH,
    ):
        self.host = host
        self.port = int(port)
        self.password = password or ""
        self.db_path = Path(db_path)
        self._httpd: _ApiHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._clients: dict[str, datetime] = {}
        self._logs: list[str] = []

    @classmethod
    def register_call(cls, name: str, function: Callable[..., Any]) -> None:
        cls.ALLOWED_CALLS[name] = function

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._httpd)

    @property
    def bound_port(self) -> int:
        if self._httpd:
            return int(self._httpd.server_address[1])
        return self.port

    def start(self) -> int:
        with self._lock:
            if self.running:
                return self.bound_port
            core.init_db(self.db_path)
            self._httpd = _ApiHttpServer((self.host, self.port), _Handler, self)
            self.port = int(self._httpd.server_address[1])
            self._thread = threading.Thread(
                target=self._httpd.serve_forever,
                name="GSBTN-LAN-Server",
                daemon=True,
            )
            self._thread.start()
            self.add_log(f"Máy chủ đã mở tại {self.host}:{self.port}")
            return self.port

    def stop(self) -> None:
        with self._lock:
            httpd = self._httpd
            thread = self._thread
            self._httpd = None
            self._thread = None
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self.add_log("Máy chủ LAN đã dừng.")

    def restart(self, *, port: int | None = None, password: str | None = None) -> int:
        self.stop()
        if port is not None:
            self.port = int(port)
        if password is not None:
            self.password = password
        return self.start()

    def touch_client(self, address: str) -> None:
        with self._lock:
            self._clients[address] = datetime.now()

    def connected_clients(self, active_minutes: int = 10) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(minutes=active_minutes)
        with self._lock:
            stale = [address for address, seen in self._clients.items() if seen < cutoff]
            for address in stale:
                self._clients.pop(address, None)
            return [
                {"address": address, "last_seen": seen.isoformat(sep=" ", timespec="seconds")}
                for address, seen in sorted(self._clients.items())
            ]

    def add_log(self, text: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S')} — {text}"
        with self._lock:
            self._logs.append(line)
            if len(self._logs) > 500:
                del self._logs[:-500]

    def logs(self, limit: int = 100) -> list[str]:
        with self._lock:
            return list(self._logs[-limit:])

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "host": self.host,
            "port": self.bound_port,
            "password_required": bool(self.password),
            "database": str(self.db_path),
            "clients": self.connected_clients(),
            "logs": self.logs(50),
        }

    def call(self, method: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
        function = self.ALLOWED_CALLS.get(method)
        if not function:
            raise PermissionError(f"Phương thức không được phép qua LAN: {method}")
        kwargs.pop("db_path", None)
        result = function(*args, **kwargs, db_path=self.db_path)
        return _json_safe(result)

    def import_excel_payload(self, payload: dict[str, Any]) -> Any:
        filename = Path(str(payload.get("filename") or "du_lieu.xlsx")).name
        if Path(filename).suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ValueError("Máy chủ chỉ nhận file .xlsx hoặc .xlsm.")
        encoded = str(payload.get("content_base64") or "")
        if not encoded:
            raise ValueError("Thiếu nội dung file Excel.")
        content = base64.b64decode(encoded, validate=True)
        with tempfile.TemporaryDirectory(prefix="gsbtn_import_") as tmp:
            path = Path(tmp) / filename
            path.write_bytes(content)
            summary = core.import_excel(path, self.db_path)
            return _json_safe(summary)

    def export_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        entity_type = str(payload.get("entity_type") or "")
        suffix = str(payload.get("suffix") or ".xlsx").lower()
        if suffix not in {".xlsx", ".csv"}:
            suffix = ".xlsx"
        filters = dict(payload.get("filters", {}))
        filters.pop("db_path", None)
        with tempfile.TemporaryDirectory(prefix="gsbtn_export_") as tmp:
            path = Path(tmp) / f"export{suffix}"
            count = core.export_filtered_records(path, entity_type, db_path=self.db_path, **filters)
            return {
                "count": count,
                "filename": path.name,
                "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            }
