"""최근 21개 오차의 RMSE로 샘플 변화 신호를 판단합니다. 임계값 4는 샘플용입니다."""
RMSE_THRESHOLD = 4.00
WINDOW_SIZE = 21

def compute_rmse(recent_predictions: list[dict]) -> float:

    import math

    if not recent_predictions:
        return 0.0

    errors_sq = [(p["actual"] - p["predicted"]) ** 2 for p in recent_predictions]
    return math.sqrt(sum(errors_sq) / len(errors_sq))

def is_drift(recent_predictions: list[dict]) -> bool:

    if len(recent_predictions) < WINDOW_SIZE:
        return False
    window = recent_predictions[-WINDOW_SIZE:]
    rmse = compute_rmse(window)
    return rmse > RMSE_THRESHOLD
