"""최초 실행에서만 학습하고, 이후 저장된 Production 모델로 시작합니다."""
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from mlflow.exceptions import MlflowException
    from mlflow.tracking import MlflowClient

    for folder in ("runtime", "logs", "data/uploads", "serving_app/models"):
        Path(folder).mkdir(parents=True, exist_ok=True)
    if not list(Path("data/uploads").glob("*.csv")):
        shutil.copyfile("data/sample_haic_prices.csv", "data/uploads/build_seed.csv")
    client = MlflowClient()
    try:
        versions = client.get_latest_versions("HAIC_Predictor", stages=["Production"])
    except MlflowException as exc:
        if exc.error_code != "RESOURCE_DOES_NOT_EXIST":
            raise
        versions = []
    if not versions:
        from data.features import HAICScaler, SEQ_LEN, load_rows
        from data.storage import latest_upload
        from serving_app.train_and_register import train_and_register

        print("[init] 최초 학습·등록을 시작합니다. 완료까지 기다려 주세요.", flush=True)
        rows = load_rows(latest_upload())
        n_train = int((len(rows) - SEQ_LEN) * 0.8)
        HAICScaler().fit(rows[:n_train + SEQ_LEN]).save("serving_app/models/scaler.pkl")
        result = train_and_register()
        if not result["promoted"]:
            raise RuntimeError(f"초기 모델 게이트 미통과: {result}. 로그를 확인하세요.")
    else:
        print(f"[init] 저장된 Production v{versions[0].version}을 사용합니다.", flush=True)
    os.execvp("uvicorn", ["uvicorn", "serving_app.main:app", "--host", "0.0.0.0", "--port", "8099"])


if __name__ == "__main__":
    main()
