import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from backend.observation_repository import ObservationRepository
from backend.groundwater_service import GroundwaterService
from backend.live_observations import LiveObservations


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.repo=ObservationRepository(self.root/'observations.sqlite3')
        self.mapping={'version':'test-v1','station_id':'TEST','district_code':'11110',
            'seoul_name':'A','weather_station':'108','level_unit':'gl.-m',
            'preprocessing_version':'strict-v1','approved':True,'evidence':['TEST FIXTURE ONLY']}
        self.repo.register_mapping(self.mapping)
    def tearDown(self):self.tmp.cleanup()
    def collect(self,job,source,value=1,missing=False,status='collected'):
        station='A' if source=='seoul' else '108'
        rows=[{'source':source,'source_station':station,'date':f'2024-03-{d:02d}','value':value} for d in range(1,21)]
        rejected=[{'reason':'missing_value','row':{'tm':'2024-03-20','stnId':'108','sumRn':''}}] if missing else []
        if missing:rows=rows[:-1]
        self.repo.record_collection(job,source,station,'2024-03-01','2024-03-20',{'status':status},rows,rejected,['test-hash'])
    def test_revisions_snapshot_and_original_values_are_immutable(self):
        self.collect('one','seoul',-23);self.collect('one','kma',0)
        snapshot=self.repo.publish_snapshot('TEST','test-v1','2024-03-01','2024-03-20')
        self.assertEqual(snapshot['rows'][0]['groundwater_level'],-23)
        self.assertEqual(snapshot['rows'][0]['rainfall_mm'],0)
        count=self.repo.summary()['counts']['source_revisions']
        self.collect('two','seoul',-23)
        self.assertEqual(self.repo.summary()['counts']['source_revisions'],count)
        self.collect('three','seoul',-24)
        newer=self.repo.publish_snapshot('TEST','test-v1','2024-03-01','2024-03-20')
        self.assertNotEqual(snapshot['id'],newer['id'])
        self.assertEqual(self.repo.snapshot(snapshot['id'])['rows'][0]['groundwater_level'],-23)
        self.collect('four','seoul',-23)
        restored=self.repo.publish_snapshot('TEST','test-v1','2024-03-01','2024-03-20')
        self.assertNotEqual(snapshot['id'],restored['id'])
        self.assertEqual(restored['rows'][0]['groundwater_level'],-23)
    def test_missing_revision_does_not_revive_previous_valid_rain(self):
        self.collect('one','seoul');self.collect('one','kma')
        self.collect('two','kma',missing=True)
        with self.assertRaisesRegex(ValueError,'incomplete'):
            self.repo.publish_snapshot('TEST','test-v1','2024-03-01','2024-03-20')
    def test_cutoff_excludes_later_available_observations(self):
        with patch('backend.observation_repository.now',return_value='2024-03-21T02:00:00+00:00'):
            self.collect('one','seoul');self.collect('one','kma')
        with self.assertRaisesRegex(ValueError,'incomplete'):
            self.repo.publish_snapshot('TEST','test-v1','2024-03-01','2024-03-20','2024-03-21T01:59:00+00:00')
        snapshot=self.repo.publish_snapshot('TEST','test-v1','2024-03-01','2024-03-20','2024-03-21T02:00:00+00:00')
        self.assertEqual(len(snapshot['rows']),20)
    def test_partial_collection_cannot_publish_snapshot(self):
        self.collect('one','seoul',status='failed');self.collect('one','kma')
        with self.assertRaisesRegex(ValueError,'incomplete source'):
            self.repo.publish_snapshot('TEST','test-v1','2024-03-01','2024-03-20')
    def test_future_success_cannot_validate_past_partial_collection(self):
        with patch('backend.observation_repository.now',return_value='2024-03-21T02:00:00+00:00'):
            self.collect('failed','seoul',status='failed');self.collect('rain','kma')
        with patch('backend.observation_repository.now',return_value='2024-03-21T04:00:00+00:00'):
            self.collect('success','seoul')
        with self.assertRaisesRegex(ValueError,'incomplete source'):
            self.repo.publish_snapshot('TEST','test-v1','2024-03-01','2024-03-20','2024-03-21T03:00:00+00:00')
        self.assertEqual(len(self.repo.publish_snapshot('TEST','test-v1','2024-03-01','2024-03-20')['rows']),20)

    def test_explicit_mapping_selection_and_daily_activation_preserve_training(self):
        self.collect('one','seoul');self.collect('one','kma')
        snapshot=self.repo.publish_snapshot('TEST','test-v1','2024-03-01','2024-03-20')
        self.repo.activate(snapshot['id'],'training');self.repo.activate(snapshot['id'])
        self.repo.activate(snapshot['id'])
        with self.repo.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM active_feature_snapshots').fetchone()[0],2)
        self.repo.register_mapping({**self.mapping,'version':'test-v2'})
        self.assertEqual(self.repo.selected_mappings()[0]['version'],'test-v1')
        self.repo.select_mapping('TEST','test-v2')
        self.assertEqual(self.repo.active(),{})
        with self.repo.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM active_feature_snapshots').fetchone()[0],1)

    def test_mapping_evidence_immutable_version_and_foreign_keys(self):
        with self.assertRaises(ValueError):self.repo.register_mapping({**self.mapping,'evidence':[],'version':'empty'})
        with self.assertRaises(ValueError):self.repo.register_mapping({**self.mapping,'weather_station':'109'})
        with self.assertRaises(sqlite3.IntegrityError):
            with self.repo.connect() as db:db.execute('INSERT INTO collection_members VALUES(?,?)',('none','none'))
    def test_consistent_backup_and_repeat_migration(self):
        self.collect('one','kma');backup=self.repo.backup(self.root/'backup.sqlite3')
        restored=ObservationRepository(backup)
        self.assertEqual(self.repo.summary(),restored.summary())
        self.assertEqual(ObservationRepository(self.repo.path).summary(),self.repo.summary())
    def test_live_25_unready_never_uses_historical_models(self):
        service=GroundwaterService(self.root/'service')
        live=LiveObservations(service)
        response=live.forecasts('2026-10-07')
        self.assertEqual(response['total'],25);self.assertEqual(response['ready_count'],0)
        self.assertEqual(response['input_end_date'],'2026-10-06')
        self.assertTrue(all(r['prediction'] is None and r['data_status']=='MAPPING_REQUIRED' for r in response['forecasts']))
        self.assertEqual(service.store.list('dataset'),[])

if __name__=='__main__':unittest.main()
