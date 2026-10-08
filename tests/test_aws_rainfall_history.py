import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('aws_history_builder', ROOT/'scripts/build_aws_rainfall_history.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class HistoryBuilderTests(unittest.TestCase):
    def cache(self, root, day, lon=127):
        raw = root/'raw'/('aws-'+day+'.txt')
        raw.parent.mkdir(exist_ok=True)
        compact = day.replace('-', '')
        raw.write_bytes(('#START7777\n# YYMMDD STN LON LAT HT VAL\n'+
            f'{compact} 549 {lon} 37 80 0 용인\n#7777END\n').encode('cp949'))
        value = builder.parse_aws_daily(raw, requested_date=compact, collected_at='2026-10-08T00:00:00+00:00')
        value['raw_path'] = str(raw)
        parsed = root/'parsed'/(day+'.json')
        parsed.parent.mkdir(exist_ok=True)
        parsed.write_text(json.dumps(value))
        return parsed, raw

    def test_date_specific_coordinates_and_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.cache(root,'2026-07-01',127)
            self.cache(root,'2026-07-03',128)
            value=builder.build(root)
            self.assertEqual(value['available_dates'], ['2026-07-01','2026-07-03'])
            self.assertNotIn('longitude',value['stations'][0])
            self.assertEqual(value['station_metadata_by_date']['2026-07-03'][0]['longitude'],128)
            self.assertEqual([r['rainfall_mm'] for r in value['observations']],[0,0])
            self.assertEqual(len(value['quality']['coordinate_or_name_variant_station_ids']),1)

    def test_raw_and_cache_tampering_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            parsed,raw=self.cache(root,'2026-07-01')
            original=raw.read_bytes()
            raw.write_bytes(original+b'changed')
            with self.assertRaises(ValueError):builder.build(root)
            raw.write_bytes(original)
            value=json.loads(parsed.read_text());value['observations'][0]['rainfall_mm']=999
            parsed.write_text(json.dumps(value))
            with self.assertRaises(ValueError):builder.build(root)

    def test_unfinished_response_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            parsed,raw=self.cache(root,'2026-07-01')
            raw.write_bytes(raw.read_bytes().replace(b'#7777END',b''))
            value=json.loads(parsed.read_text())
            import hashlib
            value['raw_sha256']=hashlib.sha256(raw.read_bytes()).hexdigest()
            parsed.write_text(json.dumps(value))
            with self.assertRaises(ValueError):builder.build(root)


if __name__=='__main__':unittest.main()
