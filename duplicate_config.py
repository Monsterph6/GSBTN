from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _user_data_root() -> Path:
    override = os.environ.get("GIAM_SAT_DICH_BENH_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "CDC_HaiPhong" / "GiamSatDichBenh"
    return Path.home() / ".giam_sat_dich_benh"


CONFIG_PATH = _user_data_root() / "duplicate_rules.json"

CASE_CRITERIA_DEFS: list[tuple[str, str]] = [
    ("case_code", "Trùng mã ca bệnh"),
    ("national_id", "Trùng CCCD/CMND"),
    ("phone", "Trùng số điện thoại"),
    ("name_birth_year", "Trùng họ tên + năm sinh"),
    ("name_commune", "Trùng họ tên + xã/phường"),
    ("name_similar", "Họ tên gần giống"),
    ("onset_near", "Ngày khởi phát gần nhau"),
]
CASE_CRITERIA_LABELS: dict[str, str] = dict(CASE_CRITERIA_DEFS)
DEFAULT_CASE_CRITERIA = ["case_code", "national_id"]

CRITERIA_CONFIG_PATH = _user_data_root() / "case_duplicate_criteria.json"


@dataclass
class CaseDuplicateCriteria:
    """Tiêu chí lọc trùng ca bệnh do CDC chọn — thay cho chấm điểm/trọng số.

    Riêng ``name_similar`` (họ tên gần giống) và ``onset_near`` (khởi phát gần ngày) chỉ so
    sánh các ca trong CÙNG một xã/phường — đây là phạm vi được chọn để giới hạn số cặp phải so
    khớp mờ (không có khoá chặn chính xác như các tiêu chí còn lại).
    """

    enabled: list[str] = field(default_factory=lambda: list(DEFAULT_CASE_CRITERIA))
    name_similarity_percent: int = 92
    onset_max_days: int = 3

    def normalized(self) -> "CaseDuplicateCriteria":
        valid = {criterion_id for criterion_id, _ in CASE_CRITERIA_DEFS}
        seen: list[str] = []
        for criterion_id in self.enabled or []:
            if criterion_id in valid and criterion_id not in seen:
                seen.append(criterion_id)
        self.enabled = seen or list(DEFAULT_CASE_CRITERIA)
        self.name_similarity_percent = max(50, min(100, int(self.name_similarity_percent)))
        self.onset_max_days = max(0, min(60, int(self.onset_max_days)))
        return self


def load_case_criteria() -> CaseDuplicateCriteria:
    if not CRITERIA_CONFIG_PATH.exists():
        return CaseDuplicateCriteria()
    try:
        raw = json.loads(CRITERIA_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CaseDuplicateCriteria()
    return CaseDuplicateCriteria(
        enabled=raw.get("enabled") or list(DEFAULT_CASE_CRITERIA),
        name_similarity_percent=raw.get("name_similarity_percent", 92),
        onset_max_days=raw.get("onset_max_days", 3),
    ).normalized()


def save_case_criteria(criteria: CaseDuplicateCriteria) -> Path:
    criteria.normalized()
    CRITERIA_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = CRITERIA_CONFIG_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(criteria), ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CRITERIA_CONFIG_PATH)
    return CRITERIA_CONFIG_PATH


DEFAULT_OUTBREAK_WEIGHTS = {
    "disease": 30,
    "location_exact": 45,
    "location_near": 35,
    "area": 10,
    "onset_exact": 20,
    "onset_near": 15,
    "reporting_unit": 5,
}


@dataclass
class DuplicateRules:
    """Ngưỡng/trọng số lọc trùng ổ dịch. Ca bệnh dùng CaseDuplicateCriteria (chọn tiêu chí)."""

    min_score: int = 65
    definite_score: int = 85
    outbreak_weights: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_OUTBREAK_WEIGHTS))

    def normalized(self) -> "DuplicateRules":
        self.min_score = max(40, min(100, int(self.min_score)))
        self.definite_score = max(self.min_score, min(100, int(self.definite_score)))
        self.outbreak_weights = _normalized_weights(self.outbreak_weights, DEFAULT_OUTBREAK_WEIGHTS)
        return self

    def weights_for(self, entity_type: str) -> dict[str, int]:
        return dict(self.outbreak_weights)


def _normalized_weights(values: dict[str, Any] | None, defaults: dict[str, int]) -> dict[str, int]:
    values = values or {}
    result: dict[str, int] = {}
    for key, default in defaults.items():
        try:
            result[key] = max(0, min(100, int(values.get(key, default))))
        except (TypeError, ValueError):
            result[key] = default
    return result


def load_rules() -> DuplicateRules:
    if not CONFIG_PATH.exists():
        return DuplicateRules()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DuplicateRules()
    return DuplicateRules(
        min_score=raw.get("min_score", 65),
        definite_score=raw.get("definite_score", 85),
        outbreak_weights=raw.get("outbreak_weights") or dict(DEFAULT_OUTBREAK_WEIGHTS),
    ).normalized()


def save_rules(rules: DuplicateRules) -> Path:
    rules.normalized()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(rules), ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CONFIG_PATH)
    return CONFIG_PATH
