from __future__ import annotations

import base64
import json
import socket
import tempfile
import threading
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import core
from deployment_config import DeploymentConfig, load_config

READ_FUNCTIONS = {
    "dashboard_stats", "disease_summary", "monthly_outbreak_summary", "recent_active_outbreaks",
    "list_filter_values", "query_records", "get_record", "list_quality_issues",
    "list_import_batches", "execute_select", "find_duplicate_groups",
}
WRITE_FUNCTIONS = {"save_outbreak", "delete_record", "remove_duplicate_records", "create_backup"}


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], config: DeploymentConfig):
        super().__init__(address, ApiHandler)
        self.config = config


class ApiHandler(BaseHTTPRequestHandler):
    server: ApiServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(_jsonable(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = self.server.config.password
        return not expected or self.headers.get("X-GSBTN-Password", "") == expected

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/health":
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Không tìm thấy endpoint."})
            return
        if not self._authorized():
            self._write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "Sai mật khẩu máy chủ."})
            return
        self._write_json(HTTPStatus.OK, {
            "ok": True, "app": core.APP_NAME, "version": core.VERSION, "mode": "server",
            "lan_ip": get_lan_ip(), "port": self.server.server_port,
            "password_required": bool(self.server.config.password),
        })

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "Sai mật khẩu máy chủ."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 110 * 1024 * 1024:
                raise ValueError("Kích thước yêu cầu vượt quá giới hạn 110 MB.")
            payload = json.loads((self.rfile.read(length) if length else b"{}").decode("utf-8"))
            if self.path.rstrip("/") == "/rpc":
                result = self._handle_rpc(payload)
            elif self.path.rstrip("/") == "/import":
                result = self._handle_import(payload)
            else:
                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Không tìm thấy endpoint."})
                return
            self._write_json(HTTPStatus.OK, {"ok": True, "result": result})
        except Exception as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def _handle_rpc(self, payload: dict[str, Any]) -> Any:
        function_name = str(payload.get("function", ""))
        if function_name not in READ_FUNCTIONS | WRITE_FUNCTIONS:
            raise ValueError("Hàm RPC không được phép.")
        function = getattr(core, function_name, None)
        if not callable(function):
            raise ValueError(f"Máy chủ chưa hỗ trợ hàm {function_name}.")
        args, kwargs = payload.get("args") or [], payload.get("kwargs") or {}
        if not isinstance(args, list) or not isinstance(kwargs, dict):
            raise ValueError("args/kwargs không hợp lệ.")
        # Máy trạm không được chọn đường dẫn CSDL trên máy chủ.
        kwargs.pop("db_path", None)
        return function(*args, **kwargs)

    def _handle_import(self, payload: dict[str, Any]) -> Any:
        name = Path(str(payload.get("file_name", "du_lieu.xlsx"))).name
        content = payload.get("content_base64")
        if not isinstance(content, str) or not content:
            raise ValueError("Thiếu nội dung file Excel.")
        if Path(name).suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ValueError("Chỉ chấp nhận file XLSX hoặc XLSM.")
        data = base64.b64decode(content.encode("ascii"), validate=True)
        if len(data) > 100 * 1024 * 1024:
            raise ValueError("File vượt quá giới hạn 100 MB.")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            path.write_bytes(data)
            return core.import_excel(path)


class LanServerController:
    def __init__(self, config: DeploymentConfig | None = None):
        self.config = config or load_config()
        self.httpd: ApiServer | None = None
        self.thread: threading.Thread | None = None
        self.last_error = ""

    @property
    def running(self) -> bool:
        return bool(self.httpd and self.thread and self.thread.is_alive())

    @property
    def port(self) -> int:
        return int(self.httpd.server_port if self.httpd else self.config.server_port)

    @property
    def address(self) -> str:
        return f"http://{get_lan_ip()}:{self.port}"

    def start(self) -> str:
        if self.running:
            return self.address
        core.init_db()
        try:
            self.httpd = ApiServer((self.config.server_host, self.config.server_port), self.config)
            self.thread = threading.Thread(target=self.httpd.serve_forever, name="GSBTN-LAN-Server", daemon=True)
            self.thread.start()
            self.last_error = ""
            return self.address
        except Exception as exc:
            self.httpd = None
            self.thread = None
            self.last_error = str(exc)
            raise

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
        self.httpd = None
        self.thread = None
