"""변화 감지 후 최신 업로드의 최근 41행으로 재학습하고 성공 시 서빙 캐시를 갱신합니다."""
import logging

from serving_app.monitoring.drift_detector import is_drift

logger = logging.getLogger("aiops")

def check_and_trigger(recent_predictions: list[dict]) -> dict:

    if not is_drift(recent_predictions):
        return {"status": "ok"}

    logger.warning("[WARN] drift detected - triggering retrain")

    from data.features import load_rows, SEQ_LEN
    from data.storage import latest_upload
    from serving_app.train_and_register import fine_tune

    logger.info("[INFO] retrain triggered (window=last_21_days)")

    rows = load_rows(latest_upload())[-(21 + SEQ_LEN):]

    try:
        result = fine_tune(rows=rows)
    except Exception:
        logger.exception("[ERROR] retraining failed - keeping current serving model")
        return {"status": "retrain_failed", "promoted": False}

    if result["promoted"]:
        from serving_app import model_loader

        model_loader.load_eager()
        logger.info(
            f"[OK] new_rmse={result['rmse']:.2f} - production promoted: HAIC_Predictor v{result['version']}"
        )
        return {"status": "retrain_triggered", "promoted": True, "rmse": result["rmse"]}
    return {"status": "retrain_triggered", "promoted": False, "rmse": result["rmse"]}
