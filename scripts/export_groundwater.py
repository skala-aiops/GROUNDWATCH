"""학습·HTTP 검증 결과를 재사용할 수 있는 CSV로 내보냅니다."""
import argparse
import csv
import json
from pathlib import Path
import shutil


def export(root, output):
    root, output=Path(root),Path(output);output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((root/'trained/manifest.json').read_text())
    metrics=[];predictions=[]
    for s in manifest['stations']:
        metrics.append(dict(district=s['district'],station=s['station'],model_id=s['model_id'],
                            train_count=s['train_count'],training_end_date=s['training_end_date'],validation_end_date=s['evaluation_end_date'],
                            test_start_date=s['test_start_date'],test_end_date=s['test_end_date'],test_count=s['test']['count'],
                            lstm_rmse_cm=s['test']['rmse_cm'],persistence_rmse_cm=s['test_baseline']['rmse_cm'],mae_cm=s['test']['mae_cm'],
                            validation_gate_passed=s['validation_gate_passed'],serving_stage=s['serving_stage']))
        with (root/'trained'/s['code']/'test_predictions.csv').open(encoding='utf-8-sig') as stream:
            predictions.extend(csv.DictReader(stream))
    for name,values in [('district_model_metrics.csv',metrics),('heldout_predictions.csv',predictions)]:
        with (output/name).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(values[0]));writer.writeheader();writer.writerows(values)
    for name in ('latest_forecasts.csv','http_verification.json'):
        shutil.copyfile(root/'results'/name,output/name)
    shutil.copyfile(root/'trained/manifest.json',output/'manifest.json')
    print(f'{len(metrics)} models, {len(predictions)} held-out predictions -> {output}')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='serving_app/models/groundwater');parser.add_argument('--output',default='serving_app/models/groundwater/exports')
    args=parser.parse_args();export(args.root,args.output)
