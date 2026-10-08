"""Presentation clock cannot change source time or expose the next label."""
import tempfile
import unittest
from datetime import timedelta

from backend.groundwater_api import ReplayRequest
from backend.groundwater_service import GroundwaterService
from backend.tests.support.groundwater_service import FakeManager, upload_fixture, FIRST, START


class SupplySimulationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.managers = {}
        self.factory = lambda namespace: self.managers.setdefault(namespace, FakeManager())
        self.service = GroundwaterService(self.directory.name, self.factory)
        self.dataset = upload_fixture(self.service)
        self.start = str(START + timedelta(days=320))

    def tearDown(self):
        self.directory.cleanup()

    def create(self, **extra):
        replay = self.service.create_replay(self.dataset, self.start,
            str(START + timedelta(days=409)), presentation_start_date='2026-10-07', **extra)
        self.service.execute_one()
        self.assertEqual(self.service.store.get('replay', replay['id'])['status'], 'ready')
        return replay['id']

    def test_clock_persists_and_namespaces_are_independent(self):
        first, second = self.create(), self.create()
        self.assertNotEqual(first, second)
        self.assertNotEqual(self.service.manager(first), self.service.manager(second))
        reopened = GroundwaterService(self.directory.name, self.factory)
        replay = reopened.store.get('replay', first)
        clock = reopened.simulation_clock(replay)
        self.assertEqual(clock['presentation_as_of'], '2026-10-07')
        self.assertEqual(clock['source_as_of'], self.start)
        self.assertEqual(clock['elapsed_days'], 0)
        self.assertEqual(reopened.pipeline(FIRST, first)['simulation'], clock)

    def test_predict_before_reveal_and_advance_one_day(self):
        replay_id = self.create()
        before = self.service.forecasts(replay_id=replay_id)
        next_date = str(START + timedelta(days=321))
        self.assertEqual(before['as_of'], self.start)
        self.assertEqual(before['simulation']['presentation_forecast_date'], '2026-10-08')
        self.assertEqual(before['forecasts'][0]['forecast_date'], next_date)
        self.assertEqual(before['forecasts'][0]['presentation_observed_date'], '2026-10-07')
        self.assertEqual(before['forecasts'][0]['source_kind'], 'observed')
        self.assertEqual(self.service.store.forecasts(replay_id, FIRST, labelled=True), [])
        history = self.service.history(FIRST, replay_id=replay_id)['history']
        self.assertEqual(history[-1]['date'], next_date)
        self.assertEqual(history[-1]['presentation_date'], '2026-10-08')
        self.assertIsNone(history[-1]['groundwater_level'])
        self.assertIsNone(history[-1]['rainfall_mm'])
        self.assertIsNotNone(history[-1]['prediction'])
        with self.assertRaises(ValueError):
            self.service.forecasts(as_of=next_date, replay_id=replay_id)
        with self.assertRaises(ValueError):
            self.service.advance_job(replay_id, days=2)
        self.service.advance_job(replay_id)
        self.service.execute_one()
        after = self.service.forecasts(replay_id=replay_id)
        self.assertEqual(after['as_of'], next_date)
        self.assertEqual(after['simulation']['presentation_as_of'], '2026-10-08')
        self.assertEqual(after['simulation']['elapsed_days'], 1)
        labels = self.service.store.forecasts(replay_id, FIRST, labelled=True)
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0]['actual'], 321.)
        history = self.service.history(FIRST, replay_id=replay_id)['history']
        self.assertEqual(history[-2]['groundwater_level'], 321.)
        self.assertIsNone(history[-1]['groundwater_level'])
        cached = self.service.store.forecasts(replay_id, FIRST)
        self.assertTrue(all('presentation_forecast_date' not in row for row in cached))
        self.assertEqual(self.service.records(self.dataset, FIRST)[321]['date'], next_date)

    def test_original_replay_unchanged_and_synthetic_scenario_rejected(self):
        body = ReplayRequest(dataset_id=self.dataset, start_date=self.start,
                             presentation_start_date='2026-10-07')
        self.assertEqual(body.model_dump(mode='json')['presentation_start_date'], '2026-10-07')
        with self.assertRaises(ValueError):
            self.create(scenario='level_shift', shift_start=str(START + timedelta(days=330)), shift_amount=.2)
        replay = self.service.create_replay(self.dataset, self.start)
        self.service.execute_one()
        self.assertEqual(self.service.forecasts(replay_id=replay['id'])['simulation'], {'enabled': False})
        self.service.advance_job(replay['id'], 2)


if __name__ == '__main__':
    unittest.main()
