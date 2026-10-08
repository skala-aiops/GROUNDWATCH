import tempfile
import unittest
from pathlib import Path
from backend.national_repository import NationalRepository


class NationalRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = NationalRepository(Path(self.tmp.name)/'national.sqlite3')
        self.metadata = dict(station_id='fixture-001',provider='fixture',source_station_id='raw/001',
                             name='TEST FIXTURE ONLY',region_code='test-region',level_unit='m',
                             level_reference='ground_surface_signed',verified=True,
                             evidence=['TEST FIXTURE ONLY'],source_kind='synthetic')
        self.repo.register_station(self.metadata)

    def tearDown(self):
        self.tmp.cleanup()

    def row(self, day, **changes):
        return dict(date=f'2024-07-{day:02d}',groundwater_level=-5.0,rainfall_mm=0.,
                    level_unit='m',level_reference='ground_surface_signed',
                    revision_id=f'fixture-{day}',source_sha256='fixture-hash',
                    available_at='2024-07-21T00:00:00Z',collected_at='2024-07-21T00:00:00Z',
                    **changes)

    def populate(self):
        for n in range(1,21):
            self.repo.add_observation('fixture-001',self.row(n))

    def test_same_region_multiple_stations_and_page_counts(self):
        self.repo.register_station({**self.metadata,'station_id':'fixture-002','source_station_id':'raw/002'})
        first = self.repo.list_stations(region_code='test-region',limit=1)
        second = self.repo.list_stations(region_code='test-region',cursor=first['next_cursor'],limit=1)
        self.assertEqual(first['total'],2)
        self.assertEqual(second['total'],2)
        self.assertEqual(second['verified_count'],2)
        self.assertEqual(second['items'][0]['station_id'],'fixture-002')
        self.assertEqual(self.repo.list_stations(region_code="' OR 1=1 --")['total'],0)

    def test_metadata_id_evidence_and_immutability(self):
        for change in [{'station_id':'bad/id'},{'verified':'true'},{'evidence':[]}]:
            with self.assertRaises(ValueError):
                self.repo.register_station({**self.metadata,**change})
        with self.assertRaisesRegex(ValueError,'immutable'):
            self.repo.register_station({**self.metadata,'level_unit':'cm'})
        self.assertEqual(self.repo.register_station(self.metadata),self.metadata)
        with self.assertRaises(KeyError):self.repo.station('absent')

    def test_snapshot_repeatability_and_restart(self):
        self.populate()
        snap = self.repo.snapshot('fixture-001','2024-07-20','2024-07-21T00:00:00Z')
        self.assertEqual(snap['target_date'],'2024-07-21')
        self.assertEqual(len(snap['rows']),20)
        self.assertEqual(snap['rows'][0]['groundwater_level'],-5.)
        self.assertEqual(snap['source_kind'],'synthetic')
        restored = NationalRepository(self.repo.path)
        self.assertEqual(restored.snapshot('fixture-001','2024-07-20','2024-07-21T00:00:00Z'),snap)
        self.assertTrue(restored.readiness('fixture-001','2024-07-20','2024-07-21T00:00:00Z')['data_ready'])

    def test_cutoff_audit_does_not_change_identical_input_identity(self):
        self.populate()
        a = self.repo.snapshot('fixture-001','2024-07-20','2024-07-21T00:00:00Z')
        b = self.repo.snapshot('fixture-001','2024-07-20','2024-07-21T01:00:00Z')
        self.assertEqual(a['id'],b['id'])
        self.assertNotEqual(a['cutoff'],b['cutoff'])
        self.repo.add_observation('fixture-001',{**self.row(20),'revision_id':'new-revision',
                                  'available_at':'2024-07-22T00:00:00Z','collected_at':'2024-07-22T00:00:00Z'})
        c = self.repo.snapshot('fixture-001','2024-07-20','2024-07-22T00:00:00Z')
        self.assertNotEqual(a['id'],c['id'])

    def test_cutoff_and_timezone_and_collection_visibility(self):
        self.populate()
        with self.assertRaisesRegex(ValueError,'incomplete'):
            self.repo.snapshot('fixture-001','2024-07-20','2024-07-20T23:59:59Z')
        with self.assertRaisesRegex(ValueError,'timezone'):
            self.repo.snapshot('fixture-001','2024-07-20','2024-07-21T00:00:00')
        late = self.row(20)
        late.update(revision_id='late',groundwater_level=-100,
                    collected_at='2024-07-22T00:00:00Z')
        self.repo.add_observation('fixture-001',late)
        self.assertEqual(self.repo.snapshot('fixture-001','2024-07-20',
                         '2024-07-21T00:00:00Z')['rows'][-1]['groundwater_level'],-5)
        self.assertEqual(self.repo.snapshot('fixture-001','2024-07-20',
                         '2024-07-22T00:00:00Z')['rows'][-1]['groundwater_level'],-100)

    def test_invalid_revision_does_not_revive_previous_valid_value(self):
        self.populate()
        old = self.repo.snapshot('fixture-001','2024-07-20','2024-07-21T00:00:00Z')
        correction=self.row(20)
        correction.update(revision_id='correction',quality_status='missing',rainfall_mm=None,
                          collected_at='2024-07-22T00:00:00Z')
        self.repo.add_observation('fixture-001',correction)
        with self.assertRaisesRegex(ValueError,'invalid_quality'):
            self.repo.snapshot('fixture-001','2024-07-20','2024-07-22T00:00:00Z')
        self.assertEqual(old,self.repo.snapshot('fixture-001','2024-07-20','2024-07-21T00:00:00Z'))
        with self.assertRaisesRegex(ValueError,'immutable'):
            self.repo.add_observation('fixture-001',{**correction,'rainfall_mm':1.})

    def test_unverified_gap_unit_and_nonfinite_fail_closed(self):
        self.repo.register_station({**self.metadata,'station_id':'unverified','verified':False})
        self.assertEqual(self.repo.readiness('unverified')['status'],'unverified_metadata')
        for changes in [{'rainfall_mm':-1},{'groundwater_level':float('nan')},{'rainfall_mm':True}]:
            with self.assertRaises(ValueError):
                self.repo.add_observation('fixture-001',{**self.row(1),**changes})
        for n in range(1,20):self.repo.add_observation('fixture-001',self.row(n))
        with self.assertRaisesRegex(ValueError,'incomplete'):
            self.repo.snapshot('fixture-001','2024-07-20','2024-07-21T00:00:00Z')
        self.repo.add_observation('fixture-001',{**self.row(20),'level_reference':'sea_level'})
        with self.assertRaisesRegex(ValueError,'reference_mismatch'):
            self.repo.snapshot('fixture-001','2024-07-20','2024-07-21T00:00:00Z')

    def test_batch_import_atomic_for_invalid_row_and_existing_revision_conflict(self):
        with self.assertRaises(ValueError):
            self.repo.add_observations('fixture-001',[self.row(1),{**self.row(2),'rainfall_mm':-1}])
        self.assertEqual(self.repo.observations('fixture-001'),[])
        self.repo.add_observation('fixture-001',self.row(2))
        with self.assertRaisesRegex(ValueError,'immutable'):
            self.repo.add_observations('fixture-001',[self.row(1),{**self.row(2),'rainfall_mm':10}])
        self.assertEqual([r['date'] for r in self.repo.observations('fixture-001')],['2024-07-02'])
        self.assertEqual(len(self.repo.add_observations('fixture-001',[self.row(1),self.row(2)])),2)

    def test_same_timestamp_conflicting_revisions_block_snapshot(self):
        self.populate()
        self.repo.add_observation('fixture-001',{**self.row(20),'revision_id':'z-other','groundwater_level':-9})
        with self.assertRaisesRegex(ValueError,'invalid_quality'):
            self.repo.snapshot('fixture-001','2024-07-20','2024-07-21T00:00:00Z')

    def test_rainy_periods_evaluation_only_and_immutable_revision(self):
        item=dict(year=2024,region_code='fixture-central',start_date='2024-06-20',
                  end_date='2024-07-20',source_sha256='fixture',evidence=['TEST FIXTURE ONLY'])
        period=self.repo.add_rainy_period(item)
        self.assertEqual(period,self.repo.add_rainy_period(item))
        self.assertEqual(len(self.repo.rainy_periods(year=2024)),1)
        self.repo.add_rainy_period({**item,'end_date':'2024-07-21','source_sha256':'fixture-revised'})
        self.assertEqual(len(self.repo.rainy_periods(year=2024)),2)
        with self.assertRaises(ValueError):self.repo.add_rainy_period({**item,'usage':'live_feature'})
        with self.assertRaises(ValueError):self.repo.add_rainy_period({**item,'end_date':'2023-07-01'})
