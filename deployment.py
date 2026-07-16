from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MODE_STANDALONE = "standalone"
MODE_WORKSTATION = "workstation"
MODE_SERVER = "server"
VALID_MODES = {MODE_STANDALONE, MODE_WORKSTATION, MODE_SERVER}
DEFAULT_PORT = 8765


def user_data_root() -> Path:
    override = os.environ.get("GIAM_SAT_DICH_BENH_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "CDC_HaiPhong" / "GiamSatDichBenh"
    return Path.home() / ".giam_sat_dich_benh"


CONFIG_PATH = user_data_root() / "deployment.json"


@dataclass(slots=True)
class DeploymentConfig:
    mode: str = MODE_STANDALONE
    server_host: str = "127.0.0.1"
    server_port: int = DEFAULT_PORT
    password: str = ""
    auto_start_server: bool = True

    def normalized(self) -> "DeploymentConfig":
        mode = self.mode if self.mode in VALID_MODES else MODE_STANDALONE
        host = str(self.server_host or "127.0.0.1").strip()
        if mode == MODE_SERVER:
            host = "0.0.0.0"
        port = int(self.server_port or DEFAULT_PORT)
        if not 1 <= port <= 65535:
            port = DEFAULT_PORT
        return DeploymentConfig(
            mode=mode,
            server_host=host,
            server_port=port,
            password=str(self.password or ""),
            auto_start_server=bool(self.auto_start_server),
        )

    @property
    def server_url(self) -> str:
        host = self.server_host
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        return f"http://{host}:{self.server_port}"

    @property
    def mode_label(self) -> str:
        return {
            MODE_STANDALONE: "Máy đơn lẻ",
            MODE_WORKSTATION: "Máy trạm",
            MODE_SERVER: "Máy chủ",
        }.get(self.mode, self.mode)


def load_config(path: Path | str = CONFIG_PATH) -> DeploymentConfig:
    path = Path(path)
    if not path.exists():
        config = DeploymentConfig()
        save_config(config, path)
        return config
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return DeploymentConfig()
    return DeploymentConfig(
        mode=str(raw.get("mode", MODE_STANDALONE)),
        server_host=str(raw.get("server_host", "127.0.0.1")),
        server_port=int(raw.get("server_port", DEFAULT_PORT) or DEFAULT_PORT),
        password=str(raw.get("password", "")),
        auto_start_server=bool(raw.get("auto_start_server", True)),
    ).normalized()


def save_config(config: DeploymentConfig, path: Path | str = CONFIG_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = config.normalized()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(normalized), ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return path


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if address and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
        if address and not address.startswith("127."):
            addresses.add(address)
        probe.close()
    except OSError:
        pass
    return sorted(addresses)


def public_server_addresses(config: DeploymentConfig | None = None) -> list[str]:
    config = (config or load_config()).normalized()
    return [f"http://{ip}:{config.server_port}" for ip in local_ipv4_addresses()]
