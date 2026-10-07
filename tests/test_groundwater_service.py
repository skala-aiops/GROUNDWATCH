"""Durable service and simulated-clock integration; no claimed model accuracy."""
import csv
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from data.groundwater import DISTRICTS
from serving_app.groundwater_service import GroundwaterService
from serving_app.groundwater_store import Store


FIRST = DISTRICTS[0]['district_code']
START = date(2020, 1, 1)


class FakeManager:
    def __init__(self):
        self.models, self.calls = {}, []

    def list_models(self):
        return list(self.models.values())

    def train(self, code, records, metadata, max_epochs):
        if len(records) < 410:
            raise ValueError('410 days required')
        splits = {'replay': {'start': records[-90]['date'], 'end': records[-1]['date']}}
        self.models[code] = {'district_code': code, 'model_version': '1', 'status': 'ready',
                             'threshold': .01, 'splits': splits, 'trained_through': records[199]['date']}
        return {'status': 'promoted', 'model_version': '1', 'splits': splits}

    def predict(self, code, records):
        self.calls.append(('predict', records[-1]['date']))
        return {'prediction': records[-1]['groundwater_level']-(10 if code == FIRST else 0),
                'model_version': self.models[code]['model_version'], 'unit': 'fixture_m'}

    def fine_tune(self, code, records, metadata):
        self.calls.append(('fine_tune', records[-1]['date']))
        return {'candidate_version': '2', 'status': 'awaiting_shadow'}

    def evaluate_candidate(self, code, version, records):
        self.calls.append(('evaluate', records[-1]['date']))
        self.models[code]['model_version'] = version
        return {'status': 'promoted', 'model_version': version}


def upload_fixture(service):
    manifest = {'approved': True, 'mapping_version': 'explicit-test-only',
                'stations': [{'district_code': district['district_code'],
                              'station_id': 'fixture-'+district['district_code'],
                              'level_unit': 'fixture_m'} for district in DISTRICTS]}
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=['station_id','district_code','date','groundwater_level','rainfall_mm','level_unit'])
    writer.writeheader()
    for i in range(410):
        writer.writerow({'station_id': 'fixture-'+FIRST, 'district_code': FIRST,
                         'date': str(START+timedelta(days=i)), 'groundwater_level': float(i),
                         'rainfall_mm': float(i%7), 'level_unit': 'fixture_m'})
    for district in DISTRICTS[1:]:
        for i in range(410):
            writer.writerow({'station_id': 'fixture-'+district['district_code'],
                             'district_code': district['district_code'], 'date': str(START+timedelta(days=i)),
                             'groundwater_level': 1., 'rainfall_mm': 0., 'level_unit': 'fixture_m'})
    queued = service.queue_upload(stream.getvalue().encode('utf-8-sig'), json.dumps(manifest).encode())
    service.execute_one()
    assert service.store.job(queued['job_id'])['status'] == 'completed', service.store.job(queued['job_id'])
    return queued['dataset_id']


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.managers = {}
        self.factory = lambda namespace: self.managers.setdefault(namespace, FakeManager())
        self.service = GroundwaterService(self.directory.name, self.factory)

    def tearDown(self):
        self.directory.cleanup()

    def replay(self):
        dataset = upload_fixture(self.service)
        replay = self.service.create_replay(dataset, str(START+timedelta(days=320)), str(START+timedelta(days=409)))
        self.service.execute_one()
        self.assertEqual(self.service.store.get('replay', replay['id'])['status'], 'ready')
        return replay['id']

    def test_durable_jobs_atomic_claim_duplicate_and_explicit_recovery(self):
        store = self.service.store
        first = store.enqueue('train', {'district_code':FIRST}, 'model:first')
        with self.assertRaises(ValueError):
            store.enqueue('train', {}, 'model:first')
        claimed = store.claim()
        self.assertEqual(claimed['id'], first['id'])
        reopened = Store(Path(self.directory.name)/'metadata.sqlite3')
        self.assertIsNone(reopened.claim())
        self.assertEqual(reopened.recover(), 1)
        self.assertEqual(reopened.job(first['id'])['status'], 'interrupted')
        self.assertIsNone(reopened.claim())
        retry = reopened.enqueue('train', {}, 'model:first')
        self.assertNotEqual(retry['id'], first['id'])

    def test_missing_data_returns_25_rows_without_fabricated_values(self):
        output = self.service.forecasts(as_of='2020-12-01')
        self.assertEqual(len(output['forecasts']), 25)
        self.assertEqual(output['ready_count'], 0)
        self.assertTrue(all(row['prediction'] is None for row in output['forecasts']))
        self.assertEqual({row['quality_status'] for row in output['forecasts']}, {'DATA_REQUIRED'})

    def test_modified_replay_is_marked_synthetic_without_changing_source(self):
        dataset = upload_fixture(self.service)
        replay = self.service.create_replay(dataset, str(START+timedelta(days=320)),
            str(START+timedelta(days=409)), scenario='level_shift',
            shift_start=str(START+timedelta(days=330)), shift_amount=.2)
        self.service.execute_one()
        output = self.service.forecasts(replay_id=replay['id'])
        self.assertTrue(all(row['source_kind'] == 'synthetic' for row in output['forecasts']))
        self.assertEqual(self.service.store.get('dataset', dataset)['source_kind'], 'observed')

    def test_two_workers_cannot_claim_same_durable_job(self):
        job = self.service.store.enqueue('train', {}, 'single-job')
        path = Path(self.directory.name)/'metadata.sqlite3'
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: Store(path).claim(), range(2)))
        self.assertEqual([c['id'] for c in claims if c], [job['id']])

    def test_forecasts_deduplicate_and_labels_reveal_after_clock_advance(self):
        replay_id = self.replay()
        self.service.forecasts(replay_id=replay_id)
        self.service.forecasts(replay_id=replay_id)
        before = self.service.store.forecasts(replay_id, FIRST)
        self.assertEqual(len(before), 1)
        self.assertIsNone(before[0]['actual'])
        replay = self.service.store.get('replay', replay_id)
        self.service.advance_day(replay)
        labelled = self.service.store.forecasts(replay_id, FIRST, labelled=True)
        self.assertEqual(len(labelled), 1)
        self.assertEqual(labelled[0]['actual'], 321.)
        self.assertEqual(replay['as_of'], str(START+timedelta(days=321)))
        self.assertEqual(self.service.forecasts(replay_id=replay_id)['ready_count'], 25)
        unavailable = [r for r in self.service.forecasts(replay_id=replay_id)['forecasts'] if r['district_code'] != FIRST]
        self.assertTrue(all(r['prediction'] is not None for r in unavailable))

    def test_future_replay_queries_rejected_and_history_hides_future(self):
        replay_id = self.replay()
        with self.assertRaises(ValueError):
            self.service.forecasts(as_of=str(START+timedelta(days=321)), replay_id=replay_id)
        history = self.service.history(FIRST, replay_id=replay_id)['history']
        self.assertEqual(max(row['date'] for row in history), str(START+timedelta(days=320)))

    def test_multi_day_advance_executes_finetune_before_shadow_future(self):
        replay_id = self.replay()
        job = self.service.advance_job(replay_id, 55)
        self.service.execute_one()
        self.assertEqual(self.service.store.job(job['id'])['status'], 'completed')
        calls = self.managers[replay_id].calls
        trained = [day for kind, day in calls if kind == 'fine_tune']
        evaluated = [day for kind, day in calls if kind == 'evaluate']
        self.assertEqual(len(trained), 1, calls)
        self.assertEqual(len(evaluated), 1, calls)
        self.assertEqual((date.fromisoformat(evaluated[0])-date.fromisoformat(trained[0])).days, 30)
        self.assertEqual(self.managers[replay_id].models[FIRST]['model_version'], '2')
        # A successful model update does not resolve the separate operational event.
        quality = [e for e in self.service.store.list('event') if e['kind'] == 'quality']
        self.assertTrue(quality)
        self.assertTrue(all(e['status'] == 'OPEN' for e in quality))

    def test_failed_training_job_keeps_existing_champion_available(self):
        dataset = upload_fixture(self.service)
        manager = self.service.manager()
        manager.train(FIRST,self.service.records(dataset,FIRST),{},100)
        manager.train = lambda *args, **kwargs: {'status':'rejected','version':'2','gate_passed':False}
        job = self.service.train_job(dataset,FIRST)
        self.service.execute_one()
        result = self.service.store.job(job['id'])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['result']['promoted_count'],0)
        response = self.service.forecasts(as_of=str(START+timedelta(days=350)),dataset_id=dataset)
        row = next(r for r in response['forecasts'] if r['district_code'] == FIRST)
        self.assertEqual(row['model_version'],'1')
        self.assertIsNotNone(row['prediction'])

    def test_forecast_cache_separates_actual_champion_versions(self):
        dataset = upload_fixture(self.service)
        manager = self.service.manager()
        manager.train(FIRST,self.service.records(dataset,FIRST),{},100)
        anchor = str(START+timedelta(days=350))
        first = self.service.forecasts(as_of=anchor,dataset_id=dataset)
        self.service.forecasts(as_of=anchor,dataset_id=dataset)
        self.assertEqual(len(manager.calls),1)
        manager.models[FIRST]['model_version'] = '2'
        second = self.service.forecasts(as_of=anchor,dataset_id=dataset)
        self.assertEqual(len(manager.calls),2)
        old = next(r for r in first['forecasts'] if r['district_code'] == FIRST)
        new = next(r for r in second['forecasts'] if r['district_code'] == FIRST)
        self.assertEqual(old['model_version'],'1')
        self.assertEqual(new['model_version'],'2')
        self.assertEqual(len(self.service.store.forecasts('historical',FIRST)),2)

    def test_retrained_champion_cannot_generate_new_forecasts_before_its_cutoff(self):
        dataset = upload_fixture(self.service)
        manager = self.service.manager()
        manager.train(FIRST,self.service.records(dataset,FIRST),{},100)
        manager.models[FIRST].update(model_version='2',trained_through=str(START+timedelta(days=350)))
        output = self.service.forecasts(as_of=str(START+timedelta(days=340)),dataset_id=dataset)
        row = next(r for r in output['forecasts'] if r['district_code'] == FIRST)
        self.assertIsNone(row['prediction'])
        self.assertEqual(manager.calls,[])


if __name__ == '__main__':
    unittest.main()
