"""로컬 또는 MLflow 모델 로딩·캐시·예측. 응답에 실제 Registry 버전을 제공합니다."""
import os
import time

from data.features import HAICScaler

LOCAL_MODEL_PATH = "serving_app/models/haic_v1.keras"
SCALER_PATH = "serving_app/models/scaler.pkl"
MLFLOW_MODEL_URI = "models:/HAIC_Predictor/Production"

_model_cache = None

class LoadedModel:

    def __init__(self, keras_model, scaler: HAICScaler, version: str):
        self._keras_model = keras_model
        self.scaler = scaler
        self.version = version

    def predict_one(self, sequence: list[dict]) -> float:

        import numpy as np

        scaled = [self.scaler.transform_point(p["close"], p["volume"]) for p in sequence]

        x = np.array([scaled], dtype="float32")

        pred_scaled = float(self._keras_model.predict(x, verbose=0)[0][0])

        return self.scaler.inverse_close(pred_scaled)

def _load_from_local() -> LoadedModel:

    from tensorflow import keras

    keras_model = keras.models.load_model(LOCAL_MODEL_PATH)
    scaler = HAICScaler.load(SCALER_PATH)
    return LoadedModel(keras_model=keras_model, scaler=scaler, version="v1-local")

def _load_from_mlflow() -> LoadedModel:

    import mlflow.tensorflow

    from mlflow.tracking import MlflowClient

    versions = MlflowClient().get_latest_versions("HAIC_Predictor", stages=["Production"])
    if not versions:
        raise RuntimeError("Production 모델이 없습니다. 초기 학습 로그를 확인하세요.")
    version = versions[0].version
    keras_model = mlflow.tensorflow.load_model(f"models:/HAIC_Predictor/{version}")

    scaler = HAICScaler.load(SCALER_PATH)
    return LoadedModel(keras_model=keras_model, scaler=scaler, version=str(version))

def _load_model() -> LoadedModel:

    source = os.getenv("MODEL_SOURCE", "local")
    if source == "mlflow":
        return _load_from_mlflow()
    return _load_from_local()

def load_eager() -> LoadedModel:

    start = time.time()
    model = _load_model()
    print(f"[eager] model loaded in {time.time() - start:.3f}s at startup")
    global _model_cache
    _model_cache = model
    return model

def get_model() -> LoadedModel:

    global _model_cache

    if _model_cache is None:
        start = time.time()
        _model_cache = _load_model()
        print(f"[lazy] model loaded in {time.time() - start:.3f}s on first request")
    return _model_cache
