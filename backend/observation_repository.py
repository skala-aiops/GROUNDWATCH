"""Immutable source revisions and feature snapshots; never promote unverified mappings."""
from __future__ import annotations
import hashlib
import json
import math
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from backend.groundwater_store import Store, now, encode


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class ObservationRepository(Store):
    def __init__(self, path):
        super().__init__(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS source_mappings(
                    version TEXT NOT NULL, station_id TEXT NOT NULL, district_code TEXT NOT NULL,
                    body TEXT NOT NULL, approved INTEGER NOT NULL CHECK(approved IN (0,1)),
                    PRIMARY KEY(version,station_id), UNIQUE(version,district_code));
                CREATE TABLE IF NOT EXISTS active_api_mappings(
                    district_code TEXT PRIMARY KEY, station_id TEXT NOT NULL, mapping_version TEXT NOT NULL,
                    FOREIGN KEY(mapping_version,station_id) REFERENCES source_mappings(version,station_id));
                CREATE TABLE IF NOT EXISTS collection_runs(
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, station TEXT NOT NULL,
                    start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL,
                    collected_at TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS source_revisions(
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, station TEXT NOT NULL,
                    metric TEXT NOT NULL, observed_date TEXT NOT NULL, value REAL,
                    unit TEXT NOT NULL, quality TEXT NOT NULL, available_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL, body TEXT NOT NULL,
                    CHECK(quality!='valid' OR value IS NOT NULL),
                    CHECK(metric!='rainfall_mm' OR quality!='valid' OR value>=0));
                CREATE INDEX IF NOT EXISTS source_revision_lookup
                    ON source_revisions(source,station,metric,observed_date,available_at);
                CREATE TABLE IF NOT EXISTS collection_members(
                    run_id TEXT NOT NULL REFERENCES collection_runs(id),
                    revision_id TEXT NOT NULL REFERENCES source_revisions(id),
                    PRIMARY KEY(run_id,revision_id));
                CREATE TABLE IF NOT EXISTS quality_findings(
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES collection_runs(id),
                    reason TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS feature_snapshots(
                    id TEXT PRIMARY KEY, station_id TEXT NOT NULL, mapping_version TEXT NOT NULL,
                    contract_id TEXT NOT NULL, cutoff_at TEXT NOT NULL, body TEXT NOT NULL,
                    FOREIGN KEY(mapping_version,station_id) REFERENCES source_mappings(version,station_id));
                CREATE TABLE IF NOT EXISTS snapshot_members(
                    snapshot_id TEXT NOT NULL REFERENCES feature_snapshots(id), observed_date TEXT NOT NULL,
                    level_revision TEXT NOT NULL REFERENCES source_revisions(id),
                    rain_revision TEXT NOT NULL REFERENCES source_revisions(id),
                    PRIMARY KEY(snapshot_id,observed_date));
                CREATE TABLE IF NOT EXISTS active_feature_snapshots(
                    station_id TEXT NOT NULL, purpose TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL REFERENCES feature_snapshots(id), updated_at TEXT NOT NULL,
                    PRIMARY KEY(station_id,purpose));
                CREATE TABLE IF NOT EXISTS live_predictions(
                    id TEXT PRIMARY KEY, station_id TEXT NOT NULL, target_date TEXT NOT NULL,
                    issued_at TEXT NOT NULL, snapshot_id TEXT NOT NULL REFERENCES feature_snapshots(id),
                    model_version TEXT NOT NULL, body TEXT NOT NULL,
                    UNIQUE(station_id,target_date,snapshot_id,model_version));
                CREATE TABLE IF NOT EXISTS live_evaluations(
                    id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL REFERENCES live_predictions(id),
                    actual_revision TEXT NOT NULL REFERENCES source_revisions(id),
                    evaluated_at TEXT NOT NULL, body TEXT NOT NULL,
                    UNIQUE(prediction_id,actual_revision));
                INSERT OR IGNORE INTO schema_migrations VALUES(1,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
            ''')

    def register_mapping(self, mapping):
        required = ('version','station_id','district_code','seoul_name','weather_station','level_unit',
                    'preprocessing_version','evidence','approved')
        if any(k not in mapping for k in required):
            raise ValueError('mapping fields missing')
        if mapping['approved'] is True and (not mapping['evidence'] or
                mapping['level_unit'] in ('unknown','unverified','') or
                not mapping['seoul_name'] or not mapping['weather_station']):
            raise ValueError('approved mapping requires identity/unit/rain evidence')
        item = dict(mapping)
        item['contract_id'] = fingerprint({k:item[k] for k in
            ('station_id','seoul_name','weather_station','level_unit','preprocessing_version')} |
            {'window':20,'features':['groundwater_level','rainfall_mm'],'rain_source':'kma_asos_sumRn'})
        with self.connect() as db:
            old = db.execute('SELECT body FROM source_mappings WHERE version=? AND station_id=?',
                             (item['version'],item['station_id'])).fetchone()
            if old and json.loads(old['body']) != item:
                raise ValueError('mapping version is immutable; register a new version')
            db.execute('INSERT OR IGNORE INTO source_mappings VALUES(?,?,?,?,?)',
                       (item['version'],item['station_id'],item['district_code'],encode(item),int(item['approved'] is True)))
        return item

    def mappings(self, version=None):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM source_mappings' + (' WHERE version=?' if version else '')+
                              ' ORDER BY version, district_code', (version,) if version else ()).fetchall()
        return [json.loads(r['body']) for r in rows]

    def mapping(self, station_id, version):
        return next((m for m in self.mappings(version) if m['station_id']==station_id),None)

    def selected_mappings(self):
        with self.connect() as db:
            rows=db.execute('''SELECT m.body FROM active_api_mappings a JOIN source_mappings m
                ON m.station_id=a.station_id AND m.version=a.mapping_version ORDER BY a.district_code''').fetchall()
        return [json.loads(r['body']) for r in rows]

    def select_mapping(self,station_id,version):
        m=self.mapping(station_id,version)
        if not m or not m['approved']:
            raise ValueError('approved mapping required before selection')
        with self.connect() as db:
            db.execute('INSERT INTO active_api_mappings VALUES(?,?,?) ON CONFLICT(district_code) DO UPDATE SET '
                'station_id=excluded.station_id,mapping_version=excluded.mapping_version',
                (m['district_code'],station_id,version))
            db.execute("DELETE FROM active_feature_snapshots WHERE purpose='live' AND station_id IN (SELECT station_id FROM source_mappings WHERE district_code=?)", (m['district_code'],))
        return m

    def bootstrap_candidates(self, manifest):
        for s in manifest['stations']:
            self.register_mapping({'version':'seoul-asos-candidate-v1','station_id':s['station_id'],
                'district_code':s['district_code'],'station_name':s['station_name'],
                'seoul_name':s.get('source_station_name',s['station_name']),
                'weather_station':'','level_unit':'unverified','preprocessing_version':'strict-v1',
                'approved':False,'evidence':[],
                'blockers':['VTsSec identity/unit not verified','ASOS mapping and blank rainfall semantics not verified']})

    def record_collection(self, job_id, source, station, start, end, result, accepted, rejected, raw_hashes):
        run_id = f'{job_id}:{source}'
        collected_at = now()
        verified = [m for m in self.selected_mappings() if m['seoul_name']==station]
        # Registration alone does not select an operational source contract.
        if not verified:
            matches=[m for m in self.mappings() if m['approved'] and m['seoul_name']==station]
            verified=matches if len(matches)==1 else []
        units = {m['level_unit'] for m in verified}
        unit = 'mm' if source=='kma' else next(iter(units)) if len(units)==1 else 'unverified'
        metric = 'rainfall_mm' if source=='kma' else 'groundwater_level'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT id FROM collection_runs WHERE id=?',(run_id,)).fetchone():
                return run_id
            db.execute('INSERT INTO collection_runs VALUES(?,?,?,?,?,?,?,?)',
                (run_id,source,station,start,end,result['status'],collected_at,encode(result)))
            for row in accepted:
                content = {**row,'metric':metric,'unit':unit,
                    'quality':'valid' if source=='kma' or unit!='unverified' else 'unit_unverified'}
                digest = fingerprint(content)
                old=db.execute('SELECT id,content_hash FROM source_revisions WHERE source=? AND station=? AND metric=? '
                    'AND observed_date=? ORDER BY available_at DESC,rowid DESC LIMIT 1',
                    (source,station,metric,row['date'])).fetchone()
                rid=old['id'] if old and old['content_hash']==digest else fingerprint([source,station,metric,row['date'],digest,collected_at])
                body = {**content,'raw_sha256':raw_hashes,'policy':'strict-v1'}
                db.execute('INSERT OR IGNORE INTO source_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (rid,source,station,metric,row['date'],row['value'],unit,content['quality'],collected_at,digest,encode(body)))
                db.execute('INSERT OR IGNORE INTO collection_members VALUES(?,?)',(run_id,rid))
            for finding in rejected:
                body = {'source':source,'station':station,'finding':finding,'raw_sha256':raw_hashes}
                db.execute('INSERT OR IGNORE INTO quality_findings VALUES(?,?,?,?)',
                           (fingerprint([run_id,body]),run_id,finding['reason'],encode(body)))
                # Invalid revisions also supersede old good data; do not silently resurrect it.
                raw=finding.get('row',{})
                try:
                    day = raw.get('date') or raw.get('tm') or datetime.strptime(str(raw['OBSRVN_YMD']),'%Y%m%d').date().isoformat()
                    day = date.fromisoformat(day).isoformat()
                    identity=str(raw.get('source_station',raw.get('stnId',raw.get('OBSVTR_NM',''))))
                    if identity!=station or not start<=day<=end:
                        continue
                except (ValueError,KeyError,TypeError):
                    continue
                digest=fingerprint({'source':source,'station':station,'finding':finding})
                old=db.execute('SELECT id,content_hash FROM source_revisions WHERE source=? AND station=? AND metric=? '
                    'AND observed_date=? ORDER BY available_at DESC,rowid DESC LIMIT 1',(source,station,metric,day)).fetchone()
                rid=old['id'] if old and old['content_hash']==digest else fingerprint([source,station,metric,day,digest,collected_at])
                db.execute('INSERT OR IGNORE INTO source_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (rid,source,station,metric,day,None,unit,finding['reason'],collected_at,digest,encode(body)))
                db.execute('INSERT OR IGNORE INTO collection_members VALUES(?,?)',(run_id,rid))
        return run_id

    def revisions(self, source, station, metric, start, end, cutoff):
        # Pick the latest revision first; an invalid latest value must not revive an old valid value.
        with self.connect() as db:
            rows = db.execute('''SELECT * FROM source_revisions WHERE source=? AND station=? AND metric=?
                AND observed_date BETWEEN ? AND ? AND available_at<=?
                ORDER BY observed_date, available_at, rowid''',(source,station,metric,start,end,cutoff)).fetchall()
        selected = {r['observed_date']:dict(r) for r in rows}
        return selected

    def publish_snapshot(self, station_id, version, start, end, cutoff=None):
        cutoff = cutoff or now()
        cutoff_dt = datetime.fromisoformat(cutoff.replace('Z','+00:00'))
        if cutoff_dt.tzinfo is None:
            raise ValueError('cutoff requires timezone')
        cutoff = cutoff_dt.astimezone(timezone.utc).isoformat()
        m = self.mapping(station_id,version)
        if not m or not m['approved']:
            raise ValueError('approved API mapping required')
        a,b = date.fromisoformat(start),date.fromisoformat(end)
        if b<a or b>=cutoff_dt.astimezone(ZoneInfo('Asia/Seoul')).date():
            raise ValueError('snapshot requires completed past calendar days')
        level = self.revisions('seoul',m['seoul_name'],'groundwater_level',start,end,cutoff)
        rain = self.revisions('kma',m['weather_station'],'rainfall_mm',start,end,cutoff)
        rows, members = [],[]
        for offset in range((b-a).days+1):
            day=(a+timedelta(days=offset)).isoformat()
            l,r=level.get(day),rain.get(day)
            if not l or not r or l['quality']!='valid' or r['quality']!='valid':
                raise ValueError('incomplete or unverified observation window')
            if l['unit']!=m['level_unit'] or r['unit']!='mm':
                raise ValueError('unit mismatch')
            if not all(math.isfinite(x['value']) for x in (l,r)):
                raise ValueError('nonfinite value')
            # A partial page set cannot become a complete snapshot.
            with self.connect() as db:
                for revision in (l,r):
                    if not db.execute('''SELECT 1 FROM collection_members cm JOIN collection_runs cr
                        ON cr.id=cm.run_id WHERE cm.revision_id=? AND cr.status='collected' AND cr.collected_at<=? LIMIT 1''',
                        (revision['id'],cutoff)).fetchone():
                        raise ValueError('incomplete source collection')
            rows.append({'station_id':station_id,'district_code':m['district_code'],'date':day,
                         'groundwater_level':l['value'],'rainfall_mm':r['value'],'level_unit':l['unit']})
            members.append((day,l['id'],r['id']))
        body={'station_id':station_id,'mapping_version':version,'feature_contract_id':m['contract_id'],
              'preprocessing_version':m['preprocessing_version'],'rain_source':'kma_asos_sumRn',
              'weather_station_id':m['weather_station'],'level_unit':m['level_unit'],
              'rows':rows,'members':members,'source_kind':'observed_api','start_date':start,'end_date':end}
        sid=fingerprint(body)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO feature_snapshots VALUES(?,?,?,?,?,?)',
                       (sid,station_id,version,m['contract_id'],cutoff,encode(body)))
            db.executemany('INSERT OR IGNORE INTO snapshot_members VALUES(?,?,?,?)',
                           [(sid,*member) for member in members])
        return {'id':sid,**body}

    def snapshot(self, sid):
        with self.connect() as db:
            row=db.execute('SELECT body,cutoff_at FROM feature_snapshots WHERE id=?',(sid,)).fetchone()
        if not row:
            raise KeyError('snapshot not found')
        return {'id':sid,'cutoff_at':row['cutoff_at'],**json.loads(row['body'])}

    def activate(self, sid, purpose='live'):
        if purpose not in ('live','training'):
            raise ValueError('invalid snapshot purpose')
        snapshot=self.snapshot(sid)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if purpose=='live':
                mapping=self.mapping(snapshot['station_id'],snapshot['mapping_version'])
                db.execute('INSERT INTO active_api_mappings VALUES(?,?,?) ON CONFLICT(district_code) DO UPDATE SET station_id=excluded.station_id,mapping_version=excluded.mapping_version', (mapping['district_code'],snapshot['station_id'],snapshot['mapping_version']))
            db.execute('INSERT INTO active_feature_snapshots VALUES(?,?,?,?) ON CONFLICT(station_id,purpose) '
                       'DO UPDATE SET snapshot_id=excluded.snapshot_id,updated_at=excluded.updated_at',
                       (snapshot['station_id'],purpose,sid,now()))
        return snapshot

    def active(self):
        with self.connect() as db:
            return {r['station_id']:r['snapshot_id'] for r in db.execute(
                "SELECT * FROM active_feature_snapshots WHERE purpose='live'")}

    def save_prediction(self, value):
        sid=value['inference_snapshot_id'];snapshot=self.snapshot(sid)
        if value['station_id']!=snapshot['station_id'] or value['feature_contract_id']!=snapshot['feature_contract_id']:
            raise ValueError('prediction snapshot identity mismatch')
        target=date.fromisoformat(value['forecast_date'])
        issued=datetime.fromisoformat(value['issued_at'])
        if target!=issued.astimezone(ZoneInfo('Asia/Seoul')).date() or snapshot['end_date']!=(target-timedelta(days=1)).isoformat():
            raise ValueError('live prediction requires today target and yesterday input')
        if snapshot['cutoff_at']>value['issued_at']:
            raise ValueError('snapshot unavailable at prediction issue time')
        pid=fingerprint([value['station_id'],value['forecast_date'],sid,str(value['model_version'])])
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO live_predictions VALUES(?,?,?,?,?,?,?)',
                (pid,value['station_id'],value['forecast_date'],value['issued_at'],sid,str(value['model_version']),encode(value)))
        return pid

    def predictions(self,target):
        with self.connect() as db:
            return [{**json.loads(r['body']),'id':r['id']} for r in db.execute(
                'SELECT * FROM live_predictions WHERE target_date=? ORDER BY issued_at,id',(target,))]

    def evaluate_available(self):
        created=0
        with self.connect() as db:
            predictions=[dict(r) for r in db.execute('SELECT * FROM live_predictions')]
        for p in predictions:
            snapshot=self.snapshot(p['snapshot_id']);mapping=self.mapping(p['station_id'],snapshot['mapping_version'])
            actuals=self.revisions('seoul',mapping['seoul_name'],'groundwater_level',p['target_date'],p['target_date'],now())
            actual=actuals.get(p['target_date'])
            if not actual or actual['quality']!='valid' or actual['unit']!=snapshot['level_unit']:
                continue
            with self.connect() as db:
                complete=db.execute("SELECT 1 FROM collection_members cm JOIN collection_runs cr ON cr.id=cm.run_id WHERE cm.revision_id=? AND cr.status='collected' AND cr.collected_at<=? LIMIT 1", (actual['id'],now())).fetchone()
            if not complete:
                continue
            value=json.loads(p['body']);body={'actual':actual['value'],'prediction':value['prediction'],
                'residual':value['prediction']-actual['value'],'actual_available_at':actual['available_at'],
                'policy':'strict-v1','automatic_retroactive_retrain':False}
            with self.connect() as db:
                created+=db.execute('INSERT OR IGNORE INTO live_evaluations VALUES(?,?,?,?,?)',
                    (fingerprint([p['id'],actual['id']]),p['id'],actual['id'],now(),encode(body))).rowcount
        return created

    def summary(self):
        with self.connect() as db:
            counts={table:db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in
                ('source_mappings','collection_runs','source_revisions','quality_findings','feature_snapshots',
                 'live_predictions','live_evaluations')}
        return {'counts':counts,'active_snapshots':self.active(),'schema_version':1}

    def backup(self, target):
        target=Path(target)
        if target.exists():
            raise ValueError('backup target already exists')
        target.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)
        return str(target)
