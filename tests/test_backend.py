"""웹 백엔드 계약 검증. StubGateway는 테스트 전용이며 제품 모델이 아닙니다."""
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request

import uvicorn

from serving_app.backend.adapter import ExistingModelGateway, ModelInfo, TrainingResult
from serving_app.backend.api import create_backend_app
from serving_app.backend.core import APIError, FEATURE_CONTRACT, Settings, WELL_ID, parse_csv
from serving_app.backend.database import Database
from serving_app.backend.service import BackendService


def csv_data(count=80, offset=0):
    rows = ["observed_date,groundwater_depth_cm,rainfall_mm"]
    for i in range(count):
        rows.append(f"{date(2025, 1, 1) + timedelta(days=i)},{100 + i / 10 + offset:.1f},{i % 3 / 10:.1f}")
    return ("\n".join(rows) + "\n").encode()


class StubGateway:
    def __init__(self, error=0, gate=1, fail_training=False):
        self.info = ModelInfo(str(uuid4()), WELL_ID, "TEST_ONLY", "1", FEATURE_CONTRACT, "2024-11-30", "2024-12-31")
        self.error, self.gate, self.fail_training = error, gate, fail_training
        self.training_rows = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.predict_calls = 0

    def active_model(self, well_id):
        return self.info

    def predict(self, model, sequence):
        self.predict_calls += 1
        if self.block:
            self.entered.set()
            if not self.release.wait(5):
                raise RuntimeError("test timeout")
        return sequence[-1]["groundwater_depth_cm"] + 0.1 - self.error

    def retrain(self, model, rows, policy, emit):
        self.training_rows = rows
        if self.fail_training:
            raise RuntimeError("deliberate test failure")
        passed = self.gate <= policy["gate_threshold_cm"]
        candidate = replace(self.info, id=str(uuid4()), registry_version="2",
                            training_end_date=rows[35]["observed_date"], evaluation_end_date=rows[40]["observed_date"])
        emit("train", "succeeded", "테스트용 학습 연결 검증")
        emit("gate", "succeeded" if passed else "failed", "테스트용 Gate 결과")
        if passed:
            self.info = candidate
        return TrainingResult(candidate, self.gate, passed, passed, rows[20]["observed_date"],
                              rows[35]["observed_date"], rows[36]["observed_date"], rows[40]["observed_date"])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.gateway = StubGateway()
        self.settings = Settings(db_path=Path(self.tmp.name) / "groundwatch.db")
        self.service = BackendService(self.settings, self.gateway)
        self.service.start()

    def tearDown(self):
        self.gateway.release.set()
        self.service.close()
        self.tmp.cleanup()

    def upload(self, count=80, offset=0, parent=None):
        return self.service.upload(WELL_ID, csv_data(count, offset), "test.csv", "simulated", "baseline", parent)[0]

    def finish(self, run_id):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            run = self.service.run(run_id)
            if run["status"] not in ("queued", "running"):
                return run
            time.sleep(0.01)
        self.fail("background run did not finish")

    def analyse(self, dataset, start="2025-01-21", end="2025-03-01"):
        run = self.service.analyse(WELL_ID, dataset["id"], start, end, str(uuid4()))
        return self.finish(run["id"])

    def test_upload_atomic_dedup_and_append_only(self):
        first = self.upload(41)
        again, created = self.service.upload(WELL_ID, csv_data(41), "renamed.csv", "simulated", "baseline", None)
        self.assertFalse(created)
        self.assertEqual(first["id"], again["id"])
        child = self.upload(42, parent=first["id"])
        self.assertEqual(child["parent_dataset_id"], first["id"])
        with self.assertRaises(APIError) as err:
            self.upload(43, offset=1, parent=child["id"])
        self.assertEqual(err.exception.status, 422)
        with self.assertRaises(APIError):
            self.service.upload(WELL_ID, csv_data(40), "bad.csv", "simulated", "baseline", None)
        self.assertEqual(len(self.service.datasets(WELL_ID)), 2)
        with self.service.db.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM observation").fetchone()[0], 83)
            self.assertEqual(bytes(db.execute("SELECT raw_csv FROM dataset WHERE id=?", (first["id"],)).fetchone()[0]), csv_data(41))

    def test_csv_rejects_gaps_duplicates_nan_negative_underflow_and_precision(self):
        original = csv_data(41)
        bad_values = [
            original.replace(b"2025-01-02", b"2025-01-01"),
            original.replace(b"2025-01-02", b"2025-01-03"),
            original.replace(b"100.0,0.0", b"NaN,0.0"),
            original.replace(b"100.0,0.0", b"100.0,-0.1"),
            original.replace(b"100.0,0.0", b"100.0,0.01"),
            original.replace(b"100.0,0.0", b"1e-999,0.0"),
            original.replace(b"100.0,0.0", b",0.0"),
        ]
        for raw in bad_values:
            with self.subTest(raw=raw[:100]), self.assertRaises(APIError):
                parse_csv(raw)
        self.assertEqual(parse_csv(original)[0]["rainfall_mm"], 0)

    def test_forecast_idempotency_and_actual_arrives_on_extension(self):
        first = self.upload(41)
        key = str(uuid4())
        forecast, created = self.service.predict(WELL_ID, first["id"], first["end_date"], key)
        self.assertTrue(created)
        self.assertEqual(forecast["target_date"], "2025-02-11")
        self.assertIsNone(forecast["actual_depth_cm"])
        again, created = self.service.predict(WELL_ID, first["id"], first["end_date"], key)
        self.assertFalse(created)
        self.assertEqual(forecast["id"], again["id"])
        self.assertEqual(self.gateway.predict_calls, 1)
        with self.assertRaises(APIError) as err:
            self.service.predict(WELL_ID, first["id"], "2025-02-09", key)
        self.assertEqual(err.exception.code, "IDEMPOTENCY_CONFLICT")
        child = self.upload(42, parent=first["id"])
        values = self.service.forecasts(WELL_ID, child["id"], "live")
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["dataset_id"], first["id"])
        self.assertAlmostEqual(values[0]["actual_depth_cm"], 104.1)
        run = self.finish(self.service.runs(WELL_ID, child["id"])[0]["id"])
        self.assertEqual(run["status"], "succeeded")
        check = self.service.check(run["result"]["last_check_id"])
        self.assertEqual(check["state"], "insufficient_data")
        self.assertEqual(check["sample_count"], 1)
        self.assertIsNone(check["rmse_cm"])

    def test_unconfigured_threshold_is_not_evaluated(self):
        d = self.upload()
        run = self.analyse(d)
        self.assertEqual(run["status"], "succeeded")
        check = self.service.check(run["result"]["last_check_id"])
        self.assertEqual(check["state"], "not_evaluated")
        self.assertEqual(check["sample_count"], 21)
        self.assertAlmostEqual(check["rmse_cm"], 0)
        self.assertIsNone(run["result"]["child_run_id"])
        with self.service.db.connect() as db:
            early = dict(db.execute("SELECT * FROM monitoring_check WHERE sample_count=20").fetchone())
            self.assertEqual(early["state"], "insufficient_data")
            self.assertIsNone(early["rmse_cm"])

    def test_drift_stops_at_21_and_retrain_uses_same_dataset_41_rows(self):
        self.service.settings = replace(self.settings, rmse_threshold_cm=5, gate_threshold_cm=3, auto_retrain=True, policy_version="test-policy")
        self.gateway.error = 10
        d = self.upload()
        unrelated = self.upload(90, offset=50)
        parent = self.analyse(d)
        self.assertEqual(parent["status"], "succeeded")
        self.assertEqual(parent["result"]["prediction_count"], 21)
        self.assertEqual(parent["result"]["processed_through_date"], "2025-02-10")
        child = self.finish(parent["result"]["child_run_id"])
        self.assertEqual(child["status"], "succeeded")
        self.assertTrue(child["result"]["promoted"])
        self.assertEqual(len(self.gateway.training_rows), 41)
        self.assertAlmostEqual(self.gateway.training_rows[0]["groundwater_depth_cm"], 100)
        self.assertNotEqual(child["dataset_id"], unrelated["id"])
        self.assertEqual(child["result"]["training_end_date"], "2025-02-05")
        self.assertEqual(child["result"]["gate_start_date"], "2025-02-06")
        self.assertEqual(child["output_model_version_id"], self.gateway.info.id)
        self.assertEqual(self.service.check(parent["result"]["last_check_id"])["state"], "drift")

    def test_failed_gate_retains_model_and_is_not_training_failure(self):
        self.service.settings = replace(self.settings, rmse_threshold_cm=5, gate_threshold_cm=3, auto_retrain=True, policy_version="test-policy")
        self.gateway.error, self.gateway.gate = 10, 6
        before = self.gateway.info
        run = self.analyse(self.upload())
        child = self.finish(run["result"]["child_run_id"])
        self.assertEqual(child["status"], "succeeded")
        self.assertFalse(child["result"]["promoted"])
        self.assertEqual(before, self.gateway.info)

    def test_training_failure_records_failed_child_and_keeps_parent(self):
        self.service.settings = replace(self.settings, rmse_threshold_cm=5, gate_threshold_cm=3, auto_retrain=True, policy_version="test-policy")
        self.gateway.error, self.gateway.fail_training = 10, True
        before = self.gateway.info
        run = self.analyse(self.upload())
        child = self.finish(run["result"]["child_run_id"])
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(child["status"], "failed")
        self.assertEqual(before, self.gateway.info)
        self.assertEqual(child["error"]["code"], "INTERNAL_ERROR")

    def test_training_cutoff_and_model_mismatch_reject_predictions(self):
        d = self.upload()
        self.gateway.info = replace(self.gateway.info, evaluation_end_date="2025-02-01")
        with self.assertRaises(APIError) as err:
            self.analyse(d)
        self.assertEqual(err.exception.code, "INVALID_DATA")
        self.gateway.info = replace(self.gateway.info, feature_contract="haic-prices")
        with self.assertRaises(APIError) as err:
            self.service.predict(WELL_ID, d["id"], d["end_date"], str(uuid4()))
        self.assertEqual(err.exception.code, "CONTRACT_MISMATCH")
        self.assertEqual(self.service.forecasts(WELL_ID, d["id"], "live"), [])

    def test_analysis_idempotency_and_concurrent_mutation_conflict(self):
        d = self.upload()
        self.gateway.block = True
        key = str(uuid4())
        run = self.service.analyse(WELL_ID, d["id"], "2025-01-21", "2025-02-10", key)
        self.assertTrue(self.gateway.entered.wait(2))
        again = self.service.analyse(WELL_ID, d["id"], "2025-01-21", "2025-02-10", key)
        self.assertEqual(run["id"], again["id"])
        for operation in [lambda: self.service.analyse(WELL_ID, d["id"], "2025-01-21", "2025-02-10", str(uuid4())),
                          lambda: self.service.predict(WELL_ID, d["id"], d["end_date"], str(uuid4())),
                          lambda: self.upload(81)]:
            with self.assertRaises(APIError) as err:
                operation()
            self.assertEqual(err.exception.code, "RUN_IN_PROGRESS")
        self.gateway.release.set()
        self.assertEqual(self.finish(run["id"])["status"], "succeeded")
        self.assertEqual(len(self.service.runs(WELL_ID, d["id"])), 1)

    def test_restart_preserves_data_and_marks_unfinished_run(self):
        d = self.upload()
        with patch.object(self.service, "_submit"):
            run = self.service.analyse(WELL_ID, d["id"], "2025-01-21", "2025-02-10", str(uuid4()))
        self.service.close()
        self.service = BackendService(self.settings, self.gateway)
        self.service.start()
        self.assertEqual(self.service.dataset(d["id"])["row_count"], 80)
        recovered = self.service.run(run["id"])
        self.assertEqual(recovered["status"], "interrupted")
        self.assertEqual(recovered["error"]["code"], "PROCESS_INTERRUPTED")

    def test_live_window_collects_21_without_mixing_model_versions(self):
        self.service.settings = replace(self.settings, rmse_threshold_cm=5, policy_version="test-policy")
        current = self.upload(41)
        for count in range(42, 63):
            self.service.predict(WELL_ID, current["id"], current["end_date"], str(uuid4()))
            current = self.upload(count, parent=current["id"])
            run = self.finish(self.service.runs(WELL_ID, current["id"])[0]["id"])
            self.assertEqual(run["status"], "succeeded")
        check = self.service.check(run["result"]["last_check_id"])
        self.assertEqual(check["sample_count"], 21)
        self.assertEqual(check["state"], "within_threshold")
        self.gateway.info = replace(self.gateway.info, id=str(uuid4()), registry_version="2")
        self.service.predict(WELL_ID, current["id"], current["end_date"], str(uuid4()))
        current = self.upload(63, parent=current["id"])
        run = self.finish(self.service.runs(WELL_ID, current["id"])[0]["id"])
        check = self.service.check(run["result"]["last_check_id"])
        self.assertEqual(check["sample_count"], 1)
        self.assertEqual(check["state"], "insufficient_data")

    def test_first_live_actual_after_model_gate_cutoff_is_evaluated(self):
        parent = self.upload(41)
        self.gateway.info = replace(self.gateway.info, training_end_date="2025-02-05", evaluation_end_date=parent["end_date"])
        self.service.predict(WELL_ID, parent["id"], parent["end_date"], str(uuid4()))
        child = self.upload(42, parent=parent["id"])
        run = self.finish(self.service.runs(WELL_ID, child["id"])[0]["id"])
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["from_date"], "2025-02-11")
        self.assertEqual(self.service.check(run["result"]["last_check_id"])["sample_count"], 1)

    def test_lineage_does_not_fork_actual_observations(self):
        parent = self.upload(41)
        child = self.upload(42, parent=parent["id"])
        with self.assertRaises(APIError) as err:
            self.upload(43, parent=parent["id"])
        self.assertEqual(err.exception.code, "LINEAGE_CONFLICT")
        self.assertEqual(self.upload(43, parent=child["id"])["row_count"], 43)

    def test_invalid_prediction_does_not_create_forecast_and_releases_busy_state(self):
        dataset = self.upload()
        key = str(uuid4())
        with patch.object(self.gateway, "predict", return_value=float("nan")):
            with self.assertRaises(APIError) as err:
                self.service.predict(WELL_ID, dataset["id"], dataset["end_date"], key)
        self.assertEqual(err.exception.code, "INVALID_MODEL_OUTPUT")
        self.assertEqual(self.service.forecasts(WELL_ID, dataset["id"], "live"), [])
        _, created = self.service.predict(WELL_ID, dataset["id"], dataset["end_date"], key)
        self.assertTrue(created)

    def test_upload_size_limit_and_source_kind_validation(self):
        self.service.settings = replace(self.settings, max_upload_bytes=8)
        with self.assertRaises(APIError) as err:
            self.upload()
        self.assertEqual(err.exception.status, 413)
        self.service.settings = self.settings
        with self.assertRaises(APIError) as err:
            self.service.upload(WELL_ID, csv_data(), "test.csv", "measured", "baseline", None)
        self.assertEqual(err.exception.status, 422)
        self.assertEqual(self.service.datasets(WELL_ID), [])

    def test_one_process_per_database(self):
        other = Database(self.settings.db_path)
        with self.assertRaises(RuntimeError):
            other.start()

    def test_existing_haic_model_is_never_exposed_as_groundwater(self):
        with patch("serving_app.model_loader.get_model", return_value=object()):
            with self.assertRaises(APIError) as err:
                ExistingModelGateway().active_model(WELL_ID)
        self.assertEqual(err.exception.code, "CONTRACT_MISMATCH")


class HTTPTests(unittest.TestCase):
    """실제 loopback HTTP: TestClient/httpx 추가 의존성 없이 계약을 확인합니다."""
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.service = BackendService(Settings(db_path=Path(self.tmp.name) / "api.db"), StubGateway())
        app = create_backend_app(self.service)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, ws="none"))
        self.thread = threading.Thread(target=lambda: self.server.run(sockets=[self.sock]), daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 5
        while not self.server.started and self.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.server.started)

    def tearDown(self):
        self.server.should_exit = True
        self.thread.join(5)
        self.sock.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}" + path, data=body, method=method, headers=headers or {})
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            return response.status, dict(response.headers), json.loads(raw)

    def upload(self, raw=None):
        boundary = "test-" + str(uuid4())
        raw = raw or csv_data()
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="source_kind"\r\n\r\nsimulated\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="scenario"\r\n\r\nbaseline\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.csv"\r\nContent-Type: text/csv\r\n\r\n').encode()
        body += raw + f'\r\n--{boundary}--\r\n'.encode()
        return self.request("POST", f"/wells/{WELL_ID}/datasets", body, {"Content-Type": "multipart/form-data; boundary=" + boundary})

    def test_http_upload_observations_dashboard_and_openapi(self):
        status, _, result = self.upload()
        self.assertEqual(status, 201, result)
        d = result["data"]
        self.assertNotIn("raw_csv", d)
        status, _, page1 = self.request("GET", f"/wells/{WELL_ID}/observations?dataset_id={d['id']}&limit=7")
        self.assertEqual(status, 200)
        self.assertEqual(len(page1["data"]), 7)
        cursor = page1["meta"]["next_cursor"]
        status, _, page2 = self.request("GET", f"/wells/{WELL_ID}/observations?dataset_id={d['id']}&limit=7&cursor={cursor}")
        self.assertEqual(status, 200)
        self.assertGreater(page2["data"][0]["observed_date"], page1["data"][-1]["observed_date"])
        status, _, bad = self.request("GET", f"/wells/{WELL_ID}/observations?dataset_id={d['id']}&from=2025-02-01&cursor={cursor}")
        self.assertEqual(status, 422)
        self.assertEqual(bad["error"]["code"], "INVALID_DATA")
        status, _, dash = self.request("GET", f"/wells/{WELL_ID}/dashboard?dataset_id={d['id']}")
        self.assertEqual(status, 200)
        self.assertIsNone(dash["data"]["latest_forecast"])
        self.assertEqual(dash["data"]["data_freshness"]["state"], "unknown")
        status, _, spec = self.request("GET", "/openapi.json")
        self.assertEqual(status, 200)
        self.assertIn("/wells/{well_id}/analyses", spec["paths"])
        self.assertIn("Forecast", spec["components"]["schemas"])

    def test_http_error_envelopes_and_idempotent_forecast(self):
        _, _, data = self.upload()
        d = data["data"]
        headers = {"Content-Type": "application/json", "Idempotency-Key": str(uuid4())}
        body = json.dumps({"dataset_id": d["id"], "input_end_date": d["end_date"]}).encode()
        status, _, first = self.request("POST", f"/wells/{WELL_ID}/forecasts", body, headers)
        self.assertEqual(status, 201, first)
        status, _, again = self.request("POST", f"/wells/{WELL_ID}/forecasts", body, headers)
        self.assertEqual(status, 200)
        self.assertEqual(first["data"]["id"], again["data"]["id"])
        cases = [
            ("GET", "/wells?unknown=true", None, {}, 422),
            ("GET", "/wells?limit=0", None, {}, 422),
            ("GET", "/wells?limit=5&limit=6", None, {}, 422),
            ("GET", "/wells?cursor=%%", None, {}, 422),
            ("GET", "/datasets/invalid-uuid", None, {}, 422),
            ("GET", "/datasets/" + str(uuid4()), None, {}, 404),
            ("POST", f"/wells/{WELL_ID}/forecasts", b'{bad', headers, 400),
            ("POST", f"/wells/{WELL_ID}/forecasts", body, {"Content-Type": "application/json"}, 422),
        ]
        for method, path, payload, heads, expected in cases:
            with self.subTest(path=path):
                status, response_headers, error = self.request(method, path, payload, heads)
                self.assertEqual(status, expected, error)
                self.assertIn("error", error)
                self.assertTrue(error["meta"]["request_id"])
                self.assertIn("x-request-id", {k.lower() for k in response_headers})

    def test_http_async_analysis_and_history(self):
        _, _, data = self.upload()
        body = json.dumps({"dataset_id": data["data"]["id"], "from": "2025-01-21", "to": "2025-02-10", "mode": "replay"}).encode()
        status, headers, result = self.request("POST", f"/wells/{WELL_ID}/analyses", body,
                                              {"Content-Type": "application/json", "Idempotency-Key": str(uuid4())})
        self.assertEqual(status, 202, result)
        run_id = result["data"]["id"]
        self.assertEqual(headers["location"], "/api/v1/runs/" + run_id)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, _, result = self.request("GET", "/runs/" + run_id)
            if result["data"]["status"] not in ("queued", "running"):
                break
            time.sleep(0.01)
        self.assertEqual(result["data"]["status"], "succeeded", result)
        check_id = result["data"]["result"]["last_check_id"]
        status, _, check = self.request("GET", "/checks/" + check_id)
        self.assertEqual(status, 200)
        self.assertEqual(check["data"]["sample_count"], 21)
        status, _, events = self.request("GET", "/runs/" + run_id + "/events")
        self.assertEqual(status, 200)
        self.assertEqual([e["sequence"] for e in events["data"]], list(range(1, len(events["data"]) + 1)))


if __name__ == "__main__":
    unittest.main()
