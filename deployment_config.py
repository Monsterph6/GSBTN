from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

VALID_MODES = {"standalone", "workstation", "server"}


def _user_data_root() -> Path:
    override = os.environ.get("GIAM_SAT_DICH_BENH_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "CDC_HaiPhong" / "GiamSatDichBenh"
    return Path.home() / ".giam_sat_dich_benh"


CONFIG_PATH = _user_data_root() / "deployment.json"


@dataclass
class DeploymentConfig:
    mode: str = "standalone"
    server_host: str = "0.0.0.0"
    server_port: int = 8765
    server_url: str = "http://127.0.0.1:8765"
    password: str = ""
    auto_start_server: bool = True

    @property
    def is_standalone(self) -> bool:
        return self.mode == "standalone"

    @property
    def is_workstation(self) -> bool:
        return self.mode == "workstation"

    @property
    def is_server(self) -> bool:
        return self.mode == "server"


def load_config() -> DeploymentConfig:
    if not CONFIG_PATH.exists():
        return DeploymentConfig()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DeploymentConfig()
    mode = str(raw.get("mode", "standalone")).strip().lower()
    if mode not in VALID_MODES:
        mode = "standalone"
    try:
        port = int(raw.get("server_port", 8765))
    except (TypeError, ValueError):
        port = 8765
    port = max(1, min(65535, port))
    server_url = str(raw.get("server_url", f"http://127.0.0.1:{port}") or "").strip().rstrip("/")
    return DeploymentConfig(
        mode=mode,
        server_host=str(raw.get("server_host", "0.0.0.0") or "0.0.0.0").strip(),
        server_port=port,
        server_url=server_url or f"http://127.0.0.1:{port}",
        password=str(raw.get("password", "") or ""),
        auto_start_server=bool(raw.get("auto_start_server", True)),
    )


def save_config(config: DeploymentConfig) -> Path:
    if config.mode not in VALID_MODES:
        raise ValueError("Chế độ triển khai không hợp lệ.")
    config.server_port = max(1, min(65535, int(config.server_port)))
    config.server_url = config.server_url.strip().rstrip("/")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CONFIG_PATH)
    return CONFIG_PATH


def mode_label(mode: str) -> str:
    return {
        "standalone": "Máy đơn lẻ",
        "workstation": "Máy trạm",
        "server": "Máy chủ",
    }.get(mode, mode)
