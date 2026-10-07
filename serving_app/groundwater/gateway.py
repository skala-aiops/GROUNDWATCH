"""학습된 구별 후보 모델을 기존 웹 API의 ModelGateway 계약에 연결합니다."""
from collections import OrderedDict
from pathlib import Path
import json
import threading
import numpy as np
from serving_app.backend.adapter import ModelInfo, ExistingModelGateway
from serving_app.backend.core import APIError, now

DEFAULT_BUNDLE=Path('serving_app/models/groundwater/trained')


class GroundwaterGateway:
    def __init__(self, bundle=DEFAULT_BUNDLE):
        self.bundle=Path(bundle)
        self.manifest=json.loads((self.bundle/'manifest.json').read_text(encoding='utf-8'))
        self.stations={station['well_id']:station for station in self.manifest['stations']}
        self.cache=OrderedDict()
        self.lock=threading.RLock()
        self.fallback=ExistingModelGateway()

    def active_model(self, well_id):
        if well_id not in self.stations:
            return self.fallback.active_model(well_id)
        s=self.stations[well_id]
        return ModelInfo(s['model_id'],well_id,s['registry_name'],s['registry_version'],s['feature_contract'],s['training_end_date'],s['evaluation_end_date'])

    def report(self, well_id):
        station=self.stations.get(well_id)
        if not station:return None
        return {key:value for key,value in station.items() if key not in {'scaler','rows_file','operational_file'}} | {'unit':self.manifest['unit'],'selection':self.manifest['selection']}

    def bootstrap(self, service):
        """Register each well and its original contiguous measured segment once."""
        for well_id,s in self.stations.items():
            with service.db.connect() as db:
                db.execute('INSERT OR IGNORE INTO well VALUES(?,?,?,?,?,?)',
                           (well_id,s['code'],s['name'],'ground_surface','Asia/Seoul',now()))
                service._model(db,self.active_model(well_id))
            raw=(self.bundle.parent/'prepared'/s['operational_file']).read_bytes()
            service.upload(well_id,raw,s['district']+'_'+s['station']+'_실측.csv','measured',None,None)

    def predict(self, model, sequence):
        if self.active_model(model.well_id)!=model:
            raise APIError(409,'MODEL_CHANGED','관측소 모델 버전이 변경되었습니다.')
        if len(sequence)!=20:
            raise APIError(422,'INSUFFICIENT_HISTORY','20일의 연속 자료가 필요합니다.')
        from datetime import date, timedelta
        days=[date.fromisoformat(r['observed_date']) for r in sequence]
        if any(b-a!=timedelta(days=1) for a,b in zip(days,days[1:])):
            raise APIError(422,'INVALID_DATA','모델 입력 날짜가 연속되지 않습니다.')
        station=self.stations[model.well_id]
        values=np.asarray([[r['groundwater_depth_cm'],r['rainfall_mm']*10] for r in sequence],dtype=float)
        scaler=station['scaler']
        x=((values-np.asarray(scaler['mean']))/np.asarray(scaler['scale'])).astype(np.float32)[None,:,:]
        with self.lock:
            if model.id not in self.cache:
                from tensorflow import keras
                import tensorflow as tf
                loaded=keras.models.load_model(self.bundle/station['code']/'model.keras',compile=False)
                infer=tf.function(lambda inputs: loaded(inputs,training=False),input_signature=[tf.TensorSpec([None,20,2],tf.float32)],autograph=False)
                self.cache[model.id]=(loaded,infer)
                if len(self.cache)>4:self.cache.popitem(last=False)
            self.cache.move_to_end(model.id)
            delta=float(self.cache[model.id][1](x).numpy()[0][0])
        return float(values[-1,0]+delta*scaler['scale'][0])

    def retrain(self, model, rows, policy, emit):
        raise APIError(503,'RETRAIN_NOT_READY','현재 모델은 실측 자료로 평가한 연구용 후보입니다. 자동 재학습·운영 승격 정책은 아직 설정하지 않았습니다.')


def default_gateway():
    from .seed import ensure_bundle
    ensure_bundle()
    return GroundwaterGateway() if (DEFAULT_BUNDLE/'manifest.json').is_file() else ExistingModelGateway()
