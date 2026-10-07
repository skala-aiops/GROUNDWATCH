"""입력 (20, 2), 출력 1개의 제공 LSTM 모델 구조."""
from tensorflow import keras

from data.features import SEQ_LEN

N_FEATURES = 2

def build_model() -> keras.Model:
    model = keras.Sequential(
        [
            keras.layers.Input(shape=(SEQ_LEN, N_FEATURES)),
            keras.layers.LSTM(32, return_sequences=True),
            keras.layers.LSTM(32, return_sequences=True),
            keras.layers.LSTM(16),
            keras.layers.Dense(16, activation="relu"),
            keras.layers.Dense(1),
        ]
    )
    model.compile(optimizer=keras.optimizers.Adam(learning_rate=1e-3), loss="mse")
    return model
