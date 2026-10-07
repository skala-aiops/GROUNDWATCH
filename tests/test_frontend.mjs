import {test} from 'node:test';
import assert from 'node:assert/strict';
import {APIClient,APIError,dateWindows,addDays,segments,escapeHTML,isActive} from '../serving_app/static/client.mjs';
const response=(data,cursor=null,status=200)=>({ok:status<400,status,json:async()=>({data,meta:{next_cursor:cursor,request_id:'trace'}})});
test('fetches every cursor with original filters',async()=>{
  const urls=[];const client=new APIClient(async url=>{urls.push(url);return urls.length===1?response([1,2],'opaque+/='):response([3]);});
  assert.deepEqual(await client.all('/wells/id/observations',{dataset_id:'version',from:'2025-01-01'}),[1,2,3]);
  const url=new URL(urls[1],'http://localhost');assert.equal(url.searchParams.get('cursor'),'opaque+/=');assert.equal(url.searchParams.get('dataset_id'),'version');assert.equal(url.searchParams.get('from'),'2025-01-01');
});
test('detects repeated cursors instead of looping',async()=>{const client=new APIClient(async()=>response([1],'same'));await assert.rejects(client.all('/list'),e=>e.code==='INVALID_RESPONSE');});
test('uncertain mutation uses the same idempotency key after a reload',async()=>{
  const store=new Map(), storage={getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};
  const keys=[];let attempt=0;
  const fetcher=async(url,opts)=>{keys.push(opts.headers['Idempotency-Key']);if(!attempt++)throw new TypeError('offline');return response({id:'one'});};
  const first=new APIClient(fetcher,storage,()=> 'key-1');await assert.rejects(first.mutate('/analyses',{dataset_id:'a'}));
  const reloaded=new APIClient(fetcher,storage,()=> 'key-2');await reloaded.mutate('/analyses',{dataset_id:'a'});
  assert.deepEqual(keys,['key-1','key-1']);assert.equal(store.size,0);
  await reloaded.mutate('/analyses',{dataset_id:'b'});assert.equal(keys[2],'key-2');
});
test('different input never reuses uncertain request key',async()=>{
  const keys=[];let i=0;const client=new APIClient(async(url,opts)=>{keys.push(opts.headers['Idempotency-Key']);throw new TypeError('offline');},null,()=>String(++i));
  await assert.rejects(client.mutate('/analyses',{from:'2025-01-01'}));await assert.rejects(client.mutate('/analyses',{from:'2025-02-01'}));assert.deepEqual(keys,['1','2']);
});
test('abort remains abort rather than showing a network error',async()=>{const abort=new DOMException('cancel','AbortError');const client=new APIClient(async()=>{throw abort;});await assert.rejects(client.all('/list'),e=>e===abort);});
test('propagates errors and row details without discarding request id',async()=>{
  const client=new APIClient(async()=>({ok:false,json:async()=>({error:{code:'INVALID_DATA',message:'bad row',details:[{row:7,field:'rainfall_mm'}]},meta:{request_id:'trace'}})}));
  await assert.rejects(client.request('/upload'),e=>e instanceof APIError&&e.details[0].row===7&&e.requestId==='trace');
});
test('splits long inclusive ranges without gaps or overlaps',()=>{
  const end=addDays('2020-01-01',1800), windows=dateWindows('2020-01-01',end);assert.equal(windows.length,3);assert.equal(windows[2][1],end);
  for(let i=1;i<windows.length;i++)assert.equal(addDays(windows[i-1][1],1),windows[i][0]);
  assert.equal(dateWindows('2025-01-01',addDays('2025-01-01',755)).length,1);assert.throws(()=>dateWindows('2025-02-01','2025-01-01'));
});
test('missing dates split lines instead of inventing continuity',()=>{assert.deepEqual(segments([{day:'2025-01-01'},{day:'2025-01-02'},{day:'2025-01-04'}],'day').map(s=>s.length),[2,1]);});
test('untrusted names cannot become DOM markup',()=>{assert.equal(escapeHTML('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');});
test('only accepted and running jobs continue polling',()=>{for(const status of ['succeeded','failed','interrupted'])assert.equal(isActive({status}),false);assert.equal(isActive({status:'queued'}),true);assert.equal(isActive({status:'running'}),true);});
