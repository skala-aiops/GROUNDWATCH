"""Validate provenance and chronological separation, not synthetic accuracy."""
import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from data.current_extension import build_extension
from data.groundwater import load_canonical, continuous_windows, gap_aware_split


class CurrentExtensionTests(unittest.TestCase):
    def test_real_source_is_preserved_reproducible_and_synthetic_is_isolated(self):
        root = Path(__file__).resolve().parents[1]
        source, mapping = root/'data/groundwater_observations.csv', root/'data/representatives.json'
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            end = date(2026,10,8)
            path, manifest = build_extension(source,mapping,Path(directory)/'a',end)
            second, second_manifest = build_extension(source,mapping,Path(directory)/'b',end)
            self.assertEqual(path.read_bytes(),second.read_bytes())
            self.assertEqual(manifest.read_bytes(),second_manifest.read_bytes())
            stamp = json.loads((path.parent/'generation.json').read_text())
            build_extension(source,mapping,Path(directory)/'a',end)
            self.assertEqual(json.loads((path.parent/'generation.json').read_text()),stamp)
            self.assertTrue(stamp['generated_at'])
            self.assertEqual(stamp['identity'],hashlib.sha256(path.read_bytes()+manifest.read_bytes()).hexdigest())
            original = load_canonical(source,mapping)
            extended = load_canonical(path,manifest)
            observed = [r for r in extended.records if r.origin=='observed']
            values = lambda rows: {(r.station_id,r.date,r.groundwater_level,r.rainfall_mm,r.level_unit) for r in rows}
            self.assertEqual(values(original.records),values(observed))
            self.assertEqual(max(r.date for r in extended.records),end)
            self.assertEqual(extended.manifest['source_kind'],'synthetic')
            self.assertEqual(len(extended.manifest['provenance']['intervals']),25)
            self.assertTrue(all(r.rainfall_mm>=0 for r in extended.records))
            for code in extended.manifest['provenance']['intervals']:
                records=[r for r in extended.records if r.district_code==code]
                synthetic=[r for r in records if r.origin=='synthetic']
                boundary=max(r.date for r in records if r.origin=='observed')
                self.assertEqual(min(r.date for r in synthetic),boundary+timedelta(days=1))
                parts=gap_aware_split(continuous_windows(records),extended.manifest['training']['replay_start'])
                self.assertLess(parts['train'][-1].target_date,parts['validation'][0].target_date)
                self.assertLess(parts['test'][-1].target_date,parts['replay'][0].target_date)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)

    def test_verified_refresh_is_preserved_before_synthetic_tail(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            path, mapping = build_extension(root/'data/groundwater_observations.csv',
                root/'data/representatives.json', directory, date(2026,10,8),
                observed_extension_dir=root/'data')
            extended = load_canonical(path,mapping)
            self.assertTrue(extended.manifest['provenance']['additional_observation_snapshot_id'])
            for station in extended.manifest['stations']:
                rows = extended.rows_for_district(station['district_code'])
                self.assertEqual(max(r['date'] for r in rows if r['origin']=='observed'), '2026-09-30')
                self.assertEqual(min(r['date'] for r in rows if r['origin']=='synthetic'), '2026-10-01')
            self.assertEqual(extended.manifest['source_kind'],'synthetic')

    def test_future_generation_is_rejected(self):
        with self.assertRaises(ValueError):
            build_extension('unused','unused','unused',date.today()+timedelta(days=2))
