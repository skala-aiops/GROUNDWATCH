"""격리된 합성 자료로 실제 HTTP→영속 worker→감지→후보→평가→서빙을 검증합니다."""
import csv,io,json,random,os,sys,time,threading,uuid,urllib.request
from pathlib import Path
from datetime import date,timedelta,datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from data.groundwater import DISTRICTS
root=Path(os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch')).parent/'automatic-smoke'/uuid.uuid4().hex
root.mkdir(parents=True)
slope=float(os.getenv('GROUNDWATCH_SYNTHETIC_SLOPE','.3'))
os.environ['GROUNDWATCH_STATE_DIR']=str(root)
os.environ['GROUNDWATCH_TRAIN_EPOCHS']='30'
from backend.groundwater_service import GroundwaterService
from backend.main import create_app
import uvicorn
service=GroundwaterService(root)
stop=threading.Event()
def worker():
    while not stop.is_set():
        if not service.execute_one():stop.wait(.1)
threading.Thread(target=worker,daemon=True).start()
server=uvicorn.Server(uvicorn.Config(create_app(service),host='0.0.0.0',port=18101,log_level='warning'))
threading.Thread(target=server.run,daemon=True).start()
while not server.started:time.sleep(.1)
base='http://127.0.0.1:18101/api/v1'
def http(path,body=None):
    request=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=120) as r:return json.load(r)
def wait(job):
    while True:
        r=http('/jobs/'+job)
        if r['status'] in ('completed','failed','interrupted'):
            assert r['status']=='completed',r
            return r
        time.sleep(.25)
rng=random.Random(42);levels=[10.]
for i in range(1,500):levels.append(10.+.8*(levels[-1]-10.)+rng.gauss(0,.2))
manifest={'approved':True,'source_kind':'synthetic','mapping_version':'synthetic-automatic-v1','training':{'model_architecture':'residual_lstm','learning_rate':.0001},'stations':[dict(d,station_id='SYNTHETIC-'+d['district_code'],level_unit='synthetic-m') for d in DISTRICTS]}
stream=io.StringIO();w=csv.DictWriter(stream,fieldnames=['station_id','district_code','date','groundwater_level','rainfall_mm','level_unit']);w.writeheader()
for d in manifest['stations']:
    for i in range(500):
        value=levels[i] if d['district_code']!='11110' or i<410 else levels[409]+slope*(i-409)
        w.writerow(dict(station_id=d['station_id'],district_code=d['district_code'],date=str(date(2020,1,1)+timedelta(days=i)),groundwater_level=value,rainfall_mm=float(i%7),level_unit='synthetic-m'))
# Upload through the same public multipart API used by the browser.
boundary='gw-'+uuid.uuid4().hex
parts=[]
for name,filename,data,mime in [('file','synthetic.csv',stream.getvalue().encode('utf-8-sig'),'text/csv'),('manifest','manifest.json',json.dumps(manifest).encode(),'application/json')]:
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode()+data+b'\r\n')
req=urllib.request.Request(base+'/datasets',data=b''.join(parts)+f'--{boundary}--\r\n'.encode(),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
with urllib.request.urlopen(req) as response:upload=json.load(response)
results={'purpose':'synthetic automatic full pipeline; not Seoul performance','root':str(root),'created_at':datetime.now(timezone.utc).isoformat(),'rule':f'seed42 AR1(0.8,sigma0.2),500 days; first district slope{slope}/day from day410; unchanged gates','upload':upload}
def save():
    (root/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in results.items() if k in ('purpose','root','rule','passed','automatic_promotions')},ensure_ascii=False),flush=True)
wait(upload['job_id']);save()
r=http('/replays',{'dataset_id':upload['dataset_id'],'start_date':str(date(2020,1,1)+timedelta(days=409)),'end_date':str(date(2020,1,1)+timedelta(days=499))});results['replay']=r;save();results['initial_job']=wait(r['job_id']);save()
id=r['id'];results['before']=http('/forecasts?replay_id='+id)
a=http('/replays/'+id+'/advance',{'days':90});results['advance_job']=wait(a['id']);results['after']=http('/forecasts?replay_id='+id);results['events']=http('/events?replay_id='+id);results['jobs']=http('/jobs?replay_id='+id);results['models']=http('/models?replay_id='+id)
results['automatic_promotions']=[e for e in results['events']['events'] if e.get('result',{}).get('status')=='promoted' and e.get('message','').startswith('후보 평가')]
results['passed']=bool(results['automatic_promotions']) and any(x['district_code']=='11110' and int(x.get('model_version') or 0)>1 for x in results['after']['forecasts'])
save();stop.set();server.should_exit=True
raise SystemExit(0 if results['passed'] else 1)
