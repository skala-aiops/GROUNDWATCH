import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from data.groundwater import (Observation, FeatureScaler, continuous_windows,
                             chronological_split, load_canonical, validate_manifest, convert_korean_source, gap_aware_split)


class GroundwaterDataTest(unittest.TestCase):
    def write(self, rows):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)/'data.csv'
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer = csv.DictWriter(stream,fieldnames=['station_id','district_code','date','groundwater_level','rainfall_mm','level_unit'])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def row(self, day='2020-01-01', level=-1, rain=0):
        return dict(station_id='official-1',district_code='11110',date=day,groundwater_level=level,rainfall_mm=rain,level_unit='source-unit')

    def test_bom_zero_and_negative_level_are_valid_missing_rain_is_not_zero(self):
        dataset = load_canonical(self.write([self.row(),self.row('2020-01-02',0,''),self.row('2020-01-03',0,0)]))
        self.assertEqual(len(dataset.records),2)
        self.assertEqual(dataset.report['invalid_rows'],1)
        self.assertEqual(dataset.records[0].groundwater_level,-1)

    def test_conflicting_group_fully_quarantined_exact_duplicates_collapsed(self):
        dataset = load_canonical(self.write([self.row(),self.row(),self.row('2020-01-02',2),self.row('2020-01-02',3)]))
        self.assertEqual(len(dataset.records),1)
        self.assertEqual(dataset.report['exact_duplicates_removed'],1)
        self.assertEqual(dataset.report['conflicting_groups'],1)

    def test_gap_cannot_be_treated_as_twenty_days(self):
        records = [Observation('a','11110',date(2020,1,1)+timedelta(days=i+(i>=10)),float(i),0,'m','v') for i in range(22)]
        self.assertEqual(continuous_windows(records),[])

    def test_split_targets_ordered_and_scaler_fits_only_training(self):
        records = [Observation('a','11110',date(2020,1,1)+timedelta(days=i),float(i),0,'m','v') for i in range(410)]
        parts = chronological_split(continuous_windows(records))
        self.assertEqual(parts['train'][0].inputs[-1][0], 19)
        self.assertEqual(parts['train'][0].target, 20)
        self.assertEqual([len(parts[x]) for x in ('train','validation','test','replay')],[180,60,60,90])
        self.assertLess(parts['train'][-1].target_date,parts['validation'][0].target_date)
        scaler = FeatureScaler.fit([(r.groundwater_level,r.rainfall_mm) for r in records[:200]])
        self.assertEqual(scaler.means[0],99.5)
        self.assertAlmostEqual(scaler.inverse_level(scaler.transform([(300,0)])[0][0]),300)

    def test_manifest_needs_explicit_approval_and_no_station_switch(self):
        manifest = {'approved':False,'mapping_version':'v1','stations':[]}
        with self.assertRaises(ValueError):
            validate_manifest(manifest)
        manifest = {'approved':True,'mapping_version':'v1','stations':[dict(station_id='official-1',district_code='11110',level_unit='source-unit')]}
        dataset = load_canonical(self.write([self.row()]),manifest)
        self.assertTrue(dataset.metadata_for_district('11110')['manifest_approved'])
        with self.assertRaises(ValueError):
            validate_manifest(manifest)

    def test_conversion_joins_explicit_rain_station_and_quarantines_water_conflict(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        source = Path(directory.name)/'raw.csv'
        source.write_text('관측소 이름,구,관측일자,지하수위,일일강수량,강수량_측정소이름\n대표,종로구,20200101,-2,,\n다른관측소,종로구,20200101,3,5,강수원천\n대표,종로구,20200102,4,0,강수원천\n대표,종로구,20200102,7,0,강수원천\n',encoding='utf-8-sig')
        manifest = {'approved':True,'mapping_version':'v1','stations':[dict(station_id='official',district_code='11110',level_unit='m',source_station_name='대표',source_note='fixture explicit source confirmation',rainfall_station_name='강수원천')]}
        dataset = convert_korean_source(source,Path(directory.name)/'canonical.csv',manifest)
        self.assertEqual(len(dataset.records),1)
        self.assertEqual(dataset.records[0].rainfall_mm,5)
        self.assertEqual(dataset.records[0].groundwater_level,-2)
        self.assertEqual(dataset.report['conflicting_groups'],1)

    def test_malformed_manifest_is_validation_error(self):
        for stations in ([1], {'a':1}, [{'district_code':11110,'station_id':'x','level_unit':'m'}]):
            with self.assertRaises(ValueError):
                validate_manifest({'approved':True,'mapping_version':'x','stations':stations},require_all=False)

    def test_official_chart_parser_retains_negative_level_and_excludes_missing_rain(self):
        from scripts.import_official_groundwater import parse_chart
        text = 'categories1[0]="2024-01-01"; seriesData1[0]=-23.03; seriesData4[0]=0; categories1[1]="2024-01-02"; seriesData1[1]=-23; seriesData4[1]=null;'
        rows,invalid=parse_chart(text)
        self.assertEqual(rows,[(date(2024,1,1),-23.03,0.0)])
        self.assertEqual(invalid,1)

    def test_gap_aware_split_never_bridges_gap_or_leaks_replay(self):
        base=date(2020,1,1)
        records=[Observation('a','11110',base+timedelta(days=i),float(i),0,'m','v') for i in range(650) if i!=250]
        windows=continuous_windows(records)
        parts=gap_aware_split(windows,base+timedelta(days=560))
        self.assertEqual([len(parts[k]) for k in ('validation','test','replay')],[60,60,90])
        self.assertGreaterEqual(len(parts['train']),180)
        capped=gap_aware_split(windows,base+timedelta(days=560),train_max_targets=180)
        self.assertEqual(len(capped['train']),180)
        self.assertEqual(capped['train'][-1].target_date,parts['train'][-1].target_date)
        with self.assertRaises(ValueError):
            gap_aware_split(windows,base+timedelta(days=560),train_max_targets=179)
        self.assertLess(parts['train'][-1].target_date,parts['validation'][0].target_date)
        self.assertLess(parts['test'][-1].target_date,parts['replay'][0].target_date)
        self.assertFalse(any(base+timedelta(days=250)<=w.target_date<=base+timedelta(days=270) for w in windows))
        with self.assertRaises(ValueError):
            gap_aware_split([w for w in windows if w.target_date!=base+timedelta(days=600)],base+timedelta(days=560))


if __name__ == '__main__':
    unittest.main()
