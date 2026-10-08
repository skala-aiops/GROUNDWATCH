import copy
import tempfile
import unittest
from datetime import date, timedelta
from backend.api_feed_models import ApiModelManager, water_windows, input_hash, prepare
from backend.api_observation_feed import ApiObservationFeed


class Backend:
    def __init__(self, offset=0):
        self.models={};self.aliases={};self.offset=offset;self.inputs=None
    def train(self,x,y,validation,**kwargs):
        self.inputs=copy.deepcopy(x)
        return self.offset
    def predict(self,model,inputs):return [r[-1][0]+model for r in inputs]
    def register(self,name,model,bundle,directory):
        self.models[name]=(model,copy.deepcopy(bundle));return '1'
    def load(self,name,version):return copy.deepcopy(self.models[name])
    def alias(self,name):return self.aliases.get(name)
    def set_alias(self,name,version):self.aliases[name]=version


def observations():
    return [{'date':(date(2026,1,1)+timedelta(days=i)).isoformat(),
             'groundwater_level':20+i*.01,'rainfall_mm':None if i%2 else float(i%5),
             'prediction':None,'predictions':[],'source_kind':'observed_api'} for i in range(90)]


class ActualModelTests(unittest.TestCase):
    def test_mask_train_only_statistics_temporal_evaluation_and_native_forecast(self):
        with tempfile.TemporaryDirectory() as root:
            backend=Backend();manager=ApiModelManager(root,backend)
            rows=observations();original=input_hash(rows)
            # Extreme held-out rain cannot affect the training fill value/scaler.
            rows[-10]['rainfall_mm']=99999
            result=manager.train_actual('11110','well-1',rows)
            self.assertEqual(result['status'],'promoted')
            bundle=backend.models[manager._name('11110')][1]
            self.assertLess(bundle['rain_fill_value'],5)
            self.assertLess(bundle['scaler']['maximum'][1],5)
            self.assertLess(result['splits']['train']['end'],result['splits']['validation']['start'])
            self.assertLess(result['splits']['validation']['end'],result['splits']['test']['start'])
            self.assertEqual(len(backend.inputs[0][0]),3)
            self.assertEqual(backend.inputs[0][1][2],1)
            forecast=manager.forecast_actual('11110','well-1',rows)
            self.assertEqual(forecast['forecast_date'],'2026-04-01')
            self.assertEqual(forecast['imputed_rain_days'],10)
            self.assertAlmostEqual(forecast['prediction'],rows[-1]['groundwater_level'])
            self.assertNotEqual(original,input_hash(rows))
            self.assertIsNone(rows[1]['rainfall_mm'])
            with self.assertRaisesRegex(ValueError,'contract mismatch'):
                manager.forecast_actual('11110','other-well',rows)

    def test_gaps_are_not_bridged_and_insufficient_real_labels_are_rejected(self):
        rows=observations();del rows[40]
        windows=water_windows(rows)
        self.assertTrue(all((date.fromisoformat(w[-1]['date'])-date.fromisoformat(w[0]['date'])).days==20 for w in windows))
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError,'50 real target'):
                ApiModelManager(root,Backend()).train_actual('11110','well',rows[:60])

    def test_quality_gate_does_not_serve_a_bad_model(self):
        with tempfile.TemporaryDirectory() as root:
            manager=ApiModelManager(root,Backend(offset=100))
            result=manager.train_actual('11110','well',observations())
            self.assertEqual(result['status'],'rejected')
            self.assertIsNone(manager.current_version('11110'))

    def test_missing_rain_and_observed_zero_have_different_masks(self):
        rows=observations();rows[0]['rainfall_mm']=0
        filled=prepare(rows[:2],2.5)
        self.assertEqual(filled[0]['rain_missing'],0)
        self.assertEqual(filled[1]['rain_missing'],1)
        self.assertEqual(filled[1]['rainfall_mm'],2.5)
        self.assertIsNone(rows[1]['rainfall_mm'])
