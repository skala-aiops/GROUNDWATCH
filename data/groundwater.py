"""GroundWatch canonical daily observations; missing data never becomes rainfall zero."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

_NAMES = ('종로구','중구','용산구','성동구','광진구','동대문구','중랑구','성북구','강북구','도봉구','노원구','은평구','서대문구','마포구','양천구','강서구','구로구','금천구','영등포구','동작구','관악구','서초구','강남구','송파구','강동구')
_CODES = ('11110','11140','11170','11200','11215','11230','11260','11290','11305','11320','11350','11380','11410','11440','11470','11500','11530','11545','11560','11590','11620','11650','11680','11710','11740')
DISTRICTS = [dict(district_code=c, district_name=n) for c,n in zip(_CODES,_NAMES)]
DISTRICT_CODES = frozenset(_CODES)
REQUIRED_COLUMNS = ('station_id','district_code','date','groundwater_level','rainfall_mm','level_unit')


@dataclass(frozen=True)
class Observation:
    station_id: str
    district_code: str
    date: date
    groundwater_level: float
    rainfall_mm: float
    level_unit: str
    dataset_version: str

    def to_dict(self):
        value = asdict(self)
        value['date'] = self.date.isoformat()
        return value


@dataclass
class CanonicalDataset:
    records: list[Observation]
    dataset_version: str
    report: dict
    manifest: dict = field(default_factory=dict)

    def rows_for_district(self, district_code):
        records = station_records(self, district_code)
        return [record.to_dict() for record in records]

    def metadata_for_district(self, district_code):
        records = station_records(self, district_code)
        station = next((s for s in self.manifest.get('stations', []) if s['district_code'] == district_code), {})
        return {**self.manifest.get('training', {}), **station, 'district_code': district_code,
                'station_id': records[0].station_id if records else station.get('station_id'),
                'level_unit': records[0].level_unit if records else station.get('level_unit'),
                'dataset_version': self.dataset_version,
                'mapping_version': self.manifest.get('mapping_version'),
                'manifest_approved': self.manifest.get('approved') is True}


def validate_manifest(manifest, require_all=True):
    if not isinstance(manifest, dict) or manifest.get('approved') is not True:
        raise ValueError('Representative manifest must explicitly have approved=true')
    if not isinstance(manifest.get('mapping_version'), str) or not manifest['mapping_version'].strip():
        raise ValueError('mapping_version is required')
    if manifest.get('source_kind', 'observed') not in ('observed', 'synthetic'):
        raise ValueError('source_kind must be observed or synthetic')
    stations = manifest.get('stations', [])
    if not isinstance(stations, list) or not all(isinstance(station, dict) for station in stations):
        raise ValueError('stations must be a list of objects')
    if not all(isinstance(station.get('district_code'), str) for station in stations):
        raise ValueError('district_code must be a string')
    codes = [str(s.get('district_code', '')) for s in stations]
    if len(codes) != len(set(codes)) or not set(codes) <= DISTRICT_CODES:
        raise ValueError('Each district must have exactly one representative')
    if require_all and set(codes) != DISTRICT_CODES:
        raise ValueError('Approved manifest requires all 25 districts')
    if any(str(station.get('level_unit', '')).strip().lower() in ('unknown', 'unverified', '미확인') for station in stations):
        raise ValueError('level_unit must be explicitly verified')
    identifiers = [str(s.get('station_id', '')).strip() for s in stations]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError('A representative station cannot belong to multiple districts')
    for station in stations:
        for key in ('station_id', 'level_unit'):
            if not isinstance(station.get(key), str) or not station[key].strip():
                raise ValueError(f'{key} is required in representative manifest')
    if manifest.get('source_kind', 'observed') == 'observed' and any('synthetic' in s['level_unit'].lower() for s in stations):
        raise ValueError('synthetic units require source_kind=synthetic')
    return manifest


def load_canonical(path, manifest_path=None, *, require_all=False):
    """Read a canonical CSV, quarantine every conflicting station/date group.

    Row errors are reported and excluded. Schema errors raise ValueError. Dates
    after today are excluded. Source units and station identifiers must be supplied.
    """
    path = Path(path)
    version = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {}
    if manifest_path is not None:
        manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8-sig')) if not isinstance(manifest_path, dict) else manifest_path
        validate_manifest(manifest, require_all=require_all)
        expected = manifest.get("canonical_sha256")
        if expected is not None and expected != version:
            raise ValueError("canonical_sha256 does not match uploaded CSV bytes")
    errors, groups, total = [], {}, 0
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not set(REQUIRED_COLUMNS) <= set(reader.fieldnames or []):
            raise ValueError('Required columns: ' + ', '.join(REQUIRED_COLUMNS))
        for line, row in enumerate(reader, 2):
            total += 1
            try:
                missing = [key for key in REQUIRED_COLUMNS if not str(row.get(key, '')).strip()]
                if missing:
                    raise ValueError('Missing: ' + ', '.join(missing))
                day = date.fromisoformat(row['date'])
                if day.isoformat() != row['date']:
                    raise ValueError('Expected ISO YYYY-MM-DD')
                if day > date.today():
                    raise ValueError('Future observation date')
                code = row['district_code'].strip()
                if code not in DISTRICT_CODES:
                    raise ValueError('Unknown district_code')
                level, rain = float(row['groundwater_level']), float(row['rainfall_mm'])
                if not math.isfinite(level) or not math.isfinite(rain) or rain < 0:
                    raise ValueError('Values must be finite and rainfall nonnegative')
                record = Observation(row['station_id'].strip(), code, day, level, rain, row['level_unit'].strip(), version)
                groups.setdefault((record.station_id, day), []).append(record)
            except (ValueError, TypeError) as exc:
                if len(errors) < 100:
                    errors.append({'line': line, 'reason': str(exc)})
    records, conflicts, duplicates = [], [], 0
    for key, group in groups.items():
        unique = set(group)
        if len(unique) > 1:
            conflicts.append({'station_id': key[0], 'date': key[1].isoformat(), 'rows': len(group)})
        else:
            records.append(group[0])
            duplicates += len(group)-1
    units, districts = {}, {}
    for record in records:
        units.setdefault(record.station_id,set()).add(record.level_unit)
        districts.setdefault(record.station_id,set()).add(record.district_code)
    invalid_stations = {key for key in units if len(units[key]) > 1 or len(districts[key]) > 1}
    records = [r for r in records if r.station_id not in invalid_stations]
    if manifest:
        selected = {s['district_code']: s for s in manifest['stations']}
        for record in records:
            expected = selected.get(record.district_code)
            if expected and expected['station_id'] == record.station_id and expected['level_unit'] != record.level_unit:
                raise ValueError('Manifest level_unit differs from canonical data')
        records = [r for r in records if r.district_code in selected and r.station_id == selected[r.district_code]['station_id']]
    records.sort(key=lambda r: (r.district_code,r.station_id,r.date))
    report = {'source_sha256':version,'source_rows':total,'accepted_rows':len(records),
              'invalid_rows':total-sum(len(g) for g in groups.values()),'error_examples':errors,
              'exact_duplicates_removed':duplicates,'conflicting_groups':len(conflicts),
              'conflict_examples':conflicts[:100], 'inconsistent_stations':sorted(invalid_stations),
              'manifest_approved':manifest.get('approved') is True,
              'districts_with_data':len({r.district_code for r in records})}
    return CanonicalDataset(records,version,report,manifest)


def station_records(dataset, district_code):
    records = [r for r in dataset.records if r.district_code == district_code]
    if len({r.station_id for r in records}) > 1:
        raise ValueError('Multiple stations in district: approved representative manifest required')
    return sorted(records,key=lambda r:r.date)


@dataclass(frozen=True)
class Window:
    inputs: tuple
    target: float
    target_date: date
    station_id: str
    district_code: str


def continuous_windows(records, window=20):
    if window < 1:
        raise ValueError('window must be positive')
    records = sorted(records, key=lambda r:r.date)
    if len({(r.station_id,r.district_code,r.level_unit) for r in records}) > 1:
        raise ValueError('Windows cannot mix stations, districts or units')
    if len({r.date for r in records}) != len(records):
        raise ValueError('Duplicate dates must be resolved before windows')
    result = []
    for index in range(window,len(records)):
        segment = records[index-window:index+1]
        if any(b.date-a.date != timedelta(days=1) for a,b in zip(segment,segment[1:])):
            continue
        target = segment[-1]
        result.append(Window(tuple((r.groundwater_level,r.rainfall_mm) for r in segment[:-1]),target.groundwater_level,target.date,target.station_id,target.district_code))
    return result


def chronological_split(windows, train_min=180, validation_days=60, test_days=60, replay_days=90):
    windows = sorted(windows,key=lambda w:w.target_date)
    sizes = (train_min,validation_days,test_days,replay_days)
    if any(size < 1 for size in sizes) or len(windows) < sum(sizes):
        raise ValueError(f'Insufficient targets: need {sum(sizes)}, got {len(windows)}')
    if any(b.target_date-a.target_date != timedelta(days=1) for a,b in zip(windows,windows[1:])):
        raise ValueError('Partitions require a continuous calendar period')
    train_end = len(windows)-validation_days-test_days-replay_days
    val_end = train_end+validation_days
    test_end = val_end+test_days
    return {'train':windows[:train_end], 'validation':windows[train_end:val_end], 'test':windows[val_end:test_end], 'replay':windows[test_end:]}


@dataclass(frozen=True)
class FeatureScaler:
    means: tuple
    scales: tuple

    @classmethod
    def fit(cls, rows):
        rows = list(rows)
        if not rows:
            raise ValueError('Cannot fit empty training data')
        means = tuple(sum(row[i] for row in rows)/len(rows) for i in range(2))
        scales = tuple(math.sqrt(sum((row[i]-means[i])**2 for row in rows)/len(rows)) or 1.0 for i in range(2))
        if not all(math.isfinite(v) for v in means+scales):
            raise ValueError('Training data must be finite')
        return cls(means,scales)

    def transform(self, rows):
        return [[(row[i]-self.means[i])/self.scales[i] for i in range(2)] for row in rows]

    def inverse_level(self, value):
        return float(value)*self.scales[0]+self.means[0]

    def to_dict(self):
        return {'means':list(self.means),'scales':list(self.scales)}

    @classmethod
    def from_dict(cls, value):
        return cls(tuple(value['means']),tuple(value['scales']))


def convert_korean_source(source_path, output_path, manifest, rainfall_path=None):
    """Convert only explicitly identified representatives; no name becomes an official ID.

    Manifest stations must provide source_station_name and source_note alongside
    approved station_id/unit. Rain is joined only by the explicitly supplied
    rainfall_station_name (raw file) or rainfall_station_id (separate rain CSV).
    Conflicting rain station/day values are never resolved by averaging.
    """
    validate_manifest(manifest, require_all=False)
    stations = manifest['stations']
    for station in stations:
        if not station.get('source_station_name') or not station.get('source_note'):
            raise ValueError('source_station_name and source_note are required for explicit source identity/unit evidence')
    rain_groups = {}
    source_path = Path(source_path)
    with source_path.open(encoding='utf-8-sig',newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'관측소 이름','관측일자','지하수위','일일강수량'} <= set(reader.fieldnames or []):
            raise ValueError('Expected Korean joined groundwater CSV')
        for row in reader:
            try:
                raw = row['관측일자']
                if len(raw) != 8 or not raw.isdigit():
                    continue
                day = date(int(raw[:4]),int(raw[4:6]),int(raw[6:8]))
                rain = float(row['일일강수량'])
                name = row.get('강수량_측정소이름','').strip()
                if name and day <= date.today() and math.isfinite(rain) and rain >= 0:
                    rain_groups.setdefault((name,day),set()).add(rain)
            except (ValueError,TypeError):
                continue
    if rainfall_path:
        with Path(rainfall_path).open(encoding='utf-8-sig',newline='') as stream:
            reader = csv.DictReader(stream)
            if not {'rainfall_station_id','date','rainfall_mm'} <= set(reader.fieldnames or []):
                raise ValueError('Rain CSV requires rainfall_station_id,date,rainfall_mm')
            for row in reader:
                try:
                    day = date.fromisoformat(row['date'])
                    rain = float(row['rainfall_mm'])
                    if day <= date.today() and math.isfinite(rain) and rain >= 0:
                        rain_groups.setdefault((row['rainfall_station_id'],day),set()).add(rain)
                except (ValueError,TypeError):
                    continue
    by_name = {station['source_station_name']:station for station in stations}
    if len(by_name) != len(stations):
        raise ValueError('Source station names must identify distinct representatives')
    output_rows = []
    skipped = {'missing_or_conflicting_rain':0,'invalid_water_or_date':0,'district_mismatch':0}
    district_names = {item['district_code']:item['district_name'] for item in DISTRICTS}
    with source_path.open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            station = by_name.get(row.get('관측소 이름','').strip())
            if station is None:
                continue
            if row.get('구','').strip() != district_names[station['district_code']]:
                skipped['district_mismatch'] += 1
                continue
            try:
                raw = row['관측일자']
                if len(raw) != 8 or not raw.isdigit():
                    raise ValueError('Expected YYYYMMDD')
                day = date(int(raw[:4]),int(raw[4:6]),int(raw[6:8]))
                level = float(row['지하수위'])
                if day > date.today() or not math.isfinite(level):
                    raise ValueError('Invalid value/date')
            except (ValueError,TypeError):
                skipped['invalid_water_or_date'] += 1
                continue
            rain_name = station.get('rainfall_station_id') if rainfall_path else station.get('rainfall_station_name')
            rain_values = rain_groups.get((rain_name,day),set())
            if len(rain_values) != 1:
                skipped['missing_or_conflicting_rain'] += 1
                continue
            output_rows.append(dict(station_id=station['station_id'],district_code=station['district_code'],date=day.isoformat(),groundwater_level=level,rainfall_mm=next(iter(rain_values)),level_unit=station['level_unit']))
    with Path(output_path).open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)
    dataset = load_canonical(output_path,manifest)
    dataset.report['conversion'] = {'output_rows':len(output_rows),'skipped':skipped,
                                    'source_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),
                                    'rain_conflict_groups':sum(len(values)>1 for values in rain_groups.values()),
                                    'rain_join_policy':'explicit manifest rain station/date, no imputation'}
    return dataset


def gap_aware_split(windows, replay_start, train_min=180, validation_days=60, test_days=60, replay_days=90, train_max_targets=None):
    """Chronological split of already calendar-valid windows; never bridge a gap.

    Validation/test use the latest complete continuous target blocks before the
    next partition. Replay has an explicit common target start. Historical
    training windows may be separated by calendar gaps; each input window remains
    continuous and no later label can enter an earlier partition.
    """
    if isinstance(replay_start, str):
        replay_start = date.fromisoformat(replay_start)
    if any(n < 1 for n in (train_min, validation_days, test_days, replay_days)):
        raise ValueError('Partition sizes must be positive')
    windows = sorted(windows, key=lambda w:w.target_date)
    if len({w.target_date for w in windows}) != len(windows):
        raise ValueError('Duplicate target dates')
    if len({(w.station_id, w.district_code) for w in windows}) > 1:
        raise ValueError('Partitions cannot mix stations')
    def latest_block(before, size):
        groups = []
        for item in (w for w in windows if w.target_date < before):
            if not groups or item.target_date-groups[-1][-1].target_date != timedelta(days=1):
                groups.append([])
            groups[-1].append(item)
        candidates = [group[-size:] for group in groups if len(group) >= size]
        if not candidates:
            raise ValueError(f'No continuous {size}-target block before {before}')
        return candidates[-1]
    end = replay_start+timedelta(days=replay_days-1)
    replay = [w for w in windows if replay_start <= w.target_date <= end]
    if len(replay) != replay_days or any(b.target_date-a.target_date != timedelta(days=1) for a,b in zip(replay,replay[1:])):
        raise ValueError('Replay requires continuous targets at the explicit common dates')
    test = latest_block(replay_start, test_days)
    validation = latest_block(test[0].target_date, validation_days)
    train = [w for w in windows if w.target_date < validation[0].target_date]
    if train_max_targets is not None:
        if not isinstance(train_max_targets, int) or train_max_targets < train_min:
            raise ValueError('train_max_targets must be an integer at least train_min')
        train = train[-train_max_targets:]
    if len(train) < train_min:
        raise ValueError('Insufficient historical training targets')
    return {'train':train,'validation':validation,'test':test,'replay':replay}
