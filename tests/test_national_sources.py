import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from serving_app.national_sources import import_csv, collect_asos, collect_kwater, join_daily, import_kma_rainy_csv, parse_gims_station_layer, parse_aws_snapshot, collect_aws_snapshot, parse_aws_daily, parse_warning_snapshot, parse_forecast_pages
from serving_app.external_observations import SourceError

class NationalSourcesTests(unittest.TestCase):
    def test_csv_preserves_signed_values_and_quarantines_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'data.csv'
            p.write_text('source_station_id,date,value,unit,datum\nA,2024-01-01,-5,m,elevation\nA,2024-01-02,1,m,elevation\nA,2024-01-02,2,m,elevation\nA,2024-01-03,,m,elevation\nA,2024-01-04,1,cm,elevation\n')
            result=import_csv(p,source='verified_source',today=date(2024,2,1))
            self.assertEqual(len(result['accepted']),1)
            self.assertEqual(result['accepted'][0]['value'],-5)
            self.assertEqual(len(result['quarantined']),4)
            self.assertEqual(len(result['raw_sha256']),64)

    def test_seasons_are_retrospective_not_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'season.csv';p.write_text('year,region,start_date,end_date\n2024,중부,2024-06-20,2024-07-20\n2024,제주,2024-07-20,2024-06-20\n')
            result=import_csv(p,source='kma',kind='rainy_seasons',today=date(2025,1,1))
            self.assertEqual(result['accepted'][0]['purpose'],'retrospective_evaluation_only')
            self.assertEqual(len(result['quarantined']),1)

    def test_backfill_chunks_raw_redaction_and_no_zero_fill(self):
        class Client:
            calls=[]
            def kma_page(self,start,end,station,page):
                self.calls.append((start,end,page))
                return {'echo':'test-secret'},[{'tm':start,'stnId':station,'sumRn':'0'}, {'tm':end,'stnId':station,'sumRn':''}],2
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'KMA_ASOS_SERVICE_KEY':'test-secret'}):
            client=Client();result=collect_asos('2024-01-01','2024-02-02','108',output_dir=tmp,client=client,today=date(2025,1,1))
            self.assertEqual(len(client.calls),2)
            self.assertEqual(client.calls[0][:2],('2024-01-01','2024-01-31'))
            self.assertEqual(len(result['accepted']),2)
            self.assertEqual(len(result['quarantined']),2)
            for path in Path(tmp).glob('*.json'):self.assertNotIn('test-secret',path.read_text())

    def test_partial_or_changing_pagination_fails(self):
        class Client:
            def kma_page(self,*args):return {},[],3
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SourceError):collect_asos('2024-01-01','2024-01-03','108',output_dir=tmp,client=Client())
        with patch.dict(os.environ,{'GIMS_API_KEY':''}),self.assertRaisesRegex(SourceError,'kwater_auth_required'):
            collect_kwater('2024-01-01','2024-01-03','65004',output_dir='/tmp')

    def test_join_missing_and_available_cutoff(self):
        base=dict(date='2024-01-01',unit='m',metric='groundwater_level',datum='elevation',value=-1,quality='valid',raw_sha256='a'*64,available_at='2024-01-02T00:00:00Z',collected_at='2024-01-02T00:00:00Z')
        rain={**base,'metric':'rainfall_mm','unit':'mm','value':0,'raw_sha256':'b'*64,'available_at':'2024-01-03T00:00:00Z'}
        result=join_daily([base],[rain],station_id='provider:A')
        self.assertEqual(result['accepted'][0]['available_at'],'2024-01-03T00:00:00+00:00')
        self.assertEqual(result['accepted'][0]['groundwater_level'],-1)
        self.assertEqual(len(join_daily([base],[],station_id='provider:A')['quarantined']),1)


    def test_kwater_raw_only_chunks_and_redaction(self):
        class Client:
            calls=[]
            def _json(self,source,url,params):
                self.calls.append((source,url,params))
                return {'unknownEnvelope': {'echo':params['KEY'],'elev':'4.3'}}
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'GIMS_API_KEY':'secret%2Bkey'}):
            client=Client();result=collect_kwater('2024-01-01','2024-02-01','65004',output_dir=tmp,client=client,today=date(2025,1,1))
            self.assertEqual(len(client.calls),2)
            self.assertEqual(client.calls[0][2]['enddate'],'20240131')
            self.assertEqual(client.calls[0][2]['KEY'],'secret+key')
            self.assertEqual(result['accepted'],[])
            self.assertEqual(result['status'],'raw_collected_not_validated')
            self.assertFalse(result['applied_to_forecasts'])
            self.assertIn('level_spec_and_response_unverified',result['blockers'])
            for p in Path(tmp).glob('*.json'):
                self.assertNotIn('secret',p.read_text())

    def test_kwater_failures_never_leak_url_or_key(self):
        class Client:
            def _json(self,*args):raise RuntimeError('https://example.test/?KEY=secret-key')
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'GIMS_API_KEY':'secret-key'}):
            with self.assertRaises(SourceError) as ctx:
                collect_kwater('2024-01-01','2024-01-02','65004',output_dir=tmp,client=Client())
            self.assertEqual(str(ctx.exception),'kwater_collection_failed')
            self.assertEqual(list(Path(tmp).glob('*.json')),[])


    def test_actual_kma_export_preamble_dates_and_idempotent_import(self):
        from serving_app.national_repository import NationalRepository
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.csv'
            text='\r\n[검색조건]지점 :전체 , 기간 : 19730101 ~ 20261231\r\n지점번호,지점명,시작일,종료일,장마일수,강수일수,합계강수량\r\n108,서울,2024-06-20,2024-06-21,2,0,\r\n90,속초,,2024-06-21,2,0,\r\n'
            p.write_bytes(text.encode('cp949'))
            root=Path(tmp)/'output'
            result=import_kma_rainy_csv(p,output_dir=root,today=date(2025,1,1))
            self.assertEqual(result['raw_rows'],2)
            self.assertEqual(len(result['accepted']),1)
            self.assertEqual(result['accepted'][0]['region_code'],'kma_asos:108')
            self.assertEqual(result['missing_rainfall_summary_rows'],1)
            again=import_kma_rainy_csv(p,output_dir=root,today=date(2025,1,1))
            self.assertEqual(result['accepted'],again['accepted'])
            repo=NationalRepository(Path(tmp)/'db.sqlite3')
            for item in result['accepted']+again['accepted']:repo.add_rainy_period(item)
            self.assertEqual(len(repo.rainy_periods()),1)


    def test_map_coordinates_quarantine_nan_and_never_approve(self):
        good={'attributes':{'GENNUM':65004,'OBSVRNAME':'test','SIDO_NM':'전라남도','SIGUNGU_NM':'강진군'},'geometry':{'x':126.7,'y':34.5}}
        bad={'attributes':{'GENNUM':65005},'geometry':{'x':'NaN','y':'NaN'}}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'map.json';p.write_text(json.dumps({'spatialReference':{'wkid':4326},'features':[good,bad]}))
            result=parse_gims_station_layer(p)
            self.assertEqual(len(result['accepted']),1)
            self.assertEqual(len(result['quarantined']),1)
            self.assertFalse(result['accepted'][0]['verified'])
            self.assertEqual(result['accepted'][0]['level_unit'],'unverified')
            p.write_text(json.dumps({'spatialReference':{'wkid':3857},'features':[good]}))
            with self.assertRaises(ValueError):parse_gims_station_layer(p)


    def test_rainfall_cli_checkpoint_reuses_verified_request_and_result(self):
        from scripts.collect_national_rainfall import collect
        with tempfile.TemporaryDirectory() as tmp:
            stations=Path(tmp)/'stations.json';stations.write_text(json.dumps([{'source_station_id':'108'}]))
            result={'accepted':[{'date':'2024-01-01','value':1}], 'quarantined':[]}
            with patch('scripts.collect_national_rainfall.collect_asos',return_value=result) as fetch:
                first=collect(stations,[('2024-01-01','2024-01-02')],Path(tmp)/'out',1)
                again=collect(stations,[('2024-01-01','2024-01-02')],Path(tmp)/'out',1)
                self.assertEqual(fetch.call_count,1)
                self.assertEqual(first['failed'],0)
                self.assertEqual(again['results'][0]['status'],'cached')
            with patch('scripts.collect_national_rainfall.collect_asos',side_effect=RuntimeError('KEY=secret')):
                failed=collect(stations,[('2024-02-01','2024-02-02')],Path(tmp)/'out',1)
                self.assertEqual(failed['failed'],1)
                self.assertNotIn('secret',json.dumps(failed))


    def test_aws_minute_contract_sentinel_and_coordinate_validity(self):
        from serving_app.national_sources import AWS_MIN_COLUMNS
        with tempfile.TemporaryDirectory() as tmp:
            raw=Path(tmp)/'aws.txt';meta=Path(tmp)/'meta.csv'
            header='#START7777\n# *) -50 이하면 관측이 없거나, 에러처리된 것을 표시\n# '+' '.join(AWS_MIN_COLUMNS)+'\n'
            values=['202610071200','108']+['0']*16
            values[10]='-99.9';values[11]='0';values[12]='1.5';values[13]='2'
            raw.write_text(header+' '.join(values)+'\n#7777END\n')
            meta.write_bytes('지점,시작일,종료일,지점명,위도,경도\n108,2000-01-01,,서울,37.5,127\n'.encode('cp949'))
            r=parse_aws_snapshot(raw,meta,requested_at='202610071200')
            self.assertIsNone(r['observations'][0]['rainfall_mm']['RN-15m'])
            self.assertEqual(r['observations'][0]['rainfall_mm']['RN-60m'],0)
            self.assertEqual(r['coordinates_matched'],1)
            self.assertIn('not_completed_daily',r['temporal_contract'])
            raw.write_text(header+' '.join(values)+'\n'+' '.join(values)+'\n#7777END\n')
            with self.assertRaises(ValueError):parse_aws_snapshot(raw,meta,requested_at='202610071200')

    def test_aws_transport_redacts_exceptions(self):
        class Session:
            def get(self,*args,**kwargs):raise RuntimeError('authKey=secret')
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'KMA_APIHUB_KEY':'secret'}):
            with self.assertRaisesRegex(SourceError,'aws_collection_failed') as ctx:
                collect_aws_snapshot('202610071200',output_dir=tmp,session=Session())
            self.assertNotIn('secret',str(ctx.exception))


    def test_aws_daily_source_coordinates_zero_and_completed_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'daily.txt'
            prefix='#START7777\n# YYMMDD STN LON LAT HT VAL\n'
            p.write_bytes((prefix+'20261007 108 126.9 37.5 85 0.0 서울 관측소\n20261007 90 128.5 38.2 17 -99.9 속초\n#7777END\n').encode('cp949'))
            r=parse_aws_daily(p,requested_date='20261007',today=date(2026,10,8))
            self.assertEqual(len(r['observations']),1)
            self.assertEqual(r['observations'][0]['rainfall_mm'],0)
            self.assertEqual(r['stations'][0]['name'],'서울 관측소')
            self.assertEqual(len(r['quarantined']),1)
            self.assertEqual(r['provider'],'kma_ground_aws_daily')
            with self.assertRaises(ValueError):parse_aws_daily(p,requested_date='20261007',today=date(2026,10,7))


    def test_warning_empty_and_nonempty_are_not_safe_or_no_warning_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'warning.txt'
            header='#START7777\n# REG_UP REG_UP_KO--- REG_ID REG_KO--- TM_FC TM_EF WRN LVL CMD ED_TM\n'
            p.write_bytes(header.encode('cp949'))
            r=parse_warning_snapshot(p)
            self.assertEqual(r['status'],'empty_response_unverified')
            self.assertFalse(r['no_warnings_verified'])
            self.assertFalse(r['complete_snapshot_verified'])
            p.write_bytes((header+'unverified positive row\n').encode('cp949'))
            r=parse_warning_snapshot(p)
            self.assertEqual(r['status'],'nonempty_response_schema_unverified')
            self.assertEqual(r['records'],[])
            p.write_text('invalid key')
            with self.assertRaises(ValueError):parse_warning_snapshot(p)


    def test_forecast_pages_are_complete_grid_matched_and_forecast_only(self):
        rows=[dict(baseDate='20261008',baseTime='0500',nx=55,ny=127,fcstDate='20261008',fcstTime='0600',category=c,fcstValue=v) for c,v in [('POP','30'),('PCP','1mm 미만'),('PTY','1')]]
        data={'response':{'header':{'resultCode':'00'},'body':{'pageNo':1,'numOfRows':1000,'totalCount':3,'items':{'item':rows}}}}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'page.json';p.write_text(json.dumps(data))
            r=parse_forecast_pages([p],base_date='20261008',base_time='0500',nx=55,ny=127)
            self.assertEqual(r['source_kind'],'forecast')
            self.assertFalse(r['observation_compatible'])
            self.assertEqual(r['grid']['mapping_status'],'unverified')
            pcp=next(x for x in r['items'] if x['category']=='PCP')
            self.assertEqual(pcp['value'],'1mm 미만')
            self.assertEqual(pcp['parsed']['upper_mm'],1)
            rows[1]['fcstValue']='0';p.write_text(json.dumps(data))
            numeric=parse_forecast_pages([p],base_date='20261008',base_time='0500',nx=55,ny=127)
            numeric_pcp=next(x for x in numeric['items'] if x['category']=='PCP')
            self.assertEqual(numeric_pcp['parsed']['kind'],'numeric_or_qualitative_code_unverified')
            self.assertEqual(numeric_pcp['unit'],'source_category')
            data['response']['body']['totalCount']=4;p.write_text(json.dumps(data))
            with self.assertRaises(ValueError):parse_forecast_pages([p],base_date='20261008',base_time='0500',nx=55,ny=127)
            data['response']['body']['totalCount']=3;p.write_text(json.dumps(data))
            with self.assertRaises(ValueError):parse_forecast_pages([p],base_date='20261008',base_time='0500',nx=56,ny=127)

    def test_forecast_duplicate_or_missing_categories_rejected(self):
        rows=[dict(baseDate='20261008',baseTime='0500',nx=55,ny=127,fcstDate='20261008',fcstTime='0600',category='POP',fcstValue='30')]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'page.json'
            for values in [rows,rows+rows]:
                data={'response':{'header':{'resultCode':'00'},'body':{'pageNo':1,'numOfRows':1000,'totalCount':len(values),'items':{'item':values}}}}
                p.write_text(json.dumps(data))
                with self.assertRaises(ValueError):parse_forecast_pages([p],base_date='20261008',base_time='0500',nx=55,ny=127)

if __name__=='__main__':unittest.main()
