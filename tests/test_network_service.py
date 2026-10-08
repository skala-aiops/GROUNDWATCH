import unittest
from types import SimpleNamespace
from unittest.mock import patch
from serving_app.network_service import NetworkService


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.legacy = SimpleNamespace(
            forecasts=lambda **kw: {'forecasts': [{'district_code':'11110','district_name':'종로구',
                'station_id':'S1','observed_date':'2026-01-02','prediction':1.,'model_version':'v1'}],
                'as_of':kw.get('as_of') or '2026-01-03'},
            history=lambda *a, **kw: {'history':[{'date':'2026-01-02','groundwater_level':1.}]},
            pipeline=lambda *a, **kw: {'stages':{'serve':{'status':'ready'}},'namespace':'original'})
        self.registry=[]
        self.national=SimpleNamespace(repo=SimpleNamespace(
            list_stations=lambda **kw: {'items':self.registry,'next_cursor':None},
            observations=lambda *a,**kw: [{'date':'2026-01-02','groundwater_level':2.,'rainfall_mm':1.}],
            readiness=lambda *a: {'data_ready':True}, rainy_periods=lambda **kw: []),
            manager=SimpleNamespace(list_models=lambda *a: []), forecasts=lambda *a: [],
            pipeline=lambda *a: {'models':[],'jobs':[]})
        self.artifacts={
            'national_stations_gims.json': {'accepted':[{'source_station_id':'1','name':'관측소',
                'region_code':'경기도','verified':False,'latitude':37.}]},
            'national_groundwater_samples.json': {'stations':[{'source_station_id':'1','name':'샘플',
                'unit':'el.m','observations':[{'date':'2026-01-02','groundwater_level':2.},
                                            {'date':'2026-01-04','groundwater_level':3.}]}]},
            'national_training_readiness.json': {'stations':[]}}
        self.patch=patch('serving_app.network_service._read',side_effect=lambda n,d:self.artifacts.get(n,d))
        self.patch.start();self.addCleanup(self.patch.stop)
        self.service=NetworkService(self.legacy,self.national)

    def test_deduplicates_catalog_sample_and_preserves_legacy(self):
        result=self.service.stations()
        self.assertEqual(result['total_count'],2)
        self.assertEqual(result['ready_count'],1)
        sample=result['stations'][1]
        self.assertEqual(sample['station_id'],'kwater:1')
        self.assertNotIn('observations',sample)
        self.assertFalse(sample['capabilities']['train'])
        self.assertTrue(sample['capabilities']['history'])
        self.assertEqual(sample['observed_date'],'2026-01-02')
        self.assertEqual(self.service.pipeline('seoul:S1')['namespace'],'original')

    def test_history_cutoff_and_unapproved_weather(self):
        result=self.service.history('kwater:1',mode='historical_replay',as_of='2026-01-03')
        self.assertEqual(len(result['history']),1)
        self.assertIsNone(result['history'][0]['rainfall_mm'])
        self.assertIsNone(result['weather_context']['rainy_period'])
        self.assertEqual(result['weather_context']['mapping_status'],'unapproved')

    def test_seoul_rainy_context_preserves_original_rain_input(self):
        self.legacy.history=lambda *a, **kw: {'history':[{'date':'2024-07-01','groundwater_level':-2.,'rainfall_mm':7.}]}
        self.national.repo.rainy_periods=lambda **kw: [{'region_code':kw['region_code'],'year':2024}]
        result=self.service.history('seoul:S1')
        self.assertEqual(result['history'][0]['rainfall_mm'],7.)
        self.assertEqual(result['weather_context']['rainy_period'][0]['region_code'],'kma_asos:108')
        self.assertEqual(result['weather_context']['rainy_period_usage'],'evaluation_only')
        self.assertIsNone(result['weather_context']['source_station_id'])

    def test_seoul_rainy_context_uses_preserved_csv_when_not_imported(self):
        result=self.service.history('seoul:S1')
        periods=result['weather_context']['rainy_period']
        self.assertTrue(periods)
        self.assertTrue(all(p['region_code']=='kma_asos:108' for p in periods))
        self.assertTrue(all(p['source_sha256'] for p in periods))
        self.assertIsNone(result['history'][0]['rainfall_mm'])

    def test_registered_experiment_links_without_operational_approval(self):
        self.registry.append({'station_id':'experiment-1','source_station_id':'1','region_code':'경기도',
            'verified':False,'source_contract_verified':True,'mapping_status':'experimental',
            'operational_approved':False,'level_unit':'m','level_reference':'elevation'})
        item=self.service.stations(region_code='경기도')['stations'][0]
        self.assertEqual(item['operation_station_id'],'experiment-1')
        self.assertTrue(item['capabilities']['train_experimental'])
        self.assertFalse(item['capabilities']['train'])
        self.assertFalse(item['training_approved'])

    def test_unknown_station_not_fallback(self):
        with self.assertRaises(KeyError): self.service.history('kwater:missing')

    def test_router_contract(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from serving_app.network_api import router_for
        app=FastAPI();app.include_router(router_for(self.service))
        with TestClient(app) as client:
            response=client.get('/api/v2/network/stations',params={'region_code':'경기도'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['total_count'],1)
            response=client.get('/api/v2/network/stations/kwater:1/history')
            self.assertEqual(response.status_code,200)
            self.assertIsNone(response.json()['history'][0]['rainfall_mm'])

    def test_verified_rainy_source_is_evaluation_only(self):
        self.registry.append({'station_id':'experiment-1','source_station_id':'1','region_code':'경기도',
            'verified':False,'source_contract_verified':True,'mapping_status':'experimental',
            'operational_approved':False,'weather_source_station_id':'203','rainy_region':'kma_asos:203',
            'level_unit':'m','level_reference':'elevation'})
        self.national.repo.rainy_periods=lambda **kw: [{'year':2025,'start_date':'2025-06-19','end_date':'2025-07-20'}]
        result=self.service.history('kwater:1')
        self.assertEqual(result['weather_context']['source_station_id'],'203')
        self.assertEqual(result['weather_context']['rainy_period_usage'],'evaluation_only')
        self.assertEqual(result['weather_context']['rainy_period'][0]['year'],2025)
        self.assertFalse(result['weather_context']['operational_approved'])

    def _experimental_window(self):
        from datetime import date,timedelta
        self.registry.append({'station_id':'experiment-1','source_station_id':'1','region_code':'경기도',
            'verified':False,'source_contract_verified':True,'mapping_status':'experimental',
            'operational_approved':False,'level_unit':'m','level_reference':'elevation'})
        rows=[{'date':(date(2025,12,14)+timedelta(days=i)).isoformat(),
               'groundwater_level':float(i), 'rainfall_mm':1.,'quality_status':'valid',
               'level_unit':'m','level_reference':'elevation'} for i in range(20)]
        self.national.repo.observations=lambda *a,**kw: rows
        return rows

    def test_baseline_is_not_ready_model_or_issued_prediction(self):
        self._experimental_window()
        result=self.service.stations(region_code='경기도')
        item=result['stations'][0]
        self.assertEqual(item['prediction'],19.)
        self.assertEqual(item['forecast_date'],'2026-01-03')
        self.assertEqual(item['prediction_method'],'persistence')
        self.assertEqual(item['prediction_input_end_date'],'2026-01-02')
        self.assertIsNone(item['prediction_issued_at'])
        self.assertIsNone(item['forecast_timing'])
        self.assertEqual(item['horizon_days'],1)
        self.assertEqual(item['prediction_scope'],'experimental')
        self.assertIsNone(item['model_version'])
        self.assertFalse(item['model_ready'])
        self.assertEqual(item['model_status'],'not_ready')
        self.assertEqual(result['ready_count'],0)
        self.assertEqual(result['prediction_available_count'],1)
        self.assertEqual(result['fallback_count'],1)
        self.assertFalse(item['capabilities']['predict'])

    def test_baseline_requires_continuity_validity_and_source_contract(self):
        rows=self._experimental_window()
        rows[-3]['date']='2025-12-28'
        self.assertIsNone(self.service.stations(region_code='경기도')['stations'][0]['prediction'])
        rows[-3]['date']='2025-12-31';rows[-1]['quality_status']='invalid'
        self.assertIsNone(self.service.stations(region_code='경기도')['stations'][0]['prediction'])
        rows[-1]['quality_status']='valid';self.registry[0]['source_contract_verified']=False
        self.assertIsNone(self.service.stations(region_code='경기도')['stations'][0]['prediction'])

    def test_active_model_archived_prediction_wins_over_baseline(self):
        self._experimental_window()
        self.national.manager.list_models=lambda *a:[{'version':'v2','active':True}]
        self.national.forecasts=lambda *a:[{'model_version':'v2','prediction':18.,'target_date':'2026-01-03','input_end_date':'2026-01-02','issued_at':'2026-01-03T11:30:00+09:00','forecast_timing':'same_day_estimate','horizon_days':1}]
        item=self.service.stations(region_code='경기도')['stations'][0]
        self.assertEqual(item['prediction'],18.)
        self.assertEqual(item['prediction_method'],'lstm')
        self.assertEqual(item['prediction_input_end_date'],'2026-01-02')
        self.assertEqual(item['prediction_issued_at'],'2026-01-03T11:30:00+09:00')
        self.assertEqual(item['forecast_timing'],'same_day_estimate')
        self.assertEqual(item['horizon_days'],1)
        self.assertEqual(item['model_version'],'v2')
        self.assertTrue(item['model_ready'])

    def test_simulation_is_separate_station_and_preserves_origin(self):
        self.registry.append({'station_id':'sim-gims-1','source_station_id':'sim-1',
            'region_code':'경기도','verified':False,'source_kind':'synthetic',
            'namespace':'national_synthetic_v1','source_contract_verified':True,
            'mapping_status':'synthetic','operational_approved':False,
            'level_unit':'m','level_reference':'simulation_relative_datum'})
        self.national.repo.observations=lambda *a,**kw: [{'date':'2026-01-02',
            'groundwater_level':2.,'rainfall_mm':1.,'source_kind':'synthetic'}]
        items=self.service.stations()['stations']
        simulated=next(s for s in items if s['station_id']=='sim-gims-1')
        self.assertEqual(simulated['provider'],'groundwatch_simulation')
        self.assertFalse(simulated['training_approved'])
        self.assertTrue(simulated['capabilities']['train_experimental'])
        self.assertEqual(self.service.history('sim-gims-1')['history'][0]['origin'],'synthetic')
        self.assertTrue(any(s['station_id']=='kwater:1' for s in items))
