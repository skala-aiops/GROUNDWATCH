"""샘플 모델 학습·MLflow 기록·평가 게이트·Production 등록."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mlflow
import mlflow.tensorflow
import numpy as np
from mlflow.tracking import MlflowClient
from tensorflow import keras

from data.features import load_rows, build_sequences, train_test_split, HAICScaler
from data.storage import latest_upload
from serving_app.lstm_model import build_model

SEED = 42
keras.utils.set_random_seed(SEED)

RMSE_GATE = 4.00
MODEL_NAME = "HAIC_Predictor"
SCALER_PATH = "serving_app/models/scaler.pkl"
BASE_EPOCHS = 100
FINE_TUNE_EPOCHS = 10
FINE_TUNE_LR = 1e-4

def rmse(y_true, y_pred) -> float:
    return float(np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2)))

def _prepare(rows: list[dict], scaler: HAICScaler):
    X, y = build_sequences(rows, scaler)
    X_train, y_train, X_test, y_test = train_test_split(X, y)
    X_train = np.array(X_train, dtype="float32")
    X_test = np.array(X_test, dtype="float32")
    y_train_scaled = np.array([scaler.scale_close(v) for v in y_train], dtype="float32")
    return X_train, y_train_scaled, X_test, y_test

def _register_if_gate_passed(model, run_id: str, score: float) -> dict:
    result = {"run_id": run_id, "rmse": score, "promoted": False}
    if score <= RMSE_GATE:
        v = mlflow.register_model(model.model_uri, MODEL_NAME)
        MlflowClient().transition_model_version_stage(name=MODEL_NAME, version=v.version, stage="Production", archive_existing_versions=True)
        result["promoted"] = True
        result["version"] = v.version
        print(f"[GATE PASSED] rmse={score:.2f} -> {MODEL_NAME} v{v.version} promoted to Production")
    else:
        print(f"[GATE FAILED] rmse={score:.2f} > {RMSE_GATE} -> 배포 차단, 기존 Production 유지")
    return result

def train_and_register(csv_path: str | None = None, rows: list[dict] | None = None) -> dict:

    if rows is None:
        rows = load_rows(csv_path or latest_upload())
    scaler = HAICScaler.load(SCALER_PATH)
    X_train, y_train_scaled, X_test, y_test = _prepare(rows, scaler)

    with mlflow.start_run(run_name="base-train"):
        model = build_model()
        model.fit(X_train, y_train_scaled, epochs=BASE_EPOCHS, verbose=0)

        preds = [scaler.inverse_close(p) for p in model.predict(X_test, verbose=0).flatten()]
        score = rmse(y_test, preds)

        mlflow.log_param("mode", "scratch")
        mlflow.log_param("epochs", BASE_EPOCHS)
        mlflow.log_metric("rmse", score)
        logged_model = mlflow.tensorflow.log_model(model, name="model", input_example=X_train[:1])

        return _register_if_gate_passed(logged_model, mlflow.active_run().info.run_id, score)

def fine_tune(rows: list[dict]) -> dict:

    scaler = HAICScaler.load(SCALER_PATH)
    X_train, y_train_scaled, X_test, y_test = _prepare(rows, scaler)

    model = mlflow.tensorflow.load_model(f"models:/{MODEL_NAME}/Production")
    model.compile(optimizer=keras.optimizers.Adam(learning_rate=FINE_TUNE_LR), loss="mse")

    with mlflow.start_run(run_name="fine-tune"):
        model.fit(X_train, y_train_scaled, epochs=FINE_TUNE_EPOCHS, verbose=0)

        preds = [scaler.inverse_close(p) for p in model.predict(X_test, verbose=0).flatten()]
        score = rmse(y_test, preds)

        mlflow.log_param("mode", "fine-tune")
        mlflow.log_param("epochs", FINE_TUNE_EPOCHS)
        mlflow.log_param("n_rows", len(rows))
        mlflow.log_metric("rmse", score)
        logged_model = mlflow.tensorflow.log_model(model, name="model", input_example=X_train[:1])

        return _register_if_gate_passed(logged_model, mlflow.active_run().info.run_id, score)

if __name__ == "__main__":
    train_and_register()
