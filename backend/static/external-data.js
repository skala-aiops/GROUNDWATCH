'use strict';
(() => {
  const element = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const names = {seoul:'서울시',kma:'기상청'};
  const labels = {queued:'대기',running:'수집 중',completed:'수집 작업 종료',failed:'실패',interrupted:'중단',collected:'자료 확보',empty:'기간 내 유효 자료 없음'};
  const day = offset => {const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const values=Object.fromEntries(parts.map(p=>[p.type,p.value])); const d=new Date(`${values.year}-${values.month}-${values.day}T00:00:00Z`);d.setUTCDate(d.getUTCDate()+offset);return d.toISOString().slice(0,10);};
  element('external-start').value=day(-7);element('external-end').value=day(-1);
  element('external-start').max=day(-1);element('external-end').max=day(-1);
  async function request(path, options) {
    const response=await fetch('/api/v1'+path,options);const data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:`HTTP ${response.status}`);
    return data;
  }
  async function load() {
    try {
      const [data,freshness]=await Promise.all([request('/external-sources'),request('/data-freshness')]);
      if(element('live-data-summary'))element('live-data-summary').textContent=`오늘 예측 대상 ${freshness.target_date} · 필요 입력 종료 ${freshness.input_end_date} · 연속20일 준비 ${freshness.data_ready_count}/25 · 관측 revision ${freshness.repository.counts.source_revisions}개 / 품질 기록 ${freshness.repository.counts.quality_findings}개. API 자료는 기존 과거 재생과 분리합니다.`;
      element('external-status').textContent=Object.entries(data.sources).map(([name,value])=>`${names[name]} 키: ${value.configured?'설정됨':'없음'}`).join(' · ')+' · 예측 적용: 관측소·단위·모델 검증 대기';
      element('external-jobs').innerHTML=data.jobs.length?data.jobs.slice(0,10).map(job=>`<div class="record"><strong>${safe(labels[job.status]||job.status)} · ${safe(job.payload.start_date)} ~ ${safe(job.payload.end_date)}</strong><p>${safe(job.payload.seoul_station)} · ASOS ${safe(job.payload.weather_station)}</p>${Object.entries(job.result?.sources||{}).map(([name,r])=>`<p>${names[name]}: ${safe(labels[r.status]||r.status)} · 수신 ${r.received_rows} / 유효 ${r.accepted_rows} / 격리 ${r.quarantined_rows} · 최근 유효 관측일 ${safe(r.latest_observed_date||'없음')}${r.error?' · '+safe(r.error):''}</p>`).join('')}${['failed','interrupted'].includes(job.status)?`<button data-ingestion-retry="${safe(job.id)}">수집 재시도</button>`:''}<p class="footnote">예측 자료 적용: ${job.result?.applied_to_forecasts?'적용됨':'검증 대기'}</p></div>`).join(''):'<p>아직 수집 작업이 없습니다.</p>';
    }catch(error){element('external-status').textContent='수집 상태 조회 실패: '+error.message;}
  }
  element('external-refresh').addEventListener('click',load);
  element('external-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
    try {await request('/ingestions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});await load();}
    catch(error){element('external-status').textContent='수집 요청 실패: '+error.message;}
    finally{button.disabled=false;}
  });
  element('external-jobs').addEventListener('click',async event=>{const button=event.target.closest('[data-ingestion-retry]');if(!button)return;button.disabled=true;try{await request('/ingestions/'+encodeURIComponent(button.dataset.ingestionRetry)+'/retry',{method:'POST'});await load();}catch(error){element('external-status').textContent=error.message;}finally{button.disabled=false;}});
  load();setInterval(()=>{if(!document.hidden&&!element('operations').hidden)load();},30000);
})();
