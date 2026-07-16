from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook

import core
import deployment_config


def make_excel(path: Path, fields, rows, sheet='Disease Cases'):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append([label for label, _ in fields])
    for values in rows:
        ws.append([values.get(key, '') for _, key in fields])
    wb.save(path)


def test_case_duplicate_detection_and_removal():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db = root / 'test.db'
        core.BACKUP_DIR = root / 'backups'
        file = root / 'cases.xlsx'
        base = {
            'full_name': 'Nguyễn Văn A', 'birth_date_raw': '01/01/1990', 'gender': 'Nam',
            'phone': '0901234567', 'commune': 'Phường Gia Viên',
            'main_diagnosis': 'Sốt xuất huyết Dengue', 'onset_date': '10/07/2026',
            'report_datetime': '11/07/2026 08:00', 'reporting_unit': 'Trạm Y tế',
        }
        rows = [dict(base, case_code='CA-001'), dict(base, case_code='CA-001-B', current_address='Gia Viên, Hải Phòng')]
        make_excel(file, core.CASE_FIELDS, rows)
        summary = core.import_excel(file, db)
        assert summary.inserted == 2
        groups = core.find_duplicate_groups('case', db_path=db, min_score=65)
        assert len(groups) == 1
        assert groups[0]['score'] >= 85
        ids = groups[0]['record_ids']
        result = core.remove_duplicate_records('case', ids[0], ids[1:], db_path=db)
        assert result['removed_count'] == 1
        assert Path(result['backup_file']).exists()
        assert core.dashboard_stats(db)['case_records'] == 1


def test_outbreak_duplicate_detection():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db = root / 'test.db'
        file = root / 'outbreaks.xlsx'
        rows = [
            {'disease': 'Bệnh sốt xuất huyết Dengue', 'location': 'Tổ 1 - Phường Gia Viên - Hải Phòng',
             'first_onset_date': '10/07/2026', 'case_count': 2, 'report_datetime': '11/07/2026 08:00',
             'reporting_unit': 'Trạm Y tế Gia Viên'},
            {'disease': 'Sốt xuất huyết Dengue', 'location': 'Tổ 1, Phường Gia Viên, Hải Phòng',
             'first_onset_date': '11/07/2026', 'case_count': 3, 'report_datetime': '12/07/2026 08:00',
             'reporting_unit': 'Trạm Y tế Gia Viên'},
        ]
        make_excel(file, core.OUTBREAK_FIELDS, rows, 'Danh sách ổ dịch')
        assert core.import_excel(file, db).inserted == 2
        groups = core.find_duplicate_groups('outbreak', db_path=db, min_score=60)
        assert groups and groups[0]['record_count'] == 2


def test_deployment_config_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        old = deployment_config.CONFIG_PATH
        deployment_config.CONFIG_PATH = Path(tmp) / 'deployment.json'
        try:
            cfg = deployment_config.DeploymentConfig(
                mode='server', server_port=9001, password='abc', auto_start_server=False
            )
            deployment_config.save_config(cfg)
            loaded = deployment_config.load_config()
            assert loaded.mode == 'server'
            assert loaded.server_port == 9001
            assert loaded.password == 'abc'
            assert not loaded.auto_start_server
        finally:
            deployment_config.CONFIG_PATH = old


def test_lan_server_password_and_health():
    with tempfile.TemporaryDirectory() as tmp:
        code = r'''
import json, os
from urllib.error import HTTPError
from urllib.request import Request, urlopen
os.environ['GIAM_SAT_DICH_BENH_DATA_DIR'] = os.environ['TEST_DATA_DIR']
import core
from deployment_config import DeploymentConfig
from lan_server import LanServerController
cfg = DeploymentConfig(mode='server', server_host='127.0.0.1', server_port=0, password='secret')
server = LanServerController(cfg)
try:
    server.start()
    url = f'http://127.0.0.1:{server.port}/health'
    try:
        urlopen(url, timeout=5)
        raise AssertionError('request without password must fail')
    except HTTPError as exc:
        assert exc.code == 401
    req = Request(url, headers={'X-GSBTN-Password': 'secret'})
    with urlopen(req, timeout=5) as response:
        body = json.loads(response.read().decode('utf-8'))
    assert body['ok'] is True
    assert body['port'] == server.port
    forbidden = os.path.join(os.environ['TEST_DATA_DIR'], 'should_not_exist.db')
    rpc = Request(
        f'http://127.0.0.1:{server.port}/rpc',
        data=json.dumps({'function': 'dashboard_stats', 'kwargs': {'db_path': forbidden}}).encode('utf-8'),
        headers={'X-GSBTN-Password': 'secret', 'Content-Type': 'application/json'},
        method='POST',
    )
    with urlopen(rpc, timeout=5) as response:
        result = json.loads(response.read().decode('utf-8'))
    assert result['ok'] is True
    assert not os.path.exists(forbidden)
finally:
    server.stop()
'''
        env = dict(os.environ, TEST_DATA_DIR=tmp)
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr + result.stdout


def test_source_compiles():
    root = Path(__file__).parents[1]
    for name in ('app.py', 'core.py', 'deployment_config.py', 'lan_server.py', 'remote_core.py'):
        compile((root / name).read_text(encoding='utf-8'), name, 'exec')
