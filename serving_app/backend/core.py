"""웹 API의 오류·설정·CSV 입력 규약."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
import csv
import hashlib
import io
import json
import math
import os
from uuid import uuid4

FEATURE_CONTRACT = "gw-depth-rain/v1"
SCHEMA_VERSION = "groundwatch-daily/v1"
WELL_ID = "10000000-0000-4000-8000-000000000001"
COLUMNS = ["observed_date", "groundwater_depth_cm", "rainfall_mm"]


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def uid():
    return str(uuid4())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class APIError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details = [] if details is None else details


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("runtime/groundwatch.db")
    max_upload_bytes: int = 10 * 1024 * 1024
    rmse_threshold_cm: float | None = None
    gate_threshold_cm: float | None = None
    auto_retrain: bool = False
    stale_after_days: int | None = None
    policy_version: str = "unconfigured"

    def __post_init__(self):
        for value in (self.rmse_threshold_cm, self.gate_threshold_cm):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError("RMSE/Gate 기준은 유한한 양수여야 합니다.")
        if self.stale_after_days is not None and self.stale_after_days < 1:
            raise ValueError("지연 기준일 수는 1 이상이어야 합니다.")
        if self.auto_retrain and (self.rmse_threshold_cm is None or self.gate_threshold_cm is None):
            raise ValueError("자동 재학습에는 합의된 RMSE/Gate 기준이 모두 필요합니다.")
        if (self.rmse_threshold_cm is not None or self.auto_retrain) and self.policy_version == "unconfigured":
            raise ValueError("판정 정책 버전을 지정하세요.")

    @classmethod
    def from_env(cls):
        def optional(name, cast):
            raw = os.getenv(name)
            return cast(raw) if raw else None
        return cls(
            db_path=Path(os.getenv("GROUNDWATCH_DB_PATH", "runtime/groundwatch.db")),
            rmse_threshold_cm=optional("GROUNDWATCH_RMSE_THRESHOLD_CM", float),
            gate_threshold_cm=optional("GROUNDWATCH_GATE_THRESHOLD_CM", float),
            auto_retrain=os.getenv("GROUNDWATCH_AUTO_RETRAIN", "false").lower() == "true",
            stale_after_days=optional("GROUNDWATCH_STALE_AFTER_DAYS", int),
            policy_version=os.getenv("GROUNDWATCH_POLICY_VERSION", "unconfigured"),
        )

    def policy(self):
        return {"version": self.policy_version, "window_size": 21,
                "rmse_threshold_cm": self.rmse_threshold_cm,
                "gate_threshold_cm": self.gate_threshold_cm, "auto_retrain": self.auto_retrain}


def parse_csv(raw: bytes):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise APIError(422, "INVALID_DATA", "UTF-8 CSV 파일만 등록할 수 있습니다.") from exc
    reader = csv.DictReader(io.StringIO(text), strict=True)
    try:
        if reader.fieldnames != COLUMNS:
            raise APIError(422, "INVALID_DATA", "CSV 헤더와 순서를 확인하세요.", [{"expected": COLUMNS}])
        rows = []
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        for number, row in enumerate(reader, 2):
            if len(rows) >= 10000:
                raise APIError(422, "INVALID_DATA", "최대 10,000행까지 등록할 수 있습니다.")
            if None in row or any(row.get(key) in (None, "") for key in COLUMNS):
                raise APIError(422, "INVALID_DATA", "빈 값 또는 잘못된 열 수입니다.", [{"row": number, "reason": "missing_or_extra_value"}])
            for key in COLUMNS:
                try:
                    if key == "observed_date":
                        value = date.fromisoformat(row[key])
                        if value.isoformat() != row[key] or value > today:
                            raise ValueError()
                        if rows and value != date.fromisoformat(rows[-1][key]) + timedelta(days=1):
                            raise ValueError()
                        row[key] = value.isoformat()
                    else:
                        value = Decimal(row[key])
                        if not value.is_finite() or value < 0 or (key == "groundwater_depth_cm" and value == 0):
                            raise ValueError()
                        if key == "rainfall_mm" and value * 10 != (value * 10).to_integral_value():
                            raise ValueError()
                        numeric = float(value)
                        if not math.isfinite(numeric) or (key == "groundwater_depth_cm" and numeric <= 0):
                            raise ValueError()
                        row[key] = numeric
                except (ValueError, InvalidOperation, OverflowError) as exc:
                    raise APIError(422, "INVALID_DATA", "CSV의 날짜·단위·값을 확인하세요.",
                                   [{"row": number, "field": key, "reason": "invalid_value_or_nonconsecutive_date"}]) from exc
            rows.append(row)
    except csv.Error as exc:
        raise APIError(422, "INVALID_DATA", "CSV 구문이 올바르지 않습니다.") from exc
    if len(rows) < 41:
        raise APIError(422, "INSUFFICIENT_HISTORY", "최소 41일의 연속 일자료가 필요합니다.")
    return rows
