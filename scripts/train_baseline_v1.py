"""샘플 CSV로 로컬 baseline 모델과 스케일러를 생성합니다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.features import load_rows, build_sequences, train_test_split, HAICScaler
from data.storage import latest_upload
from serving_app.lstm_model import build_model

MODEL_PATH = "serving_app/models/haic_v1.keras"
SCALER_PATH = "serving_app/models/scaler.pkl"
BASE_EPOCHS = 100

def rmse(y_true, y_pred) -> float:

    return (sum((a - b) ** 2 for a, b in zip(y_true, y_pred)) / len(y_true)) ** 0.5

def main():
    import numpy as np

    rows = load_rows(latest_upload())

    scaler = HAICScaler().fit(rows)
    scaler.save(SCALER_PATH)
    print(f"scaler fit on {len(rows)}행 -> {SCALER_PATH}")

    X, y = build_sequences(rows, scaler)

    X_train, y_train, X_test, y_test = train_test_split(X, y)
    X_train = np.array(X_train, dtype="float32")
    X_test = np.array(X_test, dtype="float32")

    y_train_scaled = np.array([scaler.scale_close(v) for v in y_train], dtype="float32")

    model = build_model()

    model.fit(X_train, y_train_scaled, epochs=BASE_EPOCHS, verbose=0)

    preds_scaled = model.predict(X_test, verbose=0).flatten()
    preds = [scaler.inverse_close(p) for p in preds_scaled]
    score = rmse(y_test, preds)
    print(f"baseline v1 RMSE = {score:.2f}  (배포 게이트: $4.00)")

    model.save(MODEL_PATH)
    print(f"saved -> {MODEL_PATH}")
    if score > 4.00:
        print(
            "참고: 로컬 baseline 평가이며 Production 승격은 "
            "MLflow 등록 과정에서 별도로 검증합니다."
        )

if __name__ == "__main__":
    main()
