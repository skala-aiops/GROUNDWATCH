"""Regressions for defects found by independent requirement/operations audit."""
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from fastapi.testclient import TestClient
from data.groundwater import load_canonical
from serving_app.main import create_app
from serving_app.groundwater_service import GroundwaterService, today
from tests.test_groundwater_service import FakeManager, upload_fixture, FIRST, START


class ReauditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.managers = {}
        self.service = GroundwaterService(self.tmp.name,lambda ns:self.managers.setdefault(ns,FakeManager()))

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_upload_is_idempotent_and_never_demotes_ready_data(self):
        dataset = upload_fixture(self.service)
        old = self.service.store.get('dataset',dataset)
        result = self.service.queue_upload(Path(old['path']).read_bytes(),Path(old['manifest_path']).read_bytes())
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['dataset_id'],dataset)
        self.assertEqual(len(self.service.store.jobs()),1)
        self.assertEqual(self.service.store.get('dataset',dataset),old)

    def test_partial_replay_is_not_ready_and_cannot_advance(self):
        dataset = upload_fixture(self.service)
        replay = self.service.create_replay(dataset,str(START+timedelta(days=320)))
        manager = self.service.manager(replay['id'])
        original = manager.train
        manager.train = lambda code,*a,**kw: original(code,*a,**kw) if code==FIRST else {'status':'rejected'}
        self.service.execute_one()
        actual = self.service.store.get('replay',replay['id'])
        self.assertEqual(actual['status'],'partial')
        self.assertEqual(actual['ready_count'],1)
        self.assertEqual(self.service.store.job(replay['job_id'])['status'],'failed')
        with self.assertRaises(ValueError):
            self.service.advance_job(replay['id'])

    def test_day_crash_retry_does_not_count_same_target_or_alert_twice(self):
        dataset = upload_fixture(self.service)
        replay = self.service.create_replay(dataset,str(START+timedelta(days=320)))
        self.service.execute_one()
        replay = self.service.store.get('replay',replay['id'])
        for _ in range(21):
            self.service.advance_day(replay)
        original = self.service.monitor
        def crash_after_first(session,code,rows,as_of):
            if code != FIRST:
                raise RuntimeError('injected process failure after first district commit')
            return original(session,code,rows,as_of)
        self.service.monitor = crash_after_first
        with self.assertRaises(RuntimeError):
            self.service.advance_day(replay)
        state_id = replay['id']+':'+FIRST
        committed = copy.deepcopy(self.service.store.get('monitor',state_id))
        quality_count = len([e for e in self.service.store.list('event') if e['kind']=='quality'])
        self.service.monitor = original
        self.service.advance_day(replay)
        self.assertEqual(self.service.store.get('monitor',state_id),committed)
        self.assertEqual(len([e for e in self.service.store.list('event') if e['kind']=='quality']),quality_count)
        self.assertEqual(quality_count,1)
        self.assertEqual(len([j for j in self.service.store.jobs() if j['kind']=='fine_tune']),1)

    def test_history_filters_other_dataset_and_preserves_all_prediction_versions(self):
        dataset = upload_fixture(self.service)
        manager = self.service.manager()
        manager.train(FIRST,self.service.records(dataset,FIRST),{},100)
        anchor = str(START+timedelta(days=350))
        self.service.forecasts(as_of=anchor,dataset_id=dataset)
        manager.models[FIRST]['model_version']='2'
        response = self.service.forecasts(as_of=anchor,dataset_id=dataset)
        value = next(r for r in response['forecasts'] if r['district_code']==FIRST)
        self.service.store.forecast('historical',{**value,'source_dataset_id':'wrong-dataset','prediction':99999})
        history = self.service.history(FIRST,dataset_id=dataset)
        selected = next(r for r in history['history'] if r['date']==value['forecast_date'])
        self.assertEqual({p['model_version'] for p in selected['predictions']},{'1','2'})
        self.assertNotEqual(selected['prediction'],99999)
        self.assertEqual(selected['prediction_model_version'],'2')

    def test_current_mode_rejects_past_override_and_reports_stale_data(self):
        dataset = upload_fixture(self.service)
        with self.assertRaises(ValueError):
            self.service.forecasts(as_of='2020-12-01',mode='current')
        result = self.service.forecasts(mode='current')
        self.assertEqual(result['as_of'],today().isoformat())
        self.assertEqual(result['ready_count'],0)
        self.assertEqual({r['quality_status'] for r in result['forecasts']},{'STALE_DATA'})

    def test_manifest_file_fingerprint_is_enforced(self):
        dataset = upload_fixture(self.service)
        entry = self.service.store.get('dataset',dataset)
        manifest = json.loads(Path(entry['manifest_path']).read_text())
        manifest['canonical_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'canonical_sha256'):
            load_canonical(entry['path'],manifest)
        manifest['canonical_sha256']=hashlib.sha256(Path(entry['path']).read_bytes()).hexdigest()
        self.assertTrue(load_canonical(entry['path'],manifest).records)
        manifest['source_kind']='not-a-source'
        with self.assertRaisesRegex(ValueError,'source_kind'):
            load_canonical(entry['path'],manifest)

    def test_request_metrics_are_real_persisted_status_latency_and_alerts(self):
        with TestClient(create_app(self.service)) as client:
            for _ in range(20):
                response = client.get('/api/v1/districts')
                self.assertEqual(response.status_code,200)
                self.assertTrue(response.headers['x-request-id'])
            client.get('/api/v1/forecasts?as_of=invalid')
            metrics = client.get('/metrics/summary').json()
            self.assertEqual(metrics['count'],21)
            self.assertEqual(metrics['http_4xx_count'],1)
            self.assertEqual(metrics['http_5xx_count'],0)
            self.assertTrue(metrics['sufficient_samples'])
            self.assertGreaterEqual(metrics['p95_seconds'],0)
            self.service.store.request_metric('GET','/injected-error',500,1.5,'test-error')
            self.service.evaluate_service_health()
            self.service.evaluate_service_health()
            events = [e for e in self.service.store.list('event') if e['kind']=='service']
            self.assertEqual(len(events),1)
            self.assertEqual(events[0]['summary']['http_5xx_count'],1)


class MonitoringFailureTests(unittest.TestCase):
    def test_conflicting_model_job_does_not_start_cooldown(self):
        from serving_app.groundwater_store import Store
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'meta.sqlite3')
            scope='model:replay:11110'
            store.enqueue('rollback',{},scope)
            state={'district_code':'11110','last_processed_target_date':'2024-01-01','last_trigger':'2024-01-01'}
            store.commit_monitor('replay:11110',state,{'kind':'quality','namespace':'replay','district_code':'11110','message':'requested'},('fine_tune',{},scope))
            self.assertIsNone(store.get('monitor','replay:11110')['last_trigger'])
            self.assertEqual(len(store.jobs()),1)
            self.assertEqual(store.list('event'),[])

    def test_metric_failure_does_not_break_successful_response(self):
        with tempfile.TemporaryDirectory() as folder:
            service=GroundwaterService(folder,lambda ns:FakeManager())
            def fail(*args):raise RuntimeError('metrics only failure')
            service.store.request_metric=fail
            with TestClient(create_app(service)) as client:
                response=client.get('/api/v1/districts')
            self.assertEqual(response.status_code,200)
            self.assertEqual(len(response.json()['districts']),25)


class PipelineViewTests(unittest.TestCase):
    def test_pipeline_reports_evidence_and_default_station_without_inventing_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            managers={}
            service=GroundwaterService(folder,lambda ns:managers.setdefault(ns,FakeManager()))
            with TestClient(create_app(service)) as client:
                empty=client.get('/api/v1/pipeline').json()
                self.assertEqual(empty['district_code'],'11110')
                self.assertTrue(all(s['status']=='pending' for s in empty['stages']))
                self.assertEqual(client.get('/api/v1/pipeline?district_code=99999').status_code,422)
                dataset=upload_fixture(service)
                replay=service.create_replay(dataset,str(START+timedelta(days=320)),str(START+timedelta(days=409)))
                service.execute_one()
                endpoint='/api/v1/pipeline?replay_id='+replay['id']
                initialized=client.get(endpoint).json()
                self.assertEqual(initialized['replay_status'],'ready')
                self.assertEqual(initialized['remaining_days'],89)
                self.assertEqual(initialized['stages'][-1]['status'],'pending')
                client.get('/api/v1/forecasts?replay_id='+replay['id'])
                served=client.get(endpoint).json()
                self.assertEqual(served['stages'][-1]['status'],'completed')
                self.assertEqual(served['stages'][2]['status'],'pending')
                self.assertEqual(served['stages'][5]['status'],'pending')
                self.assertEqual(served['defaults']['shift_amount'],.2)
                self.assertEqual(served['defaults']['shift_start'],str(date.fromisoformat(served['defaults']['start_date'])+timedelta(days=22)))
                advance=service.advance_job(replay['id'],2)
                active=client.get(endpoint).json()
                self.assertTrue(active['advance_active'])
                self.assertEqual(active['active_jobs'][0]['id'],advance['id'])
                service.store.progress(advance['id'],{'processed':1,'total':2})
                self.assertEqual(client.get(endpoint).json()['latest_advance_job']['result']['processed'],1)
                service.store.finish(advance['id'],error='worker failed')
                failed=client.get(endpoint).json()
                self.assertFalse(failed['advance_active'])
                self.assertEqual(failed['replay_status'],'ready')
                self.assertEqual(failed['latest_advance_job']['error'],'worker failed')

    def test_namespace_jobs_are_filtered_before_limit(self):
        from serving_app.groundwater_store import Store
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'meta.sqlite3')
            first=store.enqueue('advance',{'replay_id':'first'},'replay:first')
            store.finish(first['id'],result={})
            for i in range(101):
                job=store.enqueue('advance',{'replay_id':'other'},'replay:other')
                store.finish(job['id'],result={})
            self.assertEqual(store.jobs('first')[0]['id'],first['id'])


class PipelineCycleTests(unittest.TestCase):
    def test_shift_source_and_current_candidate_do_not_inherit_past_success(self):
        with tempfile.TemporaryDirectory() as folder:
            managers={}
            service=GroundwaterService(folder,lambda ns:managers.setdefault(ns,FakeManager()))
            dataset=upload_fixture(service)
            replay=service.create_replay(dataset,str(START+timedelta(days=320)),str(START+timedelta(days=409)),scenario='level_shift',shift_start=str(START+timedelta(days=344)),shift_amount=.2)
            service.execute_one()
            manager=service.manager(replay['id']);original=manager.list_models
            manager.list_models=lambda:[dict(m,model_version='2',history=[{'from':'1','to':'2'}]) for m in original()]
            service.store.event(FIRST,'model','후보 평가: promoted',replay['id'],result={'status':'promoted','candidate_version':'2'})
            service.store.enqueue('fine_tune',{'replay_id':replay['id'],'district_code':FIRST},'model:'+replay['id']+':'+FIRST)
            service.store.put('monitor',{'district_code':FIRST,'candidate':'3','candidate_as_of':replay['as_of']},replay['id']+':'+FIRST)
            actual=service.pipeline(FIRST,replay['id'])
            self.assertEqual(actual['source_kind'],'synthetic')
            self.assertFalse(actual['drift_demo']['applied'])
            self.assertEqual(actual['drift_demo']['shift_start'],replay['shift_start'])
            original_rows=service.records(dataset,FIRST)
            shifted_rows=service.records(dataset,FIRST,replay)
            self.assertAlmostEqual(shifted_rows[344]['groundwater_level']-original_rows[344]['groundwater_level'],.2)
            self.assertEqual(shifted_rows[343]['groundwater_level'],original_rows[343]['groundwater_level'])
            self.assertNotIn('drift_demo',original_rows[344])
            self.assertEqual(actual['stages'][4]['status'],'pending')
            self.assertEqual(actual['stages'][5]['status'],'pending')
            self.assertIn('v3',actual['stages'][4]['detail'])


class MeanLatencyTests(unittest.TestCase):
    def test_mean_is_distinct_from_p95_and_persists_across_store_reopen(self):
        from serving_app.groundwater_store import Store
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'metrics.sqlite3'
            store=Store(path)
            self.assertIsNone(store.metric_summary()['mean_seconds'])
            for i,(status,latency) in enumerate([(200,.1),(422,.3),(500,2.0)]):
                store.request_metric('GET','/measured',status,latency,str(i))
            measured=Store(path).metric_summary(300)
            self.assertAlmostEqual(measured['mean_seconds'],.8)
            self.assertEqual(measured['p95_seconds'],2.0)
            self.assertAlmostEqual(measured['error_rate'],1/3)
            self.assertEqual(measured['http_4xx_count'],1)
