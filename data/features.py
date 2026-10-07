"""샘플 시계열 전처리·스케일러·시간 순서 분리 공용 함수."""
import csv
import pickle

SEQ_LEN = 20

def load_rows(csv_path: str = "data/haic_prices.csv") -> list[dict]:
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [
            {
                "Date": r["Date"],
                "Close": float(r["Close"]),
                "Volume": float(r["Volume"]),
            }
            for r in reader
        ]
    return rows

class HAICScaler:

    def __init__(self):
        self.close_min = self.close_max = None
        self.volume_min = self.volume_max = None

    def fit(self, rows: list[dict]) -> "HAICScaler":
        closes = [r["Close"] for r in rows]
        volumes = [r["Volume"] for r in rows]
        self.close_min, self.close_max = min(closes), max(closes)
        self.volume_min, self.volume_max = min(volumes), max(volumes)
        return self

    def _scale(self, value: float, lo: float, hi: float) -> float:
        if hi == lo:
            return 0.0
        return (value - lo) / (hi - lo)

    def _unscale(self, value: float, lo: float, hi: float) -> float:
        return value * (hi - lo) + lo

    def transform_point(self, close: float, volume: float) -> list[float]:
        return [
            self._scale(close, self.close_min, self.close_max),
            self._scale(volume, self.volume_min, self.volume_max),
        ]

    def scale_close(self, close: float) -> float:

        return self._scale(close, self.close_min, self.close_max)

    def inverse_close(self, scaled_close: float) -> float:

        return self._unscale(scaled_close, self.close_min, self.close_max)

    def save(self, path: str = "serving_app/models/scaler.pkl"):
        with open(path, "wb") as f:
            pickle.dump(self.__dict__, f)

    @classmethod
    def load(cls, path: str = "serving_app/models/scaler.pkl") -> "HAICScaler":
        scaler = cls()
        with open(path, "rb") as f:
            scaler.__dict__.update(pickle.load(f))
        return scaler

def build_sequences(rows: list[dict], scaler: HAICScaler, seq_len: int = SEQ_LEN):

    scaled_points = [scaler.transform_point(r["Close"], r["Volume"]) for r in rows]
    closes = [r["Close"] for r in rows]

    X, y = [], []
    for i in range(len(rows) - seq_len):
        X.append(scaled_points[i : i + seq_len])
        y.append(closes[i + seq_len])
    return X, y

def train_test_split(X: list, y: list, test_ratio: float = 0.2):

    split_idx = int(len(X) * (1 - test_ratio))
    return X[:split_idx], y[:split_idx], X[split_idx:], y[split_idx:]
