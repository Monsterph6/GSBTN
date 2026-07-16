from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MANIFEST_FILE_ID = "1gEk9LH7k40FgN7Ry68m0SHih-CwcF4l9"
DRIVE_DOWNLOAD_URL = "https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
USER_AGENT = "GiamSatDichBenh-Updater/1.0"


class UpdateError(RuntimeError):
    """Lỗi có thể hiển thị trực tiếp cho người dùng."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    release_file_id: str
    file_name: str
    sha256: str
    notes: str = ""
    published_at: str = ""
    package_root: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateInfo":
        required = ("version", "release_file_id", "file_name", "sha256")
        missing = [key for key in required if not str(data.get(key, "")).strip()]
        if missing:
            raise UpdateError("Tệp cập nhật thiếu trường: " + ", ".join(missing))
        sha256 = str(data["sha256"]).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise UpdateError("Mã kiểm tra SHA-256 trong tệp cập nhật không hợp lệ.")
        return cls(
            version=str(data["version"]).strip(),
            release_file_id=str(data["release_file_id"]).strip(),
            file_name=str(data["file_name"]).strip(),
            sha256=sha256,
            notes=str(data.get("notes", "")).strip(),
            published_at=str(data.get("published_at", "")).strip(),
            package_root=str(data.get("package_root", "")).strip(),
        )


def version_key(version: str) -> tuple[int, ...]:
    """Chuyển 1.2.10-beta thành (1, 2, 10) để so sánh an toàn."""
    numbers = re.findall(r"\d+", version)
    return tuple(int(x) for x in numbers) or (0,)


def is_newer_version(remote_version: str, current_version: str) -> bool:
    remote = list(version_key(remote_version))
    current = list(version_key(current_version))
    length = max(len(remote), len(current))
    remote.extend([0] * (length - len(remote)))
    current.extend([0] * (length - len(current)))
    return tuple(remote) > tuple(current)


def drive_download_url(file_id: str) -> str:
    file_id = str(file_id).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,}", file_id):
        raise UpdateError("ID tệp Google Drive không hợp lệ.")
    return DRIVE_DOWNLOAD_URL.format(file_id=file_id)


def _looks_like_html(data: bytes, content_type: str = "") -> bool:
    prefix = data[:512].lstrip().lower()
    return "text/html" in content_type.lower() or prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html")


def download_drive_file(
    file_id: str,
    destination: Path | None = None,
    progress: Callable[[int, int | None], None] | None = None,
    timeout: int = 60,
) -> bytes | Path:
    """Tải tệp Drive công khai. Khi destination=None trả bytes, ngược lại trả Path."""
    request = urllib.request.Request(drive_download_url(file_id), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            total_header = response.headers.get("Content-Length")
            total = int(total_header) if total_header and total_header.isdigit() else None
            if destination is None:
                data = response.read()
                if _looks_like_html(data, content_type):
                    raise UpdateError(
                        "Google Drive trả về trang đăng nhập thay vì tệp cập nhật. "
                        "Hãy đặt quyền chia sẻ tệp thành ‘Bất kỳ ai có đường liên kết – Người xem’."
                    )
                return data

            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            downloaded = 0
            first_chunk = b""
            with destination.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    if not first_chunk:
                        first_chunk = chunk[:512]
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, total)
            if _looks_like_html(first_chunk, content_type):
                destination.unlink(missing_ok=True)
                raise UpdateError(
                    "Không tải được gói cập nhật vì tệp Google Drive chưa được chia sẻ công khai."
                )
            return destination
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"Google Drive từ chối tải tệp (HTTP {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"Không kết nối được Google Drive: {exc.reason}") from exc


def fetch_manifest(file_id: str = MANIFEST_FILE_ID, timeout: int = 15) -> UpdateInfo:
    raw = download_drive_file(file_id, timeout=timeout)
    assert isinstance(raw, bytes)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("Tệp update_manifest.json không phải JSON hợp lệ.") from exc
    if not isinstance(data, dict):
        raise UpdateError("Nội dung tệp cập nhật không hợp lệ.")
    return UpdateInfo.from_dict(data)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_download(path: Path, expected_sha256: str) -> None:
    actual = sha256_file(path)
    if actual.lower() != expected_sha256.lower():
        Path(path).unlink(missing_ok=True)
        raise UpdateError(
            "Gói cập nhật tải về không đúng mã SHA-256. Tệp đã bị xóa để bảo đảm an toàn."
        )


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_windows_apply_script(
    zip_path: Path,
    install_dir: Path,
    package_root: str,
    launch_path: Path,
    launch_argument: str = "",
) -> Path:
    """Tạo PowerShell chạy sau khi app đóng để thay tệp, giữ nguyên data/backups."""
    fd, script_name = tempfile.mkstemp(prefix="giam_sat_dich_benh_update_", suffix=".ps1")
    os.close(fd)
    script_path = Path(script_name)
    script = f"""
$ErrorActionPreference = 'Stop'
$ProcessId = {os.getpid()}
$ZipPath = {_ps_quote(str(Path(zip_path).resolve()))}
$InstallDir = {_ps_quote(str(Path(install_dir).resolve()))}
$PackageRoot = {_ps_quote(package_root)}
$LaunchPath = {_ps_quote(str(Path(launch_path).resolve()))}
$LaunchArgument = {_ps_quote(launch_argument)}
$LogPath = Join-Path $env:TEMP 'giam_sat_dich_benh_update.log'

try {{
    Wait-Process -Id $ProcessId -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
    $Staging = Join-Path $env:TEMP ('giam_sat_update_' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Staging -Force | Out-Null
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $Staging -Force

    if ($PackageRoot -and (Test-Path (Join-Path $Staging $PackageRoot))) {{
        $Source = Join-Path $Staging $PackageRoot
    }} else {{
        $Children = @(Get-ChildItem -LiteralPath $Staging -Force)
        if ($Children.Count -eq 1 -and $Children[0].PSIsContainer) {{
            $Source = $Children[0].FullName
        }} else {{
            $Source = $Staging
        }}
    }}

    $Preserve = @('data', 'backups', 'update_cache', 'app_password.hash', 'update_config.json')
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {{
        if ($Preserve -notcontains $_.Name) {{
            $Target = Join-Path $InstallDir $_.Name
            if (Test-Path $Target) {{ Remove-Item -LiteralPath $Target -Recurse -Force }}
            Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force
        }}
    }}

    Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
    'Update completed at ' + (Get-Date) | Set-Content -LiteralPath $LogPath -Encoding UTF8

    if ($LaunchArgument) {{
        Start-Process -FilePath $LaunchPath -ArgumentList @(( '\"' + $LaunchArgument + '\"')) -WorkingDirectory $InstallDir
    }} else {{
        Start-Process -FilePath $LaunchPath -WorkingDirectory $InstallDir
    }}
}} catch {{
    ($_ | Out-String) | Set-Content -LiteralPath $LogPath -Encoding UTF8
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        'Cập nhật không hoàn tất. Xem nhật ký tại: ' + $LogPath,
        'Giám sát dịch bệnh', 'OK', 'Error'
    ) | Out-Null
}}
""".strip()
    script_path.write_text(script, encoding="utf-8-sig")
    return script_path


def launch_update_and_exit(zip_path: Path, install_dir: Path, package_root: str = "") -> None:
    if os.name != "nt":
        raise UpdateError("Tự cập nhật hiện chỉ hỗ trợ Windows.")
    if getattr(sys, "frozen", False):
        launch_path = Path(sys.executable)
        launch_argument = ""
    else:
        launch_path = Path(sys.executable)
        launch_argument = str((Path(install_dir) / "app.py").resolve())
    script = create_windows_apply_script(
        zip_path=zip_path,
        install_dir=install_dir,
        package_root=package_root,
        launch_path=launch_path,
        launch_argument=launch_argument,
    )
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        cwd=str(install_dir),
        close_fds=True,
        creationflags=creationflags,
    )
