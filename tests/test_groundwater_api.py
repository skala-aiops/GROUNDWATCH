"""HTTP contract checks, using deterministic models and explicitly labelled fixtures."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from serving_app.main import create_app
from serving_app.groundwater_models import ModelManager
from serving_app.groundwater_service import GroundwaterService
from tests.test_groundwater_models import Backend
from tests.test_groundwater_service import FakeManager, FIRST, START, upload_fixture


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.managers = {}
        factory = lambda namespace: self.managers.setdefault(namespace, FakeManager())
        self.service = GroundwaterService(self.directory.name, factory)
        self.client = TestClient(create_app(self.service))

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def upload_parts(self):
        dataset_id = upload_fixture(self.service)
        entry = self.service.store.get('dataset', dataset_id)
        return {'file': ('observations.csv', Path(entry['path']).read_bytes(), 'text/csv'),
                'manifest': ('manifest.json', Path(entry['manifest_path']).read_bytes(), 'application/json')}

    def test_live_routes_are_isolated_and_do_not_fallback_to_csv(self):
        response=self.client.get('/api/v1/live/forecasts?target_date=2026-10-07')
        self.assertEqual(response.status_code,200)
        body=response.json()
        self.assertEqual(body['ready_count'],0)
        self.assertEqual(body['input_end_date'],'2026-10-06')
        self.assertEqual(len(body['forecasts']),25)
        self.assertTrue(all(r['data_status']=='MAPPING_REQUIRED' for r in body['forecasts']))
        fresh=self.client.get('/api/v1/data-freshness').json()
        self.assertEqual(fresh['repository']['counts']['source_mappings'],25)
        self.assertEqual(self.client.get('/api/v1/live/districts/11110/history').json()['history'],[])
        self.assertEqual(self.client.post('/api/v1/live/prediction-jobs',json={'snapshot_id':'missing'}).status_code,404)
        self.assertEqual(self.client.get('/api/v1/live/forecasts?target_date=bad').status_code,422)

    def test_empty_service_200_with_25_null_predictions_and_no_observation_date(self):
        response = self.client.get('/api/v1/forecasts')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['ready_count'], 0)
        self.assertEqual(len(body['forecasts']), 25)
        self.assertTrue(all(row['prediction'] is None and row['observed_date'] is None for row in body['forecasts']))
        self.assertEqual(self.client.get('/health/live').status_code, 200)
        self.assertEqual(self.client.get('/health/ready').json()['status'], 'data_or_model_required')

    def test_invalid_date_district_and_extra_body_fields_422(self):
        self.assertEqual(self.client.get('/api/v1/forecasts?as_of=2020-02-31').status_code, 422)
        self.assertEqual(self.client.get('/api/v1/districts/99999/history').status_code, 422)
        self.assertEqual(self.client.post('/api/v1/jobs/train', json={'dataset_id':'x','district_code':'99999'}).status_code, 422)
        self.assertEqual(self.client.post('/api/v1/jobs/train', json={'dataset_id':'x','hidden_gate_override':True}).status_code, 422)

    def test_readiness_requires_models_and_continuous_inputs_and_recovers(self):
        dataset = upload_fixture(self.service)
        manager = self.service.manager(self.service.default_namespace())
        for district in self.service.districts(dataset)['districts']:
            code = district['district_code']
            manager.train(code, self.service.records(dataset, code), {}, 1)
        # A historical fixture is ready without pretending to contain today's data.
        self.assertEqual(self.client.get('/health/ready').status_code, 200)

        original = self.service.records
        rows = original(dataset, FIRST)
        for changed, reason in ((rows[:-2]+rows[-1:], 'input_date_gap'),
                                (rows[:-1], 'input_end_mismatch'),
                                (rows[-10:], 'input_insufficient')):
            self.service.records = lambda ds, code: changed if code == FIRST else original(ds, code)
            response = self.client.get('/health/ready')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()['forecast_ready_count'], 24)
            detail = next(x for x in response.json()['districts'] if x['district_code']==FIRST)
            self.assertEqual(detail['reason'], reason)
            self.assertEqual(self.client.get('/health/live').status_code, 200)
        self.service.records = original
        self.assertEqual(self.client.get('/health/ready').status_code, 200)
        model = manager.models.pop(FIRST)
        self.assertEqual(self.client.get('/health/ready').status_code, 503)
        manager.models[FIRST] = model
        self.assertEqual(self.client.get('/health/ready').status_code, 200)

    def test_forecast_provenance_preserves_station_boundaries_and_unknown_time(self):
        dataset = upload_fixture(self.service)
        original = self.service.records
        last = original(dataset, FIRST)[-1]['date']
        def mixed(ds, code, replay=None):
            rows = original(ds, code, replay)
            boundary = len(rows)-2 if code==FIRST else len(rows)-1
            return [{**r, 'origin':'synthetic' if i>=boundary else 'observed'} for i,r in enumerate(rows)]
        self.service.records = mixed
        response = self.client.get('/api/v1/forecasts').json()
        first, second = response['forecasts'][:2]
        self.assertNotEqual(first['data_source']['observed_through'],second['data_source']['observed_through'])
        self.assertEqual(first['data_source']['input_through'],last)
        self.assertTrue(first['data_source']['contains_synthetic'])
        self.assertEqual(first['data_source']['synthetic_through'],last)
        self.assertIsNone(first['data_source']['generated_at'])
        self.assertIsNotNone(first['data_source']['registered_at'])
        self.assertFalse(first['data_source']['external_api_applied'])

    def test_upload_schema_and_malformed_manifest_return_422(self):
        parts = self.upload_parts()
        bad_manifest = {'approved':True, 'mapping_version':'bad', 'stations':[1]}
        malformed = {**parts, 'manifest': ('bad.json', json.dumps(bad_manifest).encode(), 'application/json')}
        self.assertEqual(self.client.post('/api/v1/datasets', files=malformed).status_code, 422)
        bad_schema = {**parts, 'file': ('wrong.csv', b'Close,Volume\n1,2\n', 'text/csv')}
        self.assertEqual(self.client.post('/api/v1/datasets', files=bad_schema).status_code, 422)

    def test_upload_202_durable_validation_and_idempotent_repeat(self):
        parts = self.upload_parts()
        accepted = self.client.post('/api/v1/datasets', files=parts)
        self.assertEqual(accepted.status_code, 202, accepted.text)
        job_id = accepted.json()['job_id']
        self.assertEqual(self.client.get(f'/api/v1/jobs/{job_id}').json()['status'], 'completed')
        duplicate = self.client.post('/api/v1/datasets', files=parts)
        self.assertEqual(duplicate.status_code, 202)
        self.assertEqual(duplicate.json()['job_id'], job_id)
        self.assertFalse(self.service.execute_one())
        self.assertEqual(self.client.get(f'/api/v1/jobs/{job_id}').json()['status'], 'completed')
        listing = self.client.get('/api/v1/datasets').json()['datasets']
        self.assertEqual(listing[0]['status'], 'ready')
        self.assertNotIn('path', listing[0])

    def test_train_job_duplicate_and_retry_validation(self):
        dataset = upload_fixture(self.service)
        request = {'dataset_id':dataset, 'district_code':FIRST}
        queued = self.client.post('/api/v1/jobs/train', json=request)
        self.assertEqual(queued.status_code, 202)
        job_id = queued.json()['id']
        self.assertEqual(self.client.post('/api/v1/jobs/train', json=request).status_code, 409)
        self.assertEqual(self.client.post(f'/api/v1/jobs/{job_id}/retry').status_code, 409)
        self.service.store.claim()
        self.service.store.recover()
        retried = self.client.post(f'/api/v1/jobs/{job_id}/retry')
        self.assertEqual(retried.status_code, 202)
        self.assertNotEqual(retried.json()['id'], job_id)
        self.service.execute_one()
        self.assertEqual(self.client.get(f'/api/v1/jobs/{retried.json()["id"]}').json()['status'], 'completed')

    def test_rollback_rejects_unvalidated_version_without_changing_champion(self):
        dataset_id = upload_fixture(self.service)
        dataset = self.service.dataset(dataset_id)
        manager = ModelManager(Path(self.directory.name)/'models', backend=Backend())
        self.service._managers['historical'] = manager
        manager.train(dataset, FIRST)
        records = dataset.rows_for_district(FIRST)
        candidate = manager.fine_tune(FIRST, records[-41:])
        response = self.client.post(f'/api/v1/models/{FIRST}/rollback', json={
            'reason':'unvalidated candidate must not replace champion', 'version':candidate['candidate_version']})
        self.assertEqual(response.status_code, 202)
        self.service.execute_one()
        job = self.service.store.job(response.json()['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(manager.predict(FIRST, records[-20:])['model_version'], '1')

    def test_pre_evaluation_forecast_is_unavailable_not_leaked_training_result(self):
        dataset = upload_fixture(self.service)
        queued = self.client.post('/api/v1/jobs/train', json={'dataset_id':dataset,'district_code':FIRST})
        self.service.execute_one()
        self.assertEqual(self.service.store.job(queued.json()['id'])['status'], 'completed')
        response = self.client.get('/api/v1/forecasts', params={'dataset_id':dataset,'as_of':str(START+timedelta(days=200))})
        row = next(r for r in response.json()['forecasts'] if r['district_code'] == FIRST)
        self.assertIsNone(row['prediction'])
        self.assertEqual(row['quality_status'], 'BEFORE_EVALUATION_CUTOFF')

    def test_replay_future_query_and_invalid_advance_return_422(self):
        dataset = upload_fixture(self.service)
        created = self.client.post('/api/v1/replays', json={'dataset_id':dataset,
            'start_date':str(START+timedelta(days=320)), 'end_date':str(START+timedelta(days=409))})
        self.assertEqual(created.status_code, 202, created.text)
        replay_id = created.json()['id']
        self.service.execute_one()
        self.assertEqual(self.client.get('/api/v1/forecasts', params={'replay_id':replay_id,
            'as_of':str(START+timedelta(days=321))}).status_code, 422)
        self.assertEqual(self.client.post(f'/api/v1/replays/{replay_id}/advance', json={'days':0}).status_code, 422)
        self.assertEqual(self.client.post(f'/api/v1/replays/{replay_id}/advance', json={'days':181}).status_code, 422)

    def test_predict_200_actual_version_and_422_invalid_length_rain_gap_identity(self):
        dataset_id = upload_fixture(self.service)
        dataset = self.service.dataset(dataset_id)
        manager = ModelManager(Path(self.directory.name)/'prediction-models', backend=Backend())
        self.service._managers['historical'] = manager
        manager.train(dataset,FIRST)
        keys = ('station_id','date','groundwater_level','rainfall_mm','level_unit')
        sequence = [{k:r[k] for k in keys} for r in dataset.rows_for_district(FIRST)[-20:]]
        endpoint = f'/api/v1/districts/{FIRST}/predict'
        successful = self.client.post(endpoint,json={'sequence':sequence})
        self.assertEqual(successful.status_code,200,successful.text)
        self.assertEqual(successful.json()['model_version'],'1')
        self.assertAlmostEqual(successful.json()['prediction'],409.)
        self.assertEqual(self.client.post(endpoint,json={'sequence':sequence[:-1]}).status_code,422)
        negative_rain = [{**r,'rainfall_mm':-1.} if i == 0 else r for i,r in enumerate(sequence)]
        self.assertEqual(self.client.post(endpoint,json={'sequence':negative_rain}).status_code,422)
        gap = [dict(r) for r in sequence]
        gap[5]['date'] = gap[4]['date']
        self.assertEqual(self.client.post(endpoint,json={'sequence':gap}).status_code,422)
        mismatch = [{**r,'station_id':'another-well'} for r in sequence]
        self.assertEqual(self.client.post(endpoint,json={'sequence':mismatch}).status_code,422)

    def test_predict_valid_input_without_model_returns_503(self):
        from tests.test_groundwater_models import rows
        manager = ModelManager(Path(self.directory.name)/'empty-models',backend=Backend())
        self.service._managers['historical'] = manager
        keys = ('station_id','date','groundwater_level','rainfall_mm','level_unit')
        sequence = [{k:r[k] for k in keys} for r in rows()[-20:]]
        response = self.client.post(f'/api/v1/districts/{FIRST}/predict',json={'sequence':sequence})
        self.assertEqual(response.status_code,503,response.text)
        self.assertIn('model_not_ready',response.json()['detail'])


if __name__ == '__main__':
    unittest.main()
