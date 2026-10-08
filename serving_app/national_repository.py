"""Isolated national registry and immutable, cutoff-aware daily observations."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('timezone required')
        return parsed.astimezone(timezone.utc).isoformat()
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('timezone-aware ISO timestamp required') from exc


def _day(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('YYYY-MM-DD required')
    return parsed


def _text(item, keys):
    for key in keys:
        if not isinstance(item.get(key), str) or not item[key].strip():
            raise ValueError(f'{key} required')


class NationalRepository:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS national_schema(version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO national_schema VALUES(1);
                CREATE TABLE IF NOT EXISTS national_stations(
                    station_id TEXT PRIMARY KEY, region_code TEXT NOT NULL,
                    verified INTEGER NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS national_observations(
                    station_id TEXT NOT NULL REFERENCES national_stations(station_id),
                    revision_id TEXT NOT NULL, date TEXT NOT NULL,
                    available_at TEXT NOT NULL, collected_at TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(station_id,revision_id));
                CREATE INDEX IF NOT EXISTS national_daily_lookup ON
                    national_observations(station_id,date,available_at,collected_at);
                CREATE TABLE IF NOT EXISTS national_rainy_periods(
                    id TEXT PRIMARY KEY, year INTEGER NOT NULL, region_code TEXT NOT NULL, body TEXT NOT NULL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def register_station(self, item):
        item = dict(item)
        _text(item, ('station_id','provider','source_station_id','name','region_code',
                     'level_unit','level_reference'))
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', item['station_id']):
            raise ValueError('station_id must be URL-safe without slashes')
        if type(item.get('verified')) is not bool:
            raise ValueError('verified boolean required')
        if not isinstance(item.get('evidence'), list) or not item['evidence'] or not all(
                isinstance(x, str) and x.strip() for x in item['evidence']):
            raise ValueError('evidence required even for unverified metadata')
        item.setdefault('source_kind','observed')
        if item['source_kind'] not in ('observed','synthetic'):
            raise ValueError('source_kind must be observed or synthetic')
        for key, low, high in [('latitude',-90,90),('longitude',-180,180)]:
            val = item.get(key)
            if val is not None and (isinstance(val, bool) or not isinstance(val,(float,int))
                                    or not math.isfinite(val) or not low <= val <= high):
                raise ValueError(f'invalid {key}')
        body = _encode(item)
        with self.connect() as db:
            old = db.execute('SELECT body FROM national_stations WHERE station_id=?',
                             (item['station_id'],)).fetchone()
            if old and old['body'] != body:
                raise ValueError('immutable station metadata; use a new station version ID')
            db.execute('INSERT OR IGNORE INTO national_stations VALUES(?,?,?,?)',
                       (item['station_id'],item['region_code'],int(item['verified']),body))
        return item

    def station(self, station_id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM national_stations WHERE station_id=?',(station_id,)).fetchone()
        if row is None:
            raise KeyError(station_id)
        return json.loads(row['body'])

    def list_stations(self, region_code=None, verified=None, cursor=None, limit=50):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('limit must be 1..200')
        if verified is not None and type(verified) is not bool:
            raise ValueError('verified must be boolean')
        clauses, params = [], []
        for key, val in [('region_code',region_code),('verified',verified)]:
            if val is not None:
                clauses.append(f'{key}=?'); params.append(val)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.connect() as db:
            counts = db.execute('SELECT COUNT(*) AS total,COALESCE(SUM(verified),0) AS verified_count '
                                'FROM national_stations'+where,params).fetchone()
            page_clauses, page_params = list(clauses), list(params)
            if cursor is not None:
                page_clauses.append('station_id>?');page_params.append(cursor)
            page_where = ' WHERE '+' AND '.join(page_clauses) if page_clauses else ''
            rows = db.execute('SELECT body FROM national_stations'+page_where+
                              ' ORDER BY station_id LIMIT ?',page_params+[limit+1]).fetchall()
        items = [json.loads(r['body']) for r in rows[:limit]]
        return {'items':items,'next_cursor':items[-1]['station_id'] if len(rows)>limit else None,
                **dict(counts)}

    def _validated_observation(self, station_id, item):
        self.station(station_id)
        item = dict(item)
        _text(item, ('date','level_unit','level_reference','revision_id','source_sha256'))
        _day(item['date'])
        for key in ('available_at','collected_at'):
            item[key] = _time(item.get(key))
        item.setdefault('quality_status','valid')
        if item['quality_status'] not in ('valid','missing','invalid','conflict'):
            raise ValueError('unknown quality_status')
        for key in ('groundwater_level','rainfall_mm'):
            val = item.get(key)
            if val is None and item['quality_status'] != 'valid':
                continue
            if isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val):
                raise ValueError(f'{key} must be finite')
            if key == 'rainfall_mm' and val < 0:
                raise ValueError('rainfall_mm must be nonnegative')
        item['station_id'] = station_id
        _encode(item)
        return item

    def _insert_observation(self, db, station_id, item):
        body = _encode(item)
        old = db.execute('SELECT body FROM national_observations WHERE station_id=? AND revision_id=?',
                         (station_id,item['revision_id'])).fetchone()
        if old and old['body'] != body:
            raise ValueError('immutable observation revision')
        db.execute('INSERT OR IGNORE INTO national_observations VALUES(?,?,?,?,?,?)',
                   (station_id,item['revision_id'],item['date'],item['available_at'],item['collected_at'],body))

    def add_observation(self, station_id, item):
        return self.add_observations(station_id,[item])[0]

    def add_observations(self, station_id, items):
        if not isinstance(items,list) or not items:
            raise ValueError('nonempty observations list required')
        # Validate the entire request first; conflicts detected during insertion also roll back.
        validated = [self._validated_observation(station_id,item) for item in items]
        with self.connect() as db:
            for item in validated:
                self._insert_observation(db,station_id,item)
        return validated

    def observations(self, station_id, start=None, end=None, cutoff=None):
        self.station(station_id)
        clauses, params = ['station_id=?'], [station_id]
        for key, value, op in [('date',start,'>='),('date',end,'<=')]:
            if value is not None:
                _day(value);clauses.append(f'{key}{op}?');params.append(value)
        if cutoff is not None:
            cutoff = _time(cutoff)
            clauses.extend(['available_at<=?','collected_at<=?']);params.extend([cutoff,cutoff])
        with self.connect() as db:
            rows = db.execute('SELECT body FROM national_observations WHERE '+' AND '.join(clauses)+
                              ' ORDER BY date,available_at,collected_at,revision_id',params).fetchall()
        selected = {}
        for row in rows:
            item = json.loads(row['body'])
            previous = selected.get(item['date'])
            if previous and (previous['available_at'],previous['collected_at']) == (
                    item['available_at'],item['collected_at']):
                keys = ('groundwater_level','rainfall_mm','level_unit','level_reference','quality_status')
                if previous['quality_status'] == 'conflict' or any(previous.get(k) != item.get(k) for k in keys):
                    item['quality_status'] = 'conflict'
            selected[item['date']] = item
        return list(selected.values())

    def first_observation_availability(self, station_id, day, cutoff=None):
        """First known label time, preventing later revisions from hiding leakage."""
        self.station(station_id)
        clauses=['station_id=?','date=?'];params=[station_id,_day(day)]
        if cutoff is not None:
            clauses.extend(['available_at<=?','collected_at<=?']);params.extend([_time(cutoff)]*2)
        with self.connect() as db:
            row=db.execute('SELECT MIN(available_at) AS first_time FROM national_observations WHERE '+
                           ' AND '.join(clauses),params).fetchone()
        return row['first_time']

    def snapshot(self, station_id, input_end_date, cutoff):
        station = self.station(station_id)
        experimental = (station.get('source_contract_verified') is True and
                        station.get('mapping_status') == 'experimental' and
                        station.get('operational_approved') is False and
                        bool(station.get('mapping_version')) and bool(station.get('evidence')))
        if not station['verified'] and not experimental:
            raise ValueError('unverified_metadata')
        end = _day(input_end_date)
        cutoff = _time(cutoff)
        start = end-timedelta(days=19)
        rows = self.observations(station_id,start.isoformat(),end.isoformat(),cutoff)
        if len(rows) != 20 or [r['date'] for r in rows] != [
                (start+timedelta(days=n)).isoformat() for n in range(20)]:
            raise ValueError('incomplete_consecutive_input')
        for row in rows:
            if row['quality_status'] != 'valid':
                raise ValueError('invalid_quality')
            if any(row[k] != station[k] for k in ('level_unit','level_reference')):
                raise ValueError('unit_or_reference_mismatch')
        # Daily observations for a future local date cannot be present at an earlier cutoff.
        from zoneinfo import ZoneInfo
        local_day = datetime.fromisoformat(cutoff).astimezone(ZoneInfo('Asia/Seoul')).date()
        if end >= local_day:
            raise ValueError('daily_input_not_complete_at_cutoff')
        result = {'station_id':station_id,'source_kind':station['source_kind'],
                  'feature_contract_id':'national-m0-v1','input_end_date':end.isoformat(),
                  'target_date':(end+timedelta(days=1)).isoformat(),'cutoff':cutoff,
                  'level_unit':station['level_unit'],'level_reference':station['level_reference'],
                  'rows':rows}
        identity = {key:value for key,value in result.items() if key != 'cutoff'}
        result['sha256'] = hashlib.sha256(_encode(identity).encode()).hexdigest()
        result['id'] = result['sha256']
        return result

    def readiness(self, station_id, input_end_date=None, cutoff=None):
        self.station(station_id)
        cutoff = _time(cutoff or datetime.now(timezone.utc).isoformat())
        if input_end_date is None:
            from zoneinfo import ZoneInfo
            input_end_date = (datetime.fromisoformat(cutoff).astimezone(ZoneInfo('Asia/Seoul')).date()-timedelta(days=1)).isoformat()
        try:
            snap = self.snapshot(station_id,input_end_date,cutoff)
            return {'station_id':station_id,'data_ready':True,'status':'ready',
                    'input_end_date':input_end_date,'target_date':snap['target_date'],'snapshot_id':snap['id']}
        except ValueError as exc:
            return {'station_id':station_id,'data_ready':False,'status':str(exc),
                    'input_end_date':input_end_date}

    def add_rainy_period(self, item):
        item = dict(item)
        _text(item,('region_code','start_date','end_date','source_sha256'))
        if type(item.get('year')) is not int:
            raise ValueError('year integer required')
        start,end = _day(item['start_date']),_day(item['end_date'])
        if end < start or start.year != item['year'] or end.year != item['year']:
            raise ValueError('invalid rainy period dates')
        if not isinstance(item.get('evidence'),list) or not item['evidence']:
            raise ValueError('evidence required')
        item.setdefault('usage','evaluation_only')
        if item['usage'] != 'evaluation_only':
            raise ValueError('rainy period labels are evaluation_only')
        body = _encode(item)
        identity = hashlib.sha256(body.encode()).hexdigest()
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO national_rainy_periods VALUES(?,?,?,?)',
                       (identity,item['year'],item['region_code'],body))
        return {**item,'id':identity}

    def rainy_periods(self, year=None, region_code=None):
        clauses,params = [],[]
        for key,value in [('year',year),('region_code',region_code)]:
            if value is not None:
                clauses.append(f'{key}=?');params.append(value)
        with self.connect() as db:
            rows = db.execute('SELECT id,body FROM national_rainy_periods'+
                              (' WHERE '+' AND '.join(clauses) if clauses else '')+
                              ' ORDER BY year,region_code,id',params).fetchall()
        return [{**json.loads(r['body']),'id':r['id']} for r in rows]
