"""Isolated deterministic fixtures, never evidence of real API forecast accuracy."""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from serving_app.groundwater_service import GroundwaterService, today
from serving_app.groundwater_models import ModelManager
from serving_app.live_observations import LiveObservations
from tests.test_groundwater_models import Backend


class LiveTests(unittest.TestCase):
    def test_verified_fixture_snapshot_train_daily_issue_and_legacy_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);backends={}
            def factory(namespace):
                return ModelManager(root/'models',namespace=namespace,backend=backends.setdefault(namespace,Backend()))
            service=GroundwaterService(root,manager_factory=factory);live=LiveObservations(service)
            mapping={'version':'FIXTURE-v1','station_id':'fixture-well','district_code':'11110','station_name':'TEST ONLY',
                'seoul_name':'TEST ONLY','weather_station':'108','level_unit':'gl.-m',
                'preprocessing_version':'strict-v1','approved':True,'evidence':['ISOLATED TEST FIXTURE']}
            live.repo.register_mapping(mapping)
            end=today()-timedelta(days=1);start=end-timedelta(days=409)
            for source,station in [('seoul','TEST ONLY'),('kma','108')]:
                records=[{'source':source,'source_station':station,'date':(start+timedelta(days=i)).isoformat(),
                          'value':-20+i*.01 if source=='seoul' else 0} for i in range(410)]
                live.repo.record_collection('fixture',source,station,start.isoformat(),end.isoformat(),
                    {'status':'collected'},records,[],['fixture-hash'])
            snapshot=live.repo.publish_snapshot('fixture-well','FIXTURE-v1',start.isoformat(),end.isoformat())
            result=live.execute_job({'kind':'train_live','payload':{'snapshot_id':snapshot['id'],
                'replay_start':(start+timedelta(days=320)).isoformat()}})
            self.assertEqual(result['status'],'promoted')
            daily=live.repo.publish_snapshot('fixture-well','FIXTURE-v1',(end-timedelta(days=19)).isoformat(),end.isoformat())
            live.repo.activate(daily['id'])
            result=live.execute_job({'kind':'predict_live','payload':{'snapshot_id':daily['id']}})
            self.assertEqual(result['training_snapshot_id'],snapshot['id'])
            self.assertEqual(result['inference_snapshot_id'],daily['id'])
            response=live.forecasts()
            self.assertEqual(response['ready_count'],1)
            self.assertEqual(response['forecasts'][0]['model_evaluation_status'],'EVALUATION_PENDING')
            version=response['forecasts'][0]['model_version']
            service.store.put('monitor',{'version':version,'rmse':2,'threshold':1},'observed_api_v1:11110')
            self.assertEqual(live.forecasts()['forecasts'][0]['model_evaluation_status'],'WARN')
            service.store.put('monitor',{'version':'unrelated','rmse':0,'threshold':1},'observed_api_v1:11110')
            self.assertEqual(live.forecasts()['forecasts'][0]['model_evaluation_status'],'EVALUATION_PENDING')
            self.assertEqual(response['forecasts'][0]['forecast_date'],today().isoformat())
            self.assertEqual(len(live.repo.predictions(today().isoformat())),1)
            from fastapi.testclient import TestClient
            from serving_app.main import create_app
            with TestClient(create_app(service)) as client:
                history=client.get('/api/v1/live/districts/11110/history')
                self.assertEqual(history.status_code,200)
                issued=history.json()['history'][-1]
                self.assertEqual(issued['date'],today().isoformat())
                self.assertIsNone(issued['groundwater_level'])
                self.assertEqual(issued['prediction'],result['prediction'])
                self.assertEqual(len(issued['predictions']),1)
                self.assertEqual(history.json()['unit'],'gl.-m')
                live.repo.record_collection('failed-correction','seoul','TEST ONLY',end.isoformat(),end.isoformat(),
                    {'status':'failed'},[{'source':'seoul','source_station':'TEST ONLY',
                    'date':end.isoformat(),'value':999}],[],['failed-hash'])
                history=client.get('/api/v1/live/districts/11110/history').json()['history']
                self.assertFalse(any(r['date']==end.isoformat() for r in history))
                self.assertEqual(history[-1]['prediction'],result['prediction'])
            live.execute_job({'kind':'predict_live','payload':{'snapshot_id':daily['id']}})
            self.assertEqual(len(live.repo.predictions(today().isoformat())),1)
            self.assertEqual(service.store.list('dataset'),[])
            self.assertEqual(service.manager('historical').list_models(),[])
            self.assertEqual(live.repo.evaluate_available(),0)

    def test_late_labels_process_every_daily_window_once(self):
        import json
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            service=GroundwaterService(tmp);live=LiveObservations(service)
            start=today()-timedelta(days=30)
            rows=[{'target_date':(start+timedelta(days=i)).isoformat(),'issued_at':'a',
                'station_id':'TEST','model_version':'1','evaluation':json.dumps({'residual':2})} for i in range(23)]
            @contextmanager
            def connect():
                yield SimpleNamespace(execute=lambda *args:SimpleNamespace(fetchall=lambda:rows))
            live.repo=SimpleNamespace(connect=connect,selected_mappings=lambda:[{'approved':True,
                'district_code':'11110','station_id':'TEST','contract_id':'contract','version':'v1'}],
                publish_snapshot=Mock(side_effect=ValueError('fixture missing retraining window')))
            manager=SimpleNamespace(list_models=lambda:[{'district_code':'11110','status':'ready',
                'model_version':'1','feature_contract_id':'contract','threshold':1}])
            service.manager=lambda namespace:manager
            live.monitor()
            state=service.store.get('monitor','observed_api_v1:11110')
            self.assertEqual(state['breaches'],3)
            self.assertEqual(state['last_processed_target_date'],rows[-1]['target_date'])
            self.assertEqual(live.repo.publish_snapshot.call_count,2)
            live.monitor()
            self.assertEqual(live.repo.publish_snapshot.call_count,2)

    def test_promotion_stops_old_champion_backlog_monitoring(self):
        import json
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            service=GroundwaterService(tmp);live=LiveObservations(service)
            start=today()-timedelta(days=30)
            rows=[{'target_date':(start+timedelta(days=i)).isoformat(),'issued_at':'a',
                'station_id':'TEST','model_version':'1','evaluation':json.dumps({'residual':2})} for i in range(23)]
            @contextmanager
            def connect():
                yield SimpleNamespace(execute=lambda *args:SimpleNamespace(fetchall=lambda:rows))
            live.repo=SimpleNamespace(connect=connect,selected_mappings=lambda:[{'approved':True,
                'district_code':'11110','station_id':'TEST','contract_id':'contract','version':'v1'}],
                publish_snapshot=Mock(return_value={'rows':[]}))
            evaluate=Mock(return_value={'status':'promoted'})
            service.manager=lambda namespace:SimpleNamespace(list_models=lambda:[{'district_code':'11110','status':'ready',
                'model_version':'1','feature_contract_id':'contract','threshold':1}],evaluate_candidate=evaluate)
            service.store.put('monitor',{'district_code':'11110','version':'1','breaches':0,'candidate':'2',
                'candidate_as_of':(start-timedelta(days=30)).isoformat(),'last_trigger':None},'observed_api_v1:11110')
            live.monitor()
            state=service.store.get('monitor','observed_api_v1:11110')
            self.assertEqual(state['last_processed_target_date'],rows[0]['target_date'])
            self.assertEqual(evaluate.call_count,1)
            self.assertEqual(service.store.jobs(),[])

    def test_unapproved_source_blocks_cycle_without_creating_training_or_predictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=GroundwaterService(tmp)
            live=LiveObservations(service)
            result=live.cycle()
            self.assertEqual(result['status'],'mapping_required')
            self.assertEqual(service.store.jobs(),[])
            self.assertEqual(live.repo.summary()['counts']['live_predictions'],0)

if __name__=='__main__':unittest.main()
