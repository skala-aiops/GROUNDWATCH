"""빈칸 구현과 승격 실패/캐시 교체 회귀 검증. 컨테이너 안에서 unittest로 실행합니다."""
import unittest
from unittest.mock import Mock, patch

from data.features import HAICScaler
from serving_app import model_loader
from serving_app.monitoring.drift_detector import compute_rmse, is_drift
from serving_app.monitoring.retrain_trigger import check_and_trigger


class PipelineTests(unittest.TestCase):
    def tearDown(self):
        model_loader._model_cache = None

    def test_rmse_and_threshold(self):
        self.assertEqual(compute_rmse([]), 0)
        self.assertEqual(compute_rmse([{"predicted": 100, "actual": 102}, {"predicted": 100, "actual": 98}]), 2)
        self.assertFalse(is_drift([{"predicted": 0, "actual": 100}] * 20))
        self.assertFalse(is_drift([{"predicted": 0, "actual": 4}] * 21))
        self.assertTrue(is_drift([{"predicted": 0, "actual": 5}] * 21))
        self.assertFalse(is_drift([{"predicted": 0, "actual": 100}] + [{"predicted": 0, "actual": 0}] * 21))

    def test_predict_scaling_and_lazy_cache(self):
        scaler = HAICScaler().fit([{"Close": 100, "Volume": 0}, {"Close": 200, "Volume": 200}])
        keras_model = Mock()
        keras_model.predict.return_value = [[0.5]]
        loaded = model_loader.LoadedModel(keras_model, scaler, "1")
        self.assertEqual(loaded.predict_one([{"close": 150, "volume": 100}] * 20), 150)
        self.assertEqual(keras_model.predict.call_args.args[0].shape, (1, 20, 2))
        with patch.object(model_loader, "_load_model", return_value=loaded) as load:
            self.assertIs(model_loader.get_model(), loaded)
            self.assertIs(model_loader.get_model(), loaded)
            load.assert_called_once()

    def test_retrain_failure_preserves_serving_cache(self):
        current = object()
        model_loader._model_cache = current
        with patch("data.storage.latest_upload", return_value="sample.csv"), \
             patch("data.features.load_rows", return_value=[{}] * 60), \
             patch("serving_app.train_and_register.fine_tune", side_effect=RuntimeError("training failed")):
            result = check_and_trigger([{"predicted": 0, "actual": 5}] * 21)
        self.assertEqual(result["status"], "retrain_failed")
        self.assertIs(model_loader._model_cache, current)

    def test_failed_gate_does_not_reload(self):
        with patch("data.storage.latest_upload", return_value="sample.csv"), \
             patch("data.features.load_rows", return_value=[{}] * 60), \
             patch("serving_app.train_and_register.fine_tune", return_value={"promoted": False, "rmse": 5}) as train, \
             patch.object(model_loader, "load_eager") as reload:
            result = check_and_trigger([{"predicted": 0, "actual": 5}] * 21)
        self.assertFalse(result["promoted"])
        self.assertEqual(len(train.call_args.kwargs["rows"]), 41)
        reload.assert_not_called()

    def test_successful_gate_reloads(self):
        with patch("data.storage.latest_upload", return_value="sample.csv"), \
             patch("data.features.load_rows", return_value=[{}] * 60), \
             patch("serving_app.train_and_register.fine_tune", return_value={"promoted": True, "rmse": 2, "version": "2"}), \
             patch.object(model_loader, "load_eager") as reload:
            result = check_and_trigger([{"predicted": 0, "actual": 5}] * 21)
        self.assertTrue(result["promoted"])
        reload.assert_called_once()


if __name__ == "__main__":
    unittest.main()
