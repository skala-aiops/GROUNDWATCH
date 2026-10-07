"""샘플 예측·배치 API 입력과 응답 스키마."""
from typing import Annotated

from pydantic import BaseModel, Field

from data.features import SEQ_LEN

class DailyPoint(BaseModel):
    close: float = Field(..., gt=0, allow_inf_nan=False, description="해당 거래일 종가")
    volume: int = Field(..., ge=0, description="해당 거래일 거래량")

class PredictRequest(BaseModel):
    sequence: list[DailyPoint] = Field(
        ...,
        min_length=SEQ_LEN,
        max_length=SEQ_LEN,
        description=f"가장 오래된 날 -> 가장 최근 날 순서의 최근 {SEQ_LEN}거래일 시퀀스",
    )

class PredictResponse(BaseModel):
    predicted_close: float
    model_version: str

class BatchTestRequest(BaseModel):

    prices: list[Annotated[float, Field(gt=0, allow_inf_nan=False)]] = Field(
        ..., min_length=SEQ_LEN + 1, max_length=1000
    )

class BatchTestResponse(BaseModel):
    predictions: list[float]
    drift_check: dict
