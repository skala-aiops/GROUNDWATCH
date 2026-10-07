"""시간 순서로 분리한 관측소별 LSTM. 원래 제공 모델 구조를 재사용합니다."""
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone, timedelta, date
import csv
import json
import math
import numpy as np
from .prepare import window_indices


def make_arrays(rows, indices, scaler):
    values=np.asarray([[r['groundwater_depth_cm'],r['rainfall_mm']*10] for r in rows],dtype=np.float64)
    scaled=(values-np.asarray(scaler['mean']))/np.asarray(scaler['scale'])
    x=np.asarray([scaled[i-20:i] for i in indices],dtype=np.float32)
    previous=values[np.asarray(indices)-1,0]
    actual=values[indices,0]
    # Residual target preserves the strong last-observation baseline without
    # copying the answer: the previous day is available at prediction time.
    y=((actual-previous)/scaler['scale'][0]).astype(np.float32)
    return x,y,actual,previous


def temporal_split(rows, indices, operational_end):
    n=len(indices)
    train_end=int(n*.70)
    validation_end=int(n*.85)
    latest_validation=(date.fromisoformat(operational_end)-timedelta(days=21)).isoformat()
    eligible=sum(rows[i]['observed_date']<=latest_validation for i in indices)
    validation_end=min(validation_end,eligible)
    train_end=min(train_end,validation_end-20)
    if train_end<40 or validation_end-train_end<20 or n-validation_end<21:
        raise ValueError('분리된 학습 40개·검증 20개·평가 21개 이상이 필요합니다.')
    return indices[:train_end],indices[train_end:validation_end],indices[validation_end:]


def metrics(actual,predicted):
    errors=np.asarray(actual,dtype=float)-np.asarray(predicted,dtype=float)
    return {'rmse_cm':float(np.sqrt(np.mean(errors**2))),'mae_cm':float(np.mean(np.abs(errors))),'count':len(errors)}


def fit_scaler(rows, train_last):
    values=np.asarray([[r['groundwater_depth_cm'],r['rainfall_mm']*10] for r in rows[:train_last+1]],dtype=float)
    return {'mean':values.mean(axis=0).tolist(),'scale':np.maximum(values.std(axis=0),1.0).tolist()}


def train_all(prepared,output,epochs=35,only=None):
    import mlflow
    import mlflow.tensorflow
    from mlflow.tracking import MlflowClient
    from tensorflow import keras
    import tensorflow as tf
    from serving_app.lstm_model import build_model
    from serving_app.backend.core import FEATURE_CONTRACT
    prepared,output=Path(prepared),Path(output);output.mkdir(parents=True,exist_ok=True)
    if (output/'manifest.json').exists():
        raise ValueError('저장된 모델을 덮어쓰지 않습니다. --output으로 새 학습 결과 폴더를 지정하세요.')
    preparation=json.loads((prepared/'preparation.json').read_text(encoding='utf-8'))
    mlflow.set_experiment('GroundWatch-Seoul-Station-LSTM')
    client=MlflowClient();reports=[]
    stations=preparation['selected']
    if only:stations=[s for s in stations if s['district']==only]
    for station in stations:
        keras.backend.clear_session();keras.utils.set_random_seed(42)
        rows=json.loads((prepared/station['rows_file']).read_text(encoding='utf-8'))
        indices=window_indices(rows)
        train,val,test=temporal_split(rows,indices,station['last_date'])
        train_last=train[-1]
        scaler=fit_scaler(rows,train_last)
        X,y,_,_=make_arrays(rows,train,scaler)
        vx,vy,va,vp=make_arrays(rows,val,scaler)
        tx,ty,ta,tp=make_arrays(rows,test,scaler)
        model=build_model()
        # tf.data with a bounded pool avoids creating a thread per small model.
        options=tf.data.Options();options.threading.private_threadpool_size=1
        training=tf.data.Dataset.from_tensor_slices((X,y)).batch(128).with_options(options)
        validation=tf.data.Dataset.from_tensor_slices((vx,vy)).batch(128).with_options(options)
        print('TRAIN',station['district'],station['station'],len(train),len(val),len(test),flush=True)
        history=model.fit(training,validation_data=validation,epochs=epochs,verbose=0,shuffle=False,
                          callbacks=[keras.callbacks.EarlyStopping(monitor='val_loss',patience=6,restore_best_weights=True)])
        def predict(x,previous):
            parts=[np.asarray(model(x[i:i+128],training=False)).reshape(-1) for i in range(0,len(x),128)]
            return previous+np.concatenate(parts)*scaler['scale'][0]
        validation_predictions=predict(vx,vp);test_predictions=predict(tx,tp)
        if not np.isfinite(test_predictions).all() or np.any(test_predictions<=0):
            raise ValueError(station['district']+': 유효하지 않은 모델 출력')
        val_scores=metrics(va,validation_predictions);test_scores=metrics(ta,test_predictions)
        val_baseline=metrics(va,vp);test_baseline=metrics(ta,tp)
        folder=output/station['code'];folder.mkdir(exist_ok=True)
        model.save(folder/'model.keras')
        with mlflow.start_run(run_name=station['district']+'-'+station['station']) as run:
            mlflow.log_params({'station':station['station'],'district':station['district'],'sequence_length':20,'features':'depth_cm,rainfall_mm_x10',
                               'target':'next_day_depth_delta_scaled','seed':42,'max_epochs':epochs,'epochs_run':len(history.history['loss']),
                               'split':'chronological_70_15_15_with_last_21_days_reserved','source_sha256':preparation['source_sha256']})
            mlflow.log_metrics({'validation_rmse_cm':val_scores['rmse_cm'],'test_rmse_cm':test_scores['rmse_cm'],
                               'test_mae_cm':test_scores['mae_cm'],'validation_persistence_rmse_cm':val_baseline['rmse_cm'],
                               'test_persistence_rmse_cm':test_baseline['rmse_cm']})
            registered='GW_'+station['code'].replace('-','_')
            logged=mlflow.tensorflow.log_model(model,name='model',pip_requirements=['tensorflow==2.21.0','numpy==2.4.4'])
            registered_version=mlflow.register_model(logged.model_uri,registered)
            client.set_registered_model_alias(registered,'candidate',registered_version.version)
            report={**station,'model_id':str(uuid4()),'registry_name':registered,'registry_version':str(registered_version.version),'mlflow_run_id':run.info.run_id,
                    'feature_contract':FEATURE_CONTRACT,'scaler':scaler,'target_transform':'last_depth_plus_scaled_delta',
                    'training_end_date':rows[train[-1]]['observed_date'],'evaluation_end_date':rows[val[-1]]['observed_date'],
                    'test_start_date':rows[test[0]]['observed_date'],'test_end_date':rows[test[-1]]['observed_date'],
                    'train_count':len(train),'validation':val_scores,'test':test_scores,'validation_baseline':val_baseline,'test_baseline':test_baseline,
                    'validation_gate_passed':val_scores['rmse_cm']<=val_baseline['rmse_cm'],
                    'serving_stage':'research_candidate','epochs_run':len(history.history['loss']),
                    'created_at':datetime.now(timezone.utc).isoformat(),'source_sha256':preparation['source_sha256']}
            (folder/'metadata.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            mlflow.log_artifact(str(folder/'metadata.json'))
        with (folder/'test_predictions.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['district','station','target_date','actual_depth_cm','predicted_depth_cm','persistence_depth_cm','residual_cm','model_id'])
            for i,actual,pred,previous in zip(test,ta,test_predictions,tp):
                writer.writerow([station['district'],station['station'],rows[i]['observed_date'],actual,float(pred),float(previous),float(actual-pred),report['model_id']])
        reports.append(report)
        print('RESULT',station['district'],'test_rmse_cm',round(test_scores['rmse_cm'],3),'baseline',round(test_baseline['rmse_cm'],3),'gate',report['validation_gate_passed'],flush=True)
        (output/'training_progress.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'schema_version':1,'mode':'research_candidate','unit':preparation['unit'],'source_sha256':preparation['source_sha256'],
              'source_counts':preparation['counts'],'selection':preparation['selection'],'stations':reports}
    temporary=output/'manifest.json.tmp';temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(output/'manifest.json')
    return manifest
