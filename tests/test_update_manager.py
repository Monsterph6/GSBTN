from pathlib import Path

import pytest

import update_manager as um


def test_version_compare():
    assert um.is_newer_version("0.2.0", "0.1.11")
    assert um.is_newer_version("1.0", "0.9.9")
    assert not um.is_newer_version("1.0.0", "1.0")
    assert not um.is_newer_version("0.1.1", "0.2.0")


def test_update_info_validation():
    info = um.UpdateInfo.from_dict({
        "version": "0.2.0",
        "release_file_id": "1d4hzkQvesNw16vFxSsvQX8ue-I1jt4MY",
        "file_name": "release.zip",
        "sha256": "a" * 64,
    })
    assert info.version == "0.2.0"
    with pytest.raises(um.UpdateError):
        um.UpdateInfo.from_dict({"version": "0.2.0"})


def test_drive_url_validation():
    url = um.drive_download_url("1d4hzkQvesNw16vFxSsvQX8ue-I1jt4MY")
    assert "drive.usercontent.google.com" in url
    with pytest.raises(um.UpdateError):
        um.drive_download_url("bad id")


def test_sha256_file(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"abc")
    assert um.sha256_file(target) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_powershell_script_preserves_data(tmp_path: Path):
    zip_path = tmp_path / "release.zip"
    zip_path.write_bytes(b"zip")
    install_dir = tmp_path / "app"
    install_dir.mkdir()
    script = um.create_windows_apply_script(zip_path, install_dir, "root", Path("C:/Python/python.exe"), "app.py")
    text = script.read_text(encoding="utf-8-sig")
    assert "'data'" in text
    assert "'backups'" in text
    assert "Wait-Process" in text
    script.unlink()
