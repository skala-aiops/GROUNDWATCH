"""단일 시퀀스 예측과 배치 예측·변화 감지 API."""
from fastapi import APIRouter

from data.features import SEQ_LEN
from serving_app import model_loader
from serving_app.schemas import PredictRequest, PredictResponse, BatchTestRequest, BatchTestResponse
from serving_app.monitoring.retrain_trigger import check_and_trigger

router = APIRouter()

recent_predictions: list[dict] = []

SIMULATED_VOLUME = 1_200_000

@router.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):

    model = model_loader.get_model()
    sequence = [p.model_dump() for p in req.sequence]
    predicted_close = model.predict_one(sequence)
    return PredictResponse(predicted_close=round(predicted_close, 2), model_version=model.version)

@router.post("/predict/batch-test", response_model=BatchTestResponse)
def batch_test(req: BatchTestRequest):

    model = model_loader.get_model()
    predictions: list[float] = []

    prices = req.prices
    for i in range(len(prices) - SEQ_LEN):

        window = prices[i : i + SEQ_LEN]
        sequence = [{"close": p, "volume": SIMULATED_VOLUME} for p in window]
        pred = model.predict_one(sequence)
        actual = prices[i + SEQ_LEN]
        predictions.append(pred)
        recent_predictions.append({"predicted": pred, "actual": actual})

    recent_predictions[:] = recent_predictions[-21:]

    drift_check = check_and_trigger(recent_predictions)
    return BatchTestResponse(predictions=predictions, drift_check=drift_check)
