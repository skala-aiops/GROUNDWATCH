import copy
import json
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path

from serving_app.api_feed_models import ApiModelManager,NAMESPACE,input_hash
from serving_app.api_feed_ops import ApiFeedOperations
from serving_app.groundwater_service import GroundwaterService

CODE='11110'
STATION='SU-JNO-G1-0007'


class Backend:
    def __init__(self,bad=False):self.versions={};self.aliases={};self.bad=bad;self.fail_load=False
    def train(self,x,y,validation,initial=None,**kwargs):
        return {'delta':sum(target-inputs[-1][0] for inputs,target in zip(x,y))/len(y) if initial is not None else 0,
                'bad':self.bad if initial is not None else False}
    def predict(self,model,inputs):
        return [r[-1][0]+(model['delta'] if r[-1][1]>1.01 or model['bad'] else 0) for r in inputs]
    def register(self,name,model,bundle,directory):
        versions=self.versions.setdefault(name,{})
        version=str(len(versions)+1);versions[version]=(copy.deepcopy(model),copy.deepcopy(bundle));return version
    def load(self,name,version):
        if self.fail_load:raise RuntimeError('model load failed')
        return copy.deepcopy(self.versions[name][version])
    def alias(self,name):return self.aliases.get(name)
    def set_alias(self,name,version):self.aliases[name]=version


def observations(count):
    return [{'date':(date(2026,1,1)+timedelta(days=i)).isoformat(),
             'groundwater_level':20+i*.01 if i<90 else 20.89+(i-89)*.1,
             'rainfall_mm':float(i%5) if i<90 else 10.0,
             'prediction':None,'predictions':[],'source_kind':'observed_api'} for i in range(count)]


class NativeOperationsTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
        self.backend=Backend();self.manager=ApiModelManager(self.root,self.backend)
        self.service=GroundwaterService(self.root);self.ops=ApiFeedOperations(self.service,self.manager)
        self.manager.train_actual(CODE,STATION,observations(90))
    def tearDown(self):self.directory.cleanup()
    def publish(self,rows):
        forecast=self.manager.forecast_actual(CODE,STATION,rows)
        forecast['issued_at']=rows[-1]['date']+'T12:00:00+00:00'
        self.ops.record_forecast(CODE,forecast,rows)
        return forecast
    def receive(self,count):
        rows=observations(count)
        self.publish(rows[:-1])
        self.ops.evaluate_labels(CODE,rows,rows[-1]['date']+'T12:00:00+00:00')
        self.ops.monitor(CODE,STATION,rows)
        return rows
    def trigger(self):
        for count in range(91,113):self.receive(count)
        jobs=[j for j in self.service.store.jobs(NAMESPACE) if j['kind']=='retrain_api_feed']
        self.assertEqual(len(jobs),1)
        job=self.service.store.claim('retrain_api_feed')
        result=self.ops.execute_job(job);self.service.store.finish(job['id'],result)
        return result

    def test_real_issuance_only_duplicate_cycles_and_first_received_labels(self):
        rows=observations(90);forecast=self.publish(rows)
        self.assertFalse(self.ops.record_forecast(CODE,forecast,rows))
        self.assertEqual(self.ops.evaluate_labels(CODE,rows,'2027-01-01T00:00:00+00:00'),0)
        actual=observations(91)
        self.assertEqual(self.ops.evaluate_labels(CODE,actual,'2027-01-01T00:00:00+00:00'),1)
        first=self.ops.records('api_evaluation',CODE)[0]
        actual[-1]['groundwater_level']+=100
        self.assertEqual(self.ops.evaluate_labels(CODE,actual,'2027-01-02T00:00:00+00:00'),0)
        self.assertEqual(self.ops.records('api_evaluation',CODE)[0]['actual'],first['actual'])
        self.ops.monitor(CODE,STATION,actual);self.ops.monitor(CODE,STATION,actual)
        self.assertFalse(self.service.store.jobs(NAMESPACE))

    def test_full_automatic_cycle_waits_30_days_promotes_and_serves_new_version(self):
        for count in range(91,112):self.receive(count)
        self.assertFalse(self.service.store.jobs(NAMESPACE)) # 21 targets = only first breach
        rows=self.receive(112)
        self.ops.monitor(CODE,STATION,rows)
        self.assertEqual(len(self.service.store.jobs(NAMESPACE)),1)
        job=self.service.store.claim('retrain_api_feed');candidate=self.ops.execute_job(job)
        self.service.store.finish(job['id'],candidate)
        self.assertEqual(self.manager.current_version(CODE),'1')
        self.assertEqual(candidate['candidate_version'],'2')
        for count in range(113,142):self.receive(count)
        self.assertEqual(self.ops.state(CODE)['candidate_evaluation']['count'],29)
        self.assertEqual(self.manager.current_version(CODE),'1')
        self.receive(142)
        self.assertEqual(self.manager.current_version(CODE),'2')
        self.assertIsNone(self.ops.state(CODE)['candidate'])
        self.assertEqual(self.ops.state(CODE)['last_evaluation']['status'],'promoted')
        actual=observations(142)
        forecast=self.manager.forecast_actual(CODE,STATION,actual)
        self.assertEqual(forecast['model_version'],'2')
        self.assertAlmostEqual(forecast['prediction'],actual[-1]['groundwater_level']+.1,places=6)
        restored=ApiFeedOperations(GroundwaterService(self.root),ApiModelManager(self.root,self.backend))
        restored.monitor(CODE,STATION,actual)
        self.assertEqual(len([j for j in self.service.store.jobs(NAMESPACE) if j['kind']=='retrain_api_feed']),1)
        self.assertEqual(restored.pipeline(CODE)['stages'][-1]['status'],'completed')

    def test_historical_guard_rejection_keeps_serving_champion(self):
        self.backend.bad=True
        candidate=self.manager.create_candidate(CODE,observations(112),'bad-candidate')
        result=self.manager.evaluate_actual_candidate(CODE,candidate['candidate_version'],observations(142))
        self.assertEqual(result['status'],'rejected')
        self.assertFalse(result['gates']['historical_guard']['passed'])
        self.assertEqual(self.manager.current_version(CODE),'1')

    def test_missing_future_day_cannot_be_replaced_by_later_day(self):
        candidate=self.manager.create_candidate(CODE,observations(112),'calendar-gap')
        rows=observations(143);del rows[120]
        result=self.manager.evaluate_actual_candidate(CODE,candidate['candidate_version'],rows)
        self.assertEqual(result['status'],'pending')
        self.assertLess(result['count'],30)
        self.assertEqual(self.manager.current_version(CODE),'1')

    def test_failed_candidate_load_cannot_change_champion(self):
        candidate=self.manager.create_candidate(CODE,observations(112),'load-failure')
        self.backend.fail_load=True
        with self.assertRaisesRegex(RuntimeError,'load failed'):
            self.manager.evaluate_actual_candidate(CODE,candidate['candidate_version'],observations(142))
        self.assertEqual(self.manager.current_version(CODE),'1')

    def test_issuance_rejects_visible_target_and_snapshot_mismatch(self):
        rows=observations(90);forecast=self.manager.forecast_actual(CODE,STATION,rows)
        with self.assertRaisesRegex(ValueError,'already present'):
            self.ops.record_forecast(CODE,forecast,observations(91))
        forecast['inference_snapshot_id']='wrong'
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            self.ops.record_forecast(CODE,forecast,rows)

    def test_retry_candidate_job_does_not_register_second_candidate(self):
        one=self.manager.create_candidate(CODE,observations(112),'same-trigger')
        two=self.manager.create_candidate(CODE,observations(112),'same-trigger')
        self.assertEqual(one,two)
        self.assertEqual(len(self.manager._state(CODE)['versions']),2)

    def test_manual_rollback_allows_only_previous_validated_champion(self):
        self.trigger()
        for count in range(113,143):self.receive(count)
        self.assertEqual(self.manager.current_version(CODE),'2')
        self.assertEqual(self.manager.rollback(CODE)['model_version'],'1')
        with self.assertRaises(RuntimeError):self.manager.rollback(CODE,'not-validated')
