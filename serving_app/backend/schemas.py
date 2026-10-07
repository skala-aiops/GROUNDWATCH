"""신규 웹 API의 요청·응답 타입. 기존 serving_app/schemas.py는 변경하지 않습니다."""
from datetime import date, datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["live", "replay"]
Kind = Literal["analysis", "retrain"]
T = TypeVar("T")


class Meta(BaseModel):
    request_id: str
    next_cursor: str | None = None


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    error: ErrorBody
    meta: Meta


class Well(BaseModel):
    id: UUID
    code: str
    name: str
    depth_reference: str
    timezone: str


class Dataset(BaseModel):
    id: UUID
    well_id: UUID
    parent_dataset_id: UUID | None
    original_name: str
    checksum: str
    source_kind: Literal["simulated", "measured"]
    scenario: Literal["baseline", "drift"] | None
    schema_version: str
    row_count: int
    start_date: date
    end_date: date
    uploaded_at: datetime


class Observation(BaseModel):
    id: UUID
    observed_date: date
    groundwater_depth_cm: float
    rainfall_mm: float


class ModelSummary(BaseModel):
    id: UUID
    registry_name: str
    registry_version: str
    feature_contract: str


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: UUID
    input_end_date: date


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: UUID
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    mode: Literal["replay"]


class Forecast(BaseModel):
    id: UUID
    dataset_id: UUID
    model: ModelSummary
    input_start_date: date
    input_end_date: date
    target_date: date
    predicted_depth_cm: float
    actual_observation_id: UUID | None
    actual_depth_cm: float | None
    residual_cm: float | None
    mode: Mode
    created_at: datetime


class CheckMember(BaseModel):
    forecast_id: UUID
    actual_observation_id: UUID
    residual_cm: float
    position: int


class Check(BaseModel):
    id: UUID
    dataset_id: UUID
    model_version_id: UUID
    run_id: UUID
    mode: Mode
    as_of_date: date
    sample_count: int
    rmse_cm: float | None
    threshold_cm: float | None
    state: Literal["within_threshold", "drift", "insufficient_data", "not_evaluated", "data_invalid"]
    policy_snapshot: dict
    members: list[CheckMember]
    created_at: datetime


class Run(BaseModel):
    id: UUID
    dataset_id: UUID
    kind: Kind
    mode: Mode
    status: Literal["queued", "running", "succeeded", "failed", "interrupted"]
    parent_run_id: UUID | None
    trigger_check_id: UUID | None
    input_model_version_id: UUID
    output_model_version_id: UUID | None
    from_date: date
    to_date: date
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: dict | None
    error: dict | None


class Event(BaseModel):
    id: UUID
    run_id: UUID
    sequence: int
    stage: str
    state: Literal["started", "succeeded", "failed", "skipped"]
    message: str
    occurred_at: datetime


class Freshness(BaseModel):
    state: Literal["fresh", "stale", "unknown"]
    last_observed_date: date | None
    stale_after_days: int | None


class Dashboard(BaseModel):
    well_id: UUID
    dataset_id: UUID
    source_kind: Literal["simulated", "measured"]
    as_of_date: date
    last_observation: Observation | None
    latest_forecast: Forecast | None
    last_check: Check | None
    data_freshness: Freshness
    active_model: ModelSummary | None
    latest_run_id: UUID | None
    updated_at: datetime
