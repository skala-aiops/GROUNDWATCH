import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from backend.national_simulation import generate
from backend.national_repository import NationalRepository

DATA = Path(__file__).resolve().parents[3]/'data'

class SimulationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=json.loads((DATA/'national_stations_gims.json').read_text())
        cls.candidates=json.loads((DATA/'national_region_coverage_probe.json').read_text())

    def test_17_regions_reproducible_and_extend_without_rewriting_history(self):
        a=generate(self.catalog,self.candidates,'2026-10-07')
        b=generate(self.catalog,self.candidates,'2026-10-08')
        self.assertEqual(len(a['stations']),17)
        for x,y in zip(a['stations'],b['stations']):
            self.assertEqual(x['observations'],y['observations'][:-1])
            self.assertGreater(len(x['observations']),1095)
            self.assertFalse(x['station']['verified'])
            self.assertFalse(x['station']['operational_approved'])
            self.assertTrue(all(r['source_kind']=='synthetic' for r in x['observations']))

    def test_snapshot_source_isolation_and_immutable_revisions(self):
        item=generate(self.catalog,self.candidates,'2026-10-07')['stations'][0]
        with TemporaryDirectory() as root:
            repo=NationalRepository(Path(root)/'db.sqlite3')
            station=item['station']; sid=station['station_id']
            repo.register_station(station)
            rows=item['observations'][-20:]
            repo.add_observations(sid,rows)
            snapshot=repo.snapshot(sid,'2026-10-07','2026-10-08T12:00:00+09:00')
            self.assertEqual(snapshot['source_kind'],'synthetic')
            with self.assertRaisesRegex(ValueError,'immutable observation'):
                repo.add_observation(sid,{**rows[-1],'rainfall_mm':999})
            with self.assertRaisesRegex(ValueError,'incomplete_consecutive_input|daily_input_not_complete'):
                repo.snapshot(sid,'2026-10-07','2026-10-07T12:00:00+09:00')

if __name__=='__main__':unittest.main()
