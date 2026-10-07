"""AI 파드가 제공할 도메인 모델의 연결 경계. HAIC 값을 깊이로 치환하지 않습니다."""
from dataclasses import asdict, dataclass
from typing import Protocol, Callable

from .core import APIError, FEATURE_CONTRACT


@dataclass(frozen=True)
class ModelInfo:
    id: str
    well_id: str
    registry_name: str
    registry_version: str
    feature_contract: str
    training_end_date: str | None = None
    evaluation_end_date: str | None = None

    def public(self):
        return {key: asdict(self)[key] for key in ("id", "registry_name", "registry_version", "feature_contract")}


@dataclass(frozen=True)
class TrainingResult:
    candidate: ModelInfo | None
    gate_rmse_cm: float
    gate_passed: bool
    promoted: bool
    training_start_date: str
    training_end_date: str
    gate_start_date: str
    gate_end_date: str


class ModelGateway(Protocol):
    def active_model(self, well_id: str) -> ModelInfo: ...
    def predict(self, model: ModelInfo, sequence: list[dict]) -> float: ...
    def retrain(self, model: ModelInfo, rows: list[dict], policy: dict,
                emit: Callable[[str, str, str], None]) -> TrainingResult: ...


class ExistingModelGateway:
    """기존 로더를 재사용하되 명시적 도메인 모델 계약이 있을 때만 추론합니다.

    현재 LoadedModel은 주가 샘플이므로 계약 검증에서 거절됩니다.
    AI 파드의 합의된 연동 구현은 ModelGateway를 서비스에 주입할 수 있습니다.
    """
    def _loaded(self):
        from serving_app import model_loader
        try:
            return model_loader.get_model()
        except Exception as exc:
            raise APIError(503, "MODEL_NOT_READY", "모델을 준비하지 못했습니다.") from exc

    def active_model(self, well_id):
        loaded = self._loaded()
        info = getattr(loaded, "groundwatch_metadata", None)
        if not isinstance(info, ModelInfo) or info.feature_contract != FEATURE_CONTRACT:
            raise APIError(422, "CONTRACT_MISMATCH", "현재 HAIC 모델은 지하수·강수량 계약을 지원하지 않습니다.")
        if info.well_id != well_id or not callable(getattr(loaded, "predict_depth", None)):
            raise APIError(422, "CONTRACT_MISMATCH", "관측정 또는 모델 인터페이스가 일치하지 않습니다.")
        return info

    def predict(self, model, sequence):
        loaded = self._loaded()
        if getattr(loaded, "groundwatch_metadata", None) != model:
            raise APIError(409, "MODEL_CHANGED", "서빙 모델이 변경되어 예측을 중단했습니다.")
        return loaded.predict_depth(sequence)

    def retrain(self, model, rows, policy, emit):
        raise APIError(503, "RETRAIN_NOT_READY", "데이터·AI 파드의 지하수 재학습 연동이 아직 준비되지 않았습니다.")
