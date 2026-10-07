import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import requests
from serving_app.external_observations import OfficialClient, SourceError, ExternalObservations, valid_rows

class Response:
    status_code=200
    def __init__(self,data):self.data=data
    def json(self):return self.data

class Session:
    def __init__(self,response=None,error=None):self.response=response;self.error=error;self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        if self.error:raise self.error
        return self.response

class ExternalTests(unittest.TestCase):
    def test_shared_weather_is_collected_once_per_schedule_day_and_completion_can_refresh(self):
        class Client:
            weather_calls=0
            def seoul_page(self,*args):return {'ok':True},[],0
            def kma_page(self,*args):
                self.weather_calls+=1
                return {'ok':True},[{'tm':'2024-03-01','stnId':'108','sumRn':'0'}],1
        with tempfile.TemporaryDirectory() as tmp:
            client=Client();service=ExternalObservations(tmp,client)
            first=service.enqueue('2024-03-01','2024-03-03','A','108','2024-03-04')
            second=service.enqueue('2024-03-01','2024-03-03','B','108','2024-03-04')
            service.execute_one();service.execute_one()
            self.assertEqual(client.weather_calls,1)
            self.assertEqual(service.store.job(second['id'])['result']['sources']['kma']['shared_collection_job_id'],first['id'])
            service.enqueue('2024-03-01','2024-03-03','A','108')
            service.execute_one()
            self.assertEqual(client.weather_calls,2)
    def test_future_missing_and_conflicts_are_quarantined(self):
        rows=[{'tm':'2026-10-01','stnId':'108','sumRn':'0'},
              {'tm':'2026-10-02','stnId':'108','sumRn':''},
              {'tm':'2026-10-03','stnId':'108','sumRn':'1'},
              {'tm':'2026-10-03','stnId':'108','sumRn':'2'},
              {'tm':'2041-01-30','stnId':'108','sumRn':'1'}]
        accepted,rejected=valid_rows(rows,'kma','2026-10-01','2026-10-06','108',date(2026,10,7))
        self.assertEqual(accepted,[{'source':'kma','source_station':'108','date':'2026-10-01','value':0}])
        self.assertEqual({r['reason'] for r in rejected},{'missing_value','conflicting_observation','future_or_unfinished_day'})
    def test_negative_groundwater_preserved_wrong_station_rejected(self):
        rows=[{'OBSRVN_YMD':'20261001','OBSVTR_NM':'A','UDGD_WATL':-23.4},
              {'OBSRVN_YMD':'20261002','OBSVTR_NM':'B','UDGD_WATL':2}]
        good,bad=valid_rows(rows,'seoul','2026-10-01','2026-10-06','A',date(2026,10,7))
        self.assertEqual(good[0]['value'],-23.4);self.assertEqual(bad[0]['reason'],'station_mismatch')
    @patch.dict('os.environ',{'SEOUL_OPEN_DATA_KEY':'secret-key-value'})
    def test_exception_never_echoes_key_url(self):
        session=Session(error=requests.ConnectionError('http://host/secret-key-value'))
        with patch('time.sleep'):
            with self.assertRaises(SourceError) as ctx:OfficialClient(session).seoul_page(1,5,'A')
        self.assertNotIn('secret-key-value',str(ctx.exception))
        self.assertFalse(session.calls[0][1]['allow_redirects'])
    @patch.dict('os.environ',{'KMA_ASOS_SERVICE_KEY':'encoded%2Bkey'})
    def test_encoded_key_is_decoded_once_and_provider_error_is_safe(self):
        session=Session(Response({'response':{'header':{'resultCode':'30','resultMsg':'encoded+key'}}}))
        with self.assertRaises(SourceError) as ctx:OfficialClient(session).kma_page('2026-10-01','2026-10-02','108',1)
        self.assertNotIn('encoded',str(ctx.exception))
        self.assertEqual(session.calls[0][1]['params']['ServiceKey'],'encoded+key')
    def test_empty_seoul_and_failed_kma_never_replace_existing_dataset(self):
        class Client:
            def seoul_page(self,*args):return {'RESULT':{'CODE':'INFO-200'}},[],0
            def kma_page(self,*args):raise SourceError('kma: HTTP 403')
        with tempfile.TemporaryDirectory() as tmp:
            existing=Path(tmp)/'old.csv';existing.write_text('keep')
            service=ExternalObservations(tmp,Client())
            job=service.enqueue('2024-03-01','2024-03-03','A','108')
            self.assertTrue(service.execute_one())
            result=service.store.job(job['id'])
            self.assertEqual(result['status'],'failed');self.assertEqual(result['result']['collection_status'],'partial')
            self.assertFalse(result['result']['applied_to_forecasts']);self.assertEqual(existing.read_text(),'keep')
            self.assertEqual(result['result']['sources']['seoul']['status'],'empty')
    def test_duplicate_job_and_restart_preserve_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=ExternalObservations(tmp)
            job=service.enqueue('2024-03-01','2024-03-03','A','108')
            with self.assertRaises(ValueError):service.enqueue('2024-03-01','2024-03-03','A','108')
            service.store.claim()
            recovered=ExternalObservations(tmp);self.assertEqual(recovered.store.recover(),1)
            self.assertEqual(recovered.store.job(job['id'])['status'],'interrupted')
    def test_partial_pages_not_reported_complete(self):
        class Client:
            def seoul_page(self,start,*args):
                if start>1:raise SourceError('seoul: page failed')
                return {'ok':True},[{'OBSRVN_YMD':'20240301','OBSVTR_NM':'A','UDGD_WATL':1}],1500
            def kma_page(self,*args):return {'ok':True},[],0
        with tempfile.TemporaryDirectory() as tmp:
            service=ExternalObservations(tmp,Client());job=service.enqueue('2024-03-01','2024-03-03','A','108')
            service.execute_one();result=service.store.job(job['id'])['result']['sources']['seoul']
            self.assertFalse(result['complete']);self.assertEqual(result['pages'],1)

if __name__=='__main__':unittest.main()
