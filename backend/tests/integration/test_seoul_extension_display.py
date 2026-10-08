import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from backend.network_service import NetworkService
from backend.seoul_observation_extension import DATA, load_extension


class ExtensionDisplayTests(unittest.TestCase):
    def test_actual_snapshot_and_source_rain(self):
        snapshot = load_extension()
        self.assertEqual(sum(map(len, snapshot['rows'].values())), 22582)
        rows = snapshot['rows']['11110']
        self.assertEqual(rows[-1]['date'], '2026-09-30')
        self.assertTrue(all(r['prediction'] is None for r in rows))
        self.assertTrue(any(r['rainfall_mm'] == 0 for r in rows))

    def test_integrity_and_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['groundwater_observations.csv','representatives.json',
                         'seoul_observation_extension.csv','seoul_observation_extension_manifest.json']:
                (root/name).write_bytes((DATA/name).read_bytes())
            self.assertIsNotNone(load_extension(root))
            payload = (root/'seoul_observation_extension.csv').read_bytes()
            (root/'seoul_observation_extension.csv').write_bytes(payload+b'\n')
            self.assertIsNone(load_extension(root))
            (root/'seoul_observation_extension.csv').write_bytes(payload)
            manifest = json.loads((root/'seoul_observation_extension_manifest.json').read_text())
            manifest['stations'][0]['station_id'] = 'wrong-station'
            (root/'seoul_observation_extension_manifest.json').write_text(json.dumps(manifest))
            self.assertIsNone(load_extension(root))

    def test_current_observed_only_never_predicts_or_changes_base_row(self):
        service = NetworkService(SimpleNamespace(), SimpleNamespace())
        base = {'district_code':'11110','station_id':'SU-JNO-G1-0007',
                'observed_date':'2024-03-18','prediction':3.,'model_version':'1',
                'source_kind':'observed','data_source':{'input_through':'2024-03-18'}}
        current = service._current_seoul_observation(base, 'current', None, '2026-10-08')
        self.assertEqual(current['observed_date'], '2026-09-30')
        self.assertEqual(current['quality_status'], 'STALE_DATA')
        self.assertEqual(current['freshness_days'], 8)
        self.assertIsNone(current['prediction'])
        self.assertIsNone(current['data_source']['input_through'])
        self.assertEqual(base['prediction'], 3.)
        self.assertIs(service._current_seoul_observation(base,'historical_replay',None,'2026-10-08'),base)
        self.assertIs(service._current_seoul_observation(base,'current','replay','2026-10-08'),base)
        synthetic = {**base,'source_kind':'synthetic'}
        self.assertIs(service._current_seoul_observation(synthetic,'current',None,'2026-10-08'),synthetic)
        other = {**base,'station_id':'other'}
        self.assertIs(service._current_seoul_observation(other,'current',None,'2026-10-08'),other)

    def test_current_history_uses_same_observed_snapshot_replay_is_frozen(self):
        row = {'district_code':'11110','district_name':'종로구',
               'station_id':'SU-JNO-G1-0007','source_kind':'observed',
               'observed_date':'2024-03-18','prediction':None}
        legacy = SimpleNamespace(
            forecasts=lambda **kw: {'forecasts':[row],'as_of':'2026-10-08'},
            history=lambda *a,**kw: {'history':[{'date':'2024-03-18',
                'groundwater_level':-20.,'rainfall_mm':1.}]})
        national = SimpleNamespace(repo=SimpleNamespace(
            list_stations=lambda **kw: {'items':[],'next_cursor':None},
            rainy_periods=lambda **kw: []))
        from unittest.mock import patch
        with patch('backend.network_service._read', side_effect=lambda name, default: default):
            service = NetworkService(legacy,national)
            current = service.history('seoul:SU-JNO-G1-0007',mode='current')
            historical = service.history('seoul:SU-JNO-G1-0007',mode='historical_replay')
        self.assertEqual(current['history'][-1]['date'],'2026-09-30')
        self.assertEqual(len(current['history']),180)
        self.assertTrue(all(r['prediction'] is None for r in current['history']))
        self.assertEqual(historical['history'][-1]['date'],'2024-03-18')
        self.assertFalse(current['station']['capabilities']['train'])
