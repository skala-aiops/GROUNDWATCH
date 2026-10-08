from datetime import datetime, timedelta
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from serving_app.national_observation_worker import NationalObservationCollector, groundwater_provider
from serving_app.national_repository import NationalRepository
from serving_app.weather_worker import atomic_json

class NationalObservationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.repo=NationalRepository(self.root/'national/observations.sqlite3')
        self.repo.register_station(dict(station_id='kwater-601739',provider='kwater',source_station_id='601739',
            name='광주도척',region_code='test',level_unit='m',level_reference='elevation',verified=False,
            source_kind='observed',source_contract_verified=True,mapping_status='experimental',
            mapping_version='mapping-v1',mapping_id='explicit-test',weather_source_station_id='203',evidence=['test']))
        self.now=datetime.fromisoformat('2026-10-08T11:30:00+09:00');self.calls=[]
        self.environment=patch.dict('os.environ',{'GIMS_API_KEY':'test-secret'});self.environment.start()
        self.rain()

    def tearDown(self):self.environment.stop();self.tmp.cleanup()

    def rain(self, day='2026-10-07',value=0):
        atomic_json(self.root/'weather/national_aws_daily.json',dict(unit='mm',provider='kma_ground_aws_daily',
            source_kind='observed',available_dates=[day],temporal_contract='completed_calendar_day_KST_rn_day',
            collection_status='collected',raw_sha256='b'*64,collected_at=self.now.isoformat(),
            observations=[dict(station_id='kma_ground_aws_daily:203',date=day,rainfall_mm=value,
                source_sha256='b'*64,available_at=self.now.isoformat())]))

    def fetch(self,sid,day,path):
        self.calls.append((sid,day))
        return dict(source_station_id=sid,date=day,value=108.2,metric='groundwater_level',
            unit='m',datum='elevation',quality='valid',raw_sha256='a'*64,
            available_at=self.now.isoformat(),collected_at=self.now.isoformat())

    def collector(self,fetch=None):
        return NationalObservationCollector(self.root,enabled=True,repository=self.repo,clock=lambda:self.now,fetch=fetch or self.fetch)

    def test_once_restart_zero_and_last_good(self):
        collector=self.collector();self.assertEqual(collector.tick()['status'],'ready')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.repo.observations('kwater-601739')[0]['rainfall_mm'],0)
        self.assertEqual(self.collector().tick()['status'],'ready');self.assertEqual(len(self.calls),1)
        self.now+=timedelta(days=1)
        self.assertEqual(self.collector().tick()['status'],'degraded')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(self.repo.observations('kwater-601739')),1)
        self.assertEqual(self.collector().state()['stations']['kwater-601739']['last_good_day'],'2026-10-07')

    def test_time_gate_missing_credentials_and_failure_backoff(self):
        self.now=self.now.replace(hour=11,minute=29)
        self.assertEqual(self.collector().tick()['status'],'waiting');self.assertFalse(self.calls)
        self.now+=timedelta(minutes=1)
        with patch.dict('os.environ',{'GIMS_API_KEY':''}):
            self.assertEqual(self.collector().tick()['reason'],'credentials_required')
        def failed(*args):self.calls.append('attempt');raise ValueError('https://provider/?KEY=test-secret')
        self.assertEqual(self.collector(failed).tick()['status'],'degraded')
        self.now+=timedelta(minutes=9);self.collector(failed).tick();self.assertEqual(len(self.calls),1)
        self.now+=timedelta(minutes=1);self.collector(failed).tick();self.assertEqual(len(self.calls),2)
        self.assertNotIn('test-secret',(self.root/'national/observation_collection/state.json').read_text())

    def test_cached_supplier_result_survives_db_failure(self):
        collector=self.collector()
        with patch.object(self.repo,'add_observations',side_effect=ValueError('database unavailable')):
            collector.tick()
        self.assertEqual(len(self.calls),1)
        self.now+=timedelta(minutes=10)
        self.assertEqual(self.collector().tick()['status'],'ready')
        self.assertEqual(len(self.calls),1)

    def test_provider_validates_actual_envelope_and_identity(self):
        rawdir=self.root/'provider';rawdir.mkdir()
        raw=json.dumps({'response':{'resultCode':'Success','resultData':[
            {'gennum':'601739','ymd':'20261007','elev':'108.2','lev':'4.05'}]}}).encode()
        path=rawdir/'raw.json';path.write_bytes(raw)
        page=dict(file=path.name,raw_sha256=hashlib.sha256(raw).hexdigest(),collected_at=self.now.isoformat())
        with patch('serving_app.national_observation_worker.collect_kwater',return_value={'raw_pages':[page]}):
            value=groundwater_provider('601739','2026-10-07',rawdir)
            self.assertEqual(value['value'],108.2)
            with self.assertRaises(ValueError):groundwater_provider('95537','2026-10-07',rawdir)
            path.write_bytes(raw+b' ')
            with self.assertRaises(ValueError):groundwater_provider('601739','2026-10-07',rawdir)

    def test_missing_mapped_value_never_zero_filled(self):
        self.rain(value=None)
        self.assertEqual(self.collector().tick()['status'],'degraded')
        self.assertFalse(self.calls);self.assertEqual(self.repo.observations('kwater-601739'),[])

if __name__=='__main__':unittest.main()
