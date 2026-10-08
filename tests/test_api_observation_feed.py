import tempfile
import unittest
import json
from pathlib import Path
from datetime import date, timedelta
from serving_app.api_observation_feed import ApiObservationFeed
from serving_app.external_observations import SourceError
from serving_app.api_feed_models import input_hash


class Client:
    def seoul_page(self, start, end):
        self.station_filter_absent = True
        recent = date.today()-timedelta(days=40)
        rows = [{'OBSVTR_NM':'홍익대대학로캠퍼스','OBSRVN_YMD':'20410130','UDGD_WATL':4}]
        rows += [{'OBSVTR_NM':'홍익대대학로캠퍼스','OBSRVN_YMD':(recent-timedelta(days=i)).strftime('%Y%m%d'),
                  'UDGD_WATL':22.67+i*.01} for i in range(92)]
        return {'row':rows}, rows, len(rows)

    def kma_page(self, start, end, station, page):
        day = (date.today()-timedelta(days=40)).isoformat()
        rows = [{'tm':day,'stnId':'108','sumRn':''},
                {'tm':(date.today()-timedelta(days=41)).isoformat(),'stnId':'108','sumRn':'2.5'}]
        return {'row':rows}, rows, 2


class ApiFeedTests(unittest.TestCase):
    def test_changed_observations_never_serve_cached_prediction_from_old_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            feed=ApiObservationFeed(root,Client());feed.refresh()
            history=feed.history('11110')['history']
            model={'input_hash':input_hash(history),'status':'ready','prediction':23.0,
                   'model_version':'1','forecast_date':'2026-09-01','issued_at':'2026-10-08T00:00:00Z',
                   'metrics':{},'splits':{},'backtest':[]}
            (feed.folder/'models.json').write_text(json.dumps({'stations':{'11110':model}}))
            self.assertEqual(feed.overview()['forecasts'][0]['prediction'],23.0)
            self.assertEqual(feed.prediction_history('11110')['history'][-1]['prediction'],23.0)
            state=feed.read();state['water']['11110']['rows'][-1]['value']+=1
            (feed.folder/'latest.json').write_text(json.dumps(state))
            self.assertIsNone(feed.overview()['forecasts'][0]['prediction'])
            self.assertTrue(all(row['prediction'] is None for row in feed.prediction_history('11110')['history']))

    def test_input_readiness_does_not_bridge_missing_calendar_days_or_rain(self):
        start = date(2026, 1, 1)
        rows = [{'date':(start+timedelta(days=i)).isoformat(),
                 'groundwater_level':22.0, 'rainfall_mm':0.0} for i in range(25)]
        rows[10]['rainfall_mm'] = None
        del rows[20]
        result = ApiObservationFeed.input_readiness(rows)
        self.assertEqual(result['complete_days'],23)
        self.assertEqual(result['longest_consecutive_days'],10)
        self.assertEqual(result['latest_consecutive_days'],4)
        self.assertEqual(result['missing_rain_days'],1)
        self.assertFalse(result['latest_window_complete'])
        self.assertFalse(result['model_contract_verified'])

    def test_actual_lag_and_raw_values_are_kept_without_fabricating_predictions(self):
        with tempfile.TemporaryDirectory() as root:
            feed = ApiObservationFeed(root, Client())
            state = feed.refresh()
            self.assertEqual(state['future_rows'],1)
            row = feed.overview()['forecasts'][0]
            self.assertEqual(row['observed_date'],(date.today()-timedelta(days=40)).isoformat())
            self.assertEqual(row['latest_comparison']['actual'],22.67)
            self.assertIsNone(row['prediction'])
            self.assertIsNone(row['forecast_date'])
            self.assertEqual(row['available_days'],90)
            self.assertIsNone(row['rainfall_mm'])
            self.assertEqual(feed.history('11110')['history'][-2]['rainfall_mm'],2.5)

    def test_failed_refresh_retains_last_success_and_records_source_failure(self):
        class Failing(Client):
            def seoul_page(self,*args):raise SourceError('seoul: HTTP 503')
        with tempfile.TemporaryDirectory() as root:
            feed=ApiObservationFeed(root,Client());old=feed.refresh()
            feed.client=Failing();new=feed.refresh()
            self.assertEqual(new['water'],old['water'])
            self.assertEqual(new['water_collected_at'],old['water_collected_at'])
            self.assertIn('seoul',new['errors'])

    def test_incomplete_pages_do_not_replace_last_success(self):
        class Partial(Client):
            def seoul_page(self,*args):
                data,rows,total=super().seoul_page(*args)
                return data,rows,2000
        with tempfile.TemporaryDirectory() as root:
            feed=ApiObservationFeed(root,Partial());state=feed.refresh()
            self.assertNotIn('water',state)
            self.assertIn('페이지 건수 불일치',state['errors']['seoul'])

    def test_unordered_dates_do_not_create_a_false_complete_window(self):
        class Unordered(Client):
            def seoul_page(self,*args):
                data,rows,total=super().seoul_page(*args)
                rows[2],rows[3]=rows[3],rows[2]
                return data,rows,total
        with tempfile.TemporaryDirectory() as root:
            state=ApiObservationFeed(root,Unordered()).refresh()
            self.assertNotIn('water',state)
            self.assertIn('날짜 정렬',state['errors']['seoul'])
