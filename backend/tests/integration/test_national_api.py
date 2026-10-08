"""Synthetic fixtures exercise the observed contract with a fake model; not real data evidence."""
import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from backend.main import create_app
from backend.groundwater_service import GroundwaterService
from backend.national_sources import import_csv, join_daily
from backend.national_service import NationalService
from backend.tests.support.groundwater_service import FakeManager


class FakeNationalModelManager:
    def __init__(self):
        self.models = {}
        self.training_rows = {}

    def train(self, station_id, records, metadata, variant):
        if not metadata['verified']:
            raise ValueError('unverified metadata')
        self.training_rows[station_id] = records
        result = {'station_id':station_id,'model_version':'fixture-v1',
                  'variant':variant,'source_kind':metadata['source_kind'],
                  'feature_contract_id':'national-m0-v1'}
        self.models[station_id] = result
        return result

    def predict(self, station_id, rows, metadata):
        model = self.models[station_id]
        return {**model,'prediction':rows[-1]['groundwater_level']}

    def list_models(self, station_id):
        return [self.models[station_id]] if station_id in self.models else []


class NationalApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.seoul = GroundwaterService(Path(self.tmp.name)/'legacy',lambda namespace:FakeManager())
        self.manager = FakeNationalModelManager()
        self.national = NationalService(Path(self.tmp.name)/'national-fixture',manager=self.manager)
        self.client = TestClient(create_app(self.seoul,national_service=self.national))
        self.station = dict(station_id='fixture-national-001',provider='fixture',
                            source_station_id='raw/001',name='SYNTHETIC TEST ONLY',
                            region_code='fixture-region',level_unit='m',level_reference='ground_surface_signed',
                            verified=True,evidence=['SYNTHETIC TEST ONLY'],source_kind='observed')
        self.base = '/api/v2/stations/fixture-national-001'

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def register(self):
        response = self.client.post('/api/v2/stations',json=self.station)
        self.assertEqual(response.status_code,201,response.text)

    def fixture_rows(self):
        first = date(2024,1,1)
        return [dict(date=(first+timedelta(days=n)).isoformat(),groundwater_level=-5+n*.001,
                     rainfall_mm=float(n%3),level_unit='m',level_reference='ground_surface_signed',
                     revision_id=f'synthetic-{n}',source_sha256='synthetic-test-only',
                     available_at='2024-06-01T00:00:00Z',collected_at='2024-06-01T00:00:00Z')
                for n in range(140)]

    def test_queued_train_predict_http_results_and_legacy_contract_preserved(self):
        before = self.client.get('/api/v1/forecasts').json()
        self.register()
        rows = self.fixture_rows()
        imported = self.client.post(self.base+'/observations',json={'rows':rows})
        self.assertEqual(imported.status_code,201,imported.text)
        self.assertEqual(len(self.client.get(self.base+'/history').json()['history']),140)
        train = self.client.post(self.base+'/training-jobs',json={'variant':'M0'})
        self.assertEqual(train.status_code,202,train.text)
        job = train.json()
        self.assertEqual(job['status'],'queued')
        self.assertEqual(self.manager.models,{})
        self.assertTrue(self.national.execute_one())
        trained = self.client.get('/api/v2/jobs/'+job['id']).json()
        self.assertEqual(trained['status'],'completed',trained)
        self.assertEqual(trained['result']['source_kind'],'observed')
        self.assertEqual(len(self.manager.training_rows[self.station['station_id']]),140)
        predict = self.client.post(self.base+'/prediction-jobs',json={'input_end_date':rows[-1]['date']})
        self.assertEqual(predict.status_code,202,predict.text)
        self.assertEqual(self.client.get(self.base+'/forecast').status_code,503)
        self.assertTrue(self.national.execute_one())
        completed = self.client.get('/api/v2/jobs/'+predict.json()['id']).json()
        self.assertEqual(completed['status'],'completed',completed)
        prediction = self.client.get(self.base+'/forecast')
        self.assertEqual(prediction.status_code,200,prediction.text)
        payload = prediction.json()
        self.assertEqual(payload['source_kind'],'observed')
        self.assertEqual(payload['mode'],'historical_replay')
        self.assertEqual(payload['target_date'],'2024-05-20')
        self.assertEqual(payload['model_version'],'fixture-v1')
        self.assertEqual(payload['prediction'],rows[-1]['groundwater_level'])
        self.assertEqual(len(payload['snapshot_id']),64)
        after = self.client.get('/api/v1/forecasts').json()
        self.assertEqual(len(before['forecasts']),25)
        stable = lambda rows: [{k:v for k,v in r.items() if k != 'generated_at'} for r in rows]
        self.assertEqual(stable(before['forecasts']),stable(after['forecasts']))
        self.assertEqual(self.seoul.store.list('prediction'),[])

    def test_unknown_station_no_prediction_and_request_validation(self):
        self.assertEqual(self.client.get('/api/v2/stations/missing').status_code,404)
        self.assertEqual(self.client.get('/api/v2/stations/missing/forecast').status_code,404)
        self.register()
        self.assertEqual(self.client.get(self.base+'/forecast').status_code,503)
        self.assertEqual(self.client.get(self.base+'/forecast?target_date=not-a-date').status_code,422)
        self.assertEqual(self.client.post(self.base+'/training-jobs',json={'variant':'M2'}).status_code,422)
        self.assertEqual(self.client.post('/api/v2/stations',json={**self.station,'station_id':'bad/id'}).status_code,422)

    def test_atomic_batch_rejects_late_invalid_row_and_revision_conflict(self):
        self.register()
        rows = self.fixture_rows()[:2]
        bad = [{**rows[0]},{**rows[1],'rainfall_mm':-1}]
        self.assertEqual(self.client.post(self.base+'/observations',json={'rows':bad}).status_code,422)
        self.assertEqual(self.client.get(self.base+'/history').json()['history'],[])
        self.assertEqual(self.client.post(self.base+'/observations',json={'rows':[rows[1]]}).status_code,201)
        conflict = [rows[0],{**rows[1],'groundwater_level':-99}]
        self.assertEqual(self.client.post(self.base+'/observations',json={'rows':conflict}).status_code,422)
        history = self.client.get(self.base+'/history').json()['history']
        self.assertEqual(len(history),1)
        self.assertEqual(history[0]['date'],rows[1]['date'])

    def test_synthetic_file_import_join_to_http_preserves_source_revisions(self):
        self.station['level_reference'] = 'ground_level_depth'
        self.register()
        path = Path(self.tmp.name)/'synthetic-levels.csv'
        with path.open('w',newline='') as handle:
            writer = csv.DictWriter(handle,fieldnames=['source_station_id','date','value','unit','datum'])
            writer.writeheader()
            for n in range(1,21):
                writer.writerow(dict(source_station_id='raw/001',date=f'2024-07-{n:02d}',
                                     value=-5.,unit='m',datum='ground_level_depth'))
        levels = import_csv(path,source='synthetic_fixture',collected_at='2024-07-21T00:00:00Z')
        self.assertEqual(len(levels['accepted']),20)
        rain = [dict(provider='synthetic_fixture',source_station_id='rain/001',date=item['date'],
                     value=0.,metric='rainfall_mm',unit='mm',datum='precipitation',quality='valid',
                     raw_sha256='synthetic-rain-hash',available_at='2024-07-21T00:00:00Z',
                     collected_at='2024-07-21T00:00:00Z') for item in levels['accepted']]
        joined = join_daily(levels['accepted'],rain,station_id=self.station['station_id'])
        self.assertEqual(len(joined['accepted']),20)
        response = self.client.post(self.base+'/observations',json={'rows':joined['accepted']})
        self.assertEqual(response.status_code,201,response.text)
        history = self.client.get(self.base+'/history').json()['history']
        self.assertEqual(len(history),20)
        self.assertEqual(history[0]['source_revisions'],[levels['raw_sha256'],'synthetic-rain-hash'])
        self.assertEqual(self.client.get(self.base).json()['source_kind'],'observed')
        mismatch = {**joined['accepted'][0],'station_id':'wrong-station','revision_id':'wrong-identity'}
        self.assertEqual(self.client.post(self.base+'/observations',json={'rows':[mismatch]}).status_code,422)

    def test_unverified_prediction_fails_and_sources_do_not_claim_live_readiness(self):
        self.station['verified'] = False
        self.register()
        queued = self.client.post(self.base+'/prediction-jobs',json={'input_end_date':'2024-05-19'})
        self.assertEqual(queued.status_code,202)
        self.national.execute_one()
        job = self.client.get('/api/v2/jobs/'+queued.json()['id']).json()
        self.assertEqual(job['status'],'failed')
        self.assertEqual(self.client.get(self.base+'/forecast').status_code,503)
        sources = self.client.get('/api/v2/sources').json()
        self.assertEqual(sources['status'],'observations_collected_models_not_approved')
        self.assertTrue(any(s['status']=='raw_samples_collected_station_validation_required' for s in sources['sources']))
