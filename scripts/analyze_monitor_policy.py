"""Saved labelled predictions, no retraining: descriptive threshold sensitivity."""
import json,math,sqlite3,os
from pathlib import Path
from collections import defaultdict
root=Path(os.getenv('GROUNDWATCH_STATE_DIR','runtime/groundwatch'))
db=sqlite3.connect(root/'metadata.sqlite3')
results={'method':'counterfactual alert count on saved real replay predictions; no retraining rerun; not false-positive rate or prevention effect','scenarios':[]}
for ns,title in [('f26d52070b8943649c28634388e43498','observed'),('386386a79ba142abb650fbd7d6915acd','synthetic_level_shift')]:
 rows=db.execute('SELECT district_code,model_version,target_date,body,actual FROM forecasts_v2 WHERE namespace=? AND actual IS NOT NULL ORDER BY district_code,model_version,target_date',(ns,)).fetchall()
 grouped=defaultdict(list)
 for code,version,day,body,actual in rows:grouped[(code,version)].append((day,json.loads(body)['prediction']-actual))
 outcome={'namespace':ns,'kind':title,'labelled_count':len(rows),'policies':[]}
 for multiplier in [1.25,1.5,2.0]:
  for required in [1,2,3]:
   alerts=0;districts=set();samples=0
   for (code,version),seq in grouped.items():
    state=json.loads((root/'models'/ns/(code+'.json')).read_text());bundle=state['versions'][version];threshold=bundle['threshold']/1.5*multiplier
    breach=0;last=-10000
    for i in range(20,len(seq)):
     from datetime import date,timedelta
     part=seq[i-20:i+1]
     if any(date.fromisoformat(part[j][0])+timedelta(days=1)!=date.fromisoformat(part[j+1][0]) for j in range(20)):breach=0;continue
     samples+=1;rmse=math.sqrt(sum(v*v for _,v in part)/21);breach=breach+1 if rmse>threshold else 0
     if breach>=required and i-last>=21:alerts+=1;districts.add(code);last=i;breach=0
   outcome['policies'].append({'p95_multiplier':multiplier,'consecutive_breaches':required,'cooldown_days':21,'eligible_windows':samples,'potential_alerts':alerts,'district_count':len(districts)})
 results['scenarios'].append(outcome)
print(json.dumps(results,ensure_ascii=False,indent=2))
