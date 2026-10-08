"""Isolated real TensorFlow/MLflow and loopback HTTP check on synthetic data."""
import hashlib
import json
import os
import runpy
import socket
import sys
import threading
import time
import tempfile
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

os.environ['GROUNDWATCH_STATE_DIR'] = '/tmp/policy-http-module'
smoke_root = Path(tempfile.mkdtemp(prefix='groundwatch-policy-synthetic-'))
sys.argv = ['scripts/verify_model_promotion.py', '--state-dir', str(smoke_root)]
try:
    runpy.run_path('scripts/verify_model_promotion.py', run_name='__main__')
except SystemExit as exc:
    if exc.code:
        raise

import uvicorn
from serving_app.groundwater_models import ModelManager, ModelNotReady
from serving_app.groundwater_service import GroundwaterService
from serving_app.main import create_app

path = next(smoke_root.glob('*/results.json'))
smoke = json.loads(path.read_text())
attempt = next(a for a in smoke['attempts'] if a.get('evaluation', {}).get('status') == 'promoted')
namespace = 'trend_' + str(attempt['number'])
manager = ModelManager(smoke['run_root'], namespace=namespace)
# Recreate the script's explicitly synthetic linear observations.
import random
rng = random.Random(42)
levels = [10.]
for i in range(1, 410):
    levels.append(10. + .8 * (levels[-1]-10.) + rng.gauss(0, .2))
records = [{'date': str(date(2020, 1, 1)+timedelta(days=410+i)),
            'groundwater_level': levels[-1]+attempt['slope']*(i+1),
            'rainfall_mm': float((410+i)%7), 'station_id': 'synthetic-well',
            'district_code': '11110', 'level_unit': 'synthetic_level'} for i in range(71)]
keys = ('date', 'groundwater_level', 'rainfall_mm', 'station_id', 'level_unit')
sequence = [{k: row[k] for k in keys} for row in records[-20:]]

def serve(current):
    service = GroundwaterService('/tmp/policy-http-service')
    service._managers['historical'] = current
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(service), log_level='warning'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError('isolated HTTP server did not start')
        time.sleep(.05)
    return server, thread, port

def predict(port):
    request = Request(f'http://127.0.0.1:{port}/api/v1/districts/11110/predict',
                      data=json.dumps({'sequence': sequence}).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=15) as response:
        assert response.status == 200
        return {'status_code': response.status, 'response': json.load(response)}

def stop(server, thread):
    server.should_exit = True
    thread.join(timeout=15)
    assert not thread.is_alive()

manager.rollback('11110', '1')
server, thread, port = serve(manager)
try:
    before = predict(port)
    assert before['response']['model_version'] == '1'
    promoted = manager.promote('11110', attempt['candidate']['candidate_version'])
    after = predict(port)
    assert after['response']['model_version'] == promoted['model_version'] == '2'
    assert after['response']['prediction'] == attempt['actual_prediction_after_promotion']['prediction']
    candidate = manager.fine_tune('11110', records[-41:])
    try:
        manager.promote('11110', candidate['candidate_version'])
    except ModelNotReady:
        blocked = True
    else:
        raise AssertionError('unevaluated candidate was promoted')
    awaiting = predict(port)
    assert awaiting == after
    # Synthetic policy fixture: future labels follow the frozen champion exactly.
    # This deliberately yields champion RMSE zero; it is not observed accuracy.
    future = [dict(row) for row in records[-20:]]
    for i in range(30):
        predicted = manager.predict('11110', future[-20:])
        future.append({**records[-1], 'date': predicted['forecast_date'],
                       'groundwater_level': predicted['prediction'], 'rainfall_mm': float((481+i)%7)})
    rejected = manager.evaluate_candidate('11110', candidate['candidate_version'], future)
    assert rejected['status'] == 'rejected', rejected
    assert rejected['metrics']['shadow_champion']['rmse'] == 0
    retained = predict(port)
    assert retained == after
finally:
    stop(server, thread)

restored = ModelManager(smoke['run_root'], namespace=namespace)
server, thread, port = serve(restored)
try:
    restarted = predict(port)
    assert restarted == after
    try:
        restored.promote('11110', candidate['candidate_version'])
    except ModelNotReady:
        rejected_blocked_after_restart = True
    else:
        raise AssertionError('rejected candidate was promoted after restart')
finally:
    stop(server, thread)

result = {'purpose': 'synthetic actual TensorFlow/MLflow and real loopback HTTP policy verification; no Seoul accuracy claim',
          'network': 'container loopback only; no host ports or operational volumes',
          'seed': 42, 'initial': smoke['initial'], 'successful_evaluation': attempt['evaluation'],
          'before': before, 'after': after, 'awaiting_candidate': awaiting,
          'unevaluated_direct_promotion_blocked': blocked,
          'rejection_rule': '30 future synthetic labels recursively generated from frozen champion predictions',
          'rejected_evaluation': rejected, 'after_rejection': retained,
          'after_server_and_manager_restart': restarted,
          'rejected_direct_promotion_blocked_after_restart': rejected_blocked_after_restart,
          'source_hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                            (Path('serving_app/groundwater_models.py'), Path('tests/test_groundwater_models.py'), Path('tests/test_groundwater_api.py'))}}
print('POLICY_HTTP_RESULT=' + json.dumps(result, ensure_ascii=False), flush=True)
