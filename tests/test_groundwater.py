import copy
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

from serving_app.groundwater.prepare import prepare, window_indices
from serving_app.groundwater.training import temporal_split, make_arrays, fit_scaler
from serving_app.groundwater.seed import ensure_bundle


def rows(count=200):
    return [{'observed_date':(date(2024,1,1)+timedelta(days=i)).isoformat(),
             'groundwater_depth_cm':100+i, 'rainfall_mm':i%3/10} for i in range(count)]


class GroundwaterTests(unittest.TestCase):
    def test_windows_never_bridge_missing_dates(self):
        data=rows(70);del data[30]
        indices=window_indices(data)
        self.assertEqual(len(indices),29)
        for i in indices:
            self.assertEqual(date.fromisoformat(data[i]['observed_date'])-date.fromisoformat(data[i-20]['observed_date']),timedelta(days=20))

    def test_split_and_scaler_exclude_future_answers(self):
        data=rows();train,val,test=temporal_split(data,window_indices(data),data[-1]['observed_date'])
        self.assertLess(train[-1],val[0]);self.assertLess(val[-1],test[0])
        self.assertGreaterEqual(len(test),21)
        scaler=fit_scaler(data,train[-1]);changed=copy.deepcopy(data)
        for row in changed[train[-1]+1:]:row['groundwater_depth_cm']=999999
        self.assertEqual(scaler,fit_scaler(changed,train[-1]))
        x,y,actual,previous=make_arrays(data,[test[0]],scaler)
        self.assertEqual(x.shape,(1,20,2))
        self.assertAlmostEqual(float(y[0])*scaler['scale'][0]+previous[0],actual[0],places=5)
        changed=copy.deepcopy(data);changed[test[0]]['groundwater_depth_cm']=888888
        future_x,_,_,_=make_arrays(changed,[test[0]],scaler)
        np.testing.assert_array_equal(x,future_x)

    def test_selection_units_duplicates_and_conflicts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'input.csv'
            fields=['구','관측소 이름','관측일자','지하수위','일일강수량']
            records=[]
            for district in ('가구','나구'):
                for station in ('유효관측소','관측종료관측소'):
                    for i in range(200):records.append([district,station,(date(2024,1,1)+timedelta(days=i)).strftime('%Y%m%d'),'1.25','0.1'])
            records.append(records[0].copy())
            conflict=records[70].copy();conflict[3]='9';records.append(conflict)
            records[90][3]='0'
            with source.open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(fields);writer.writerows(records)
            result=prepare(source,root/'out')
            self.assertEqual(len(result['selected']),2)
            self.assertTrue(all(s['station']=='유효관측소' for s in result['selected']))
            self.assertEqual(result['counts']['conflicting_station_dates'],1)
            self.assertEqual(result['counts']['duplicate_rows'],2)
            self.assertEqual(result['counts']['nonpositive_station_dates'],1)
            selected=json.loads((root/'out'/result['selected'][0]['rows_file']).read_text())
            self.assertEqual(selected[0]['groundwater_depth_cm'],125)
            self.assertEqual(selected[0]['rainfall_mm'],.1)
            days={r['observed_date'] for r in selected}
            self.assertNotIn((date(2024,1,1)+timedelta(days=70)).isoformat(),days)
            self.assertNotIn((date(2024,1,1)+timedelta(days=90)).isoformat(),days)

    def test_missing_seed_keeps_existing_baseline_available(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            ensure_bundle(root/'models',root/'missing.zip')
            self.assertFalse((root/'models').exists())

    def test_seed_restores_once_without_overwriting_models(self):
        seed=Path('data/groundwater/bundle.zip')
        if not seed.exists():self.skipTest('로컬 학습 결과 묶음 미제공')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'models'
            ensure_bundle(root,seed)
            manifest=root/'trained/manifest.json';saved=manifest.read_bytes()
            self.assertEqual(len(json.loads(saved)['stations']),25)
            ensure_bundle(root,seed)
            self.assertEqual(manifest.read_bytes(),saved)


if __name__=='__main__':unittest.main()
