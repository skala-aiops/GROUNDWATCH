import {APIClient, APIError, addDays, dateWindows, isActive, escapeHTML as h} from './client.mjs';
import {renderChart} from './charts.mjs';
const $ = selector => document.querySelector(selector);
const storage = {getItem: key => {try{return localStorage.getItem(key);}catch{return null;}},setItem:(key,value)=>{try{localStorage.setItem(key,value);}catch{}},removeItem:key=>{try{localStorage.removeItem(key);}catch{}}};
const api = new APIClient(undefined, storage);
const state = {well:null, wells:[], reports:[], modelReport:null, datasets:[], dataset:null, dashboard:null, observations:[], forecasts:[], runs:[], run:null, events:[], page:'overview', mode:'live', range:'60', from:'', to:'', table:false, loading:false, dataError:null, pending:false, kind:'', analysisFrom:'', analysisTo:'', loadedQuery:'', revision:0};
let controller, runController, pollTimer, runRevision = 0;
const num = value => value == null ? '—' : Number(value).toLocaleString('ko-KR',{maximumFractionDigits:2});
const dateTime = value => value ? new Date(value).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '—';
const source = d => d?.source_kind === 'simulated' ? '시뮬레이션' : '실측 자료';
const short = value => value?.slice(0,8) || '—';
const version = d => `V${state.datasets.length-state.datasets.findIndex(x=>x.id===d.id)}`;
const badge = (text, tone='') => `<span class="badge ${tone}">${h(text)}</span>`;
const kv = (label,value) => `<div class="kv"><span>${h(label)}</span><span>${h(value)}</span></div>`;
const modelReady = () => Boolean(state.dashboard?.active_model && !state.loading && !state.dataError && !state.pending);
const modelReason = () => state.loading ? '자료를 불러오는 중입니다.' : state.dataError ? '자료를 새로고침한 뒤 실행할 수 있습니다.' : state.dashboard?.active_model ? '선택한 자료와 연결된 모델로 실행합니다.' : '지하수 예측 모델 연결 대기';
const checkLabels = {within_threshold:['기준 이내','green'],drift:['현장 재확인 필요','amber'],insufficient_data:['판정 자료 부족','neutral'],not_evaluated:['판정 기준 미설정','neutral'],data_invalid:['데이터 확인 필요','red']};
const runLabels = {queued:'접수됨',running:'진행 중',succeeded:'완료',failed:'실패',interrupted:'중단됨'};
const stageLabels = {validate:'입력 확인',predict:'예측',evaluate:'오차 평가',detect:'변화 감지',train:'재학습',register:'모델 등록',gate:'성능 검증',deploy:'모델 적용'};
const eventLabels = {started:'시작',succeeded:'완료',failed:'실패',skipped:'건너뜀'};
function checkStatus(check) {return check ? checkLabels[check.state] || ['판정 전','neutral'] : ['판정 전','neutral'];}
function announce(message, tone='success') {$('#notice').innerHTML = `<div class="notice ${tone}">${h(message)}</div>`;}
function detailText(detail) {
  const labels={observed_date:'관측일',groundwater_depth_cm:'지하수 깊이',rainfall_mm:'강수량',missing_or_extra_value:'빈 값 또는 열 수를 확인하세요',invalid_value_or_nonconsecutive_date:'날짜의 연속성·단위·값을 확인하세요',missing:'필수 항목이 누락되었습니다'};
  return [detail.row!=null?`${detail.row}행`:null,labels[detail.field]||detail.field,labels[detail.reason]||detail.reason].filter(Boolean).join(' · ') || (detail.expected?'필수 열: '+detail.expected.join(', '):'요청 정보 확인 필요');
}
function showError(error, retained=false) {
  if (error.name==='AbortError') return;
  const hints = {CONTRACT_MISMATCH:'현재 모델은 지하수 입력·출력 계약과 맞지 않습니다. 지하수 예측 모델 연결을 기다려 주세요.',MODEL_NOT_READY:'모델 준비가 끝난 뒤 다시 시도하세요.',RETRAIN_NOT_READY:'자동 재학습 연결이 준비되지 않았습니다.',RUN_IN_PROGRESS:'진행 중인 작업이 끝난 뒤 다시 실행하세요.',LINEAGE_CONFLICT:'이미 이어진 버전입니다. 가장 최근 버전을 선택해 등록하세요.',FORECAST_EXISTS:'같은 자료·모델의 예측이 이미 있습니다. 새로고침하여 확인하세요.',MODEL_CHANGED:'모델이 변경되었습니다. 새로고침 후 다시 실행하세요.',IDEMPOTENCY_CONFLICT:'요청 내용이 달라졌습니다. 입력값을 확인한 뒤 다시 실행하세요.'};
  const existing = error.details?.find(d=>d.existing_run_id)?.existing_run_id;
  $('#notice').innerHTML = `<div class="notice error" role="alert"><strong>${h(error.message)}</strong>${hints[error.code]?`<p>${h(hints[error.code])}</p>`:''}${retained?'<p>아래는 마지막으로 조회에 성공한 자료입니다. 현재 상태와 다를 수 있습니다.</p>':''}${error.details?.length?`<ul>${error.details.map(d=>`<li>${h(detailText(d))}</li>`).join('')}</ul>`:''}<button data-action="refresh">새로고침</button>${existing?`<button data-run="${h(existing)}">진행 중인 실행 보기</button>`:''}${error.requestId?`<details><summary>문의용 정보</summary><span class="mono">${h(error.code)} · ${h(error.requestId)}</span></details>`:''}</div>`;
}
function stopPolling() {clearTimeout(pollTimer);runController?.abort();runRevision++;}
function setRange() {
  if (!state.dataset) return;
  if(state.range!=='custom') {state.to=addDays(state.dataset.end_date,1);state.from=addDays(state.dataset.end_date,-(Number(state.range)-1));}
}
function context() {
  $('#context').innerHTML = `<div class="context-bar"><div><div class="eyebrow">OBSERVATION WELL ${state.well?' / '+h(state.well.code):''}</div><label class="small muted" for="well-select">관측소 선택</label><select id="well-select" ${state.pending?'disabled':''}>${state.wells.map(w=>`<option value="${h(w.id)}" ${w.id===state.well?.id?'selected':''}>${h(w.name)}</option>`).join('')}</select></div><div class="context-select"><label for="dataset-select" class="muted small">조회 버전</label><select id="dataset-select" ${state.pending?'disabled':''} ${!state.datasets.length?'disabled':''}>${state.datasets.length?state.datasets.map(d=>`<option value="${h(d.id)}" ${d.id===state.dataset?.id?'selected':''}>${version(d)} · ${h(source(d))} · ${h(d.original_name)}</option>`).join(''):'<option>등록된 자료 없음</option>'}</select></div></div>`;
}
function heading(number,title,description,button='') {return `<div class="page-heading"><div><div class="section-number">${number} / GROUNDWATCH</div><h1>${title}</h1><p>${description}</p></div>${button}</div>`;}
function blank() {return `<div class="empty panel"><div class="empty-symbol">≋</div><h2>첫 관측 자료를 등록해 주세요</h2><p>관측 날짜, 지하수 깊이, 일 강수량이 담긴 CSV로 시작합니다.</p><button class="primary" data-page="datasets">관측 자료 등록</button></div>`;}
function render() {
  context();
  document.querySelectorAll('nav a').forEach(a=>{if(a.dataset.page===state.page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  $('#view').setAttribute('aria-busy',String(state.loading));
  if(state.page==='models') renderModels(); else if(state.page==='datasets') renderDatasets(); else if(state.page==='operations') renderOperations(); else renderOverview();
}
function checkDetail(check) {
  if(!check) return '';
  return `<details class="check-detail"><summary>판정 근거 ${check.sample_count}/21건 확인</summary>${kv('평가일',check.as_of_date)}${kv('오차 기준',check.threshold_cm==null?'미설정':num(check.threshold_cm)+' cm')}${kv('판정 모델',short(check.model_version_id))}<div class="table-scroll" tabindex="0" aria-label="판정에 사용한 예측 오차"><table><thead><tr><th scope="col">순서</th><th scope="col">예측 식별자</th><th scope="col">실측 − 예측 (cm)</th></tr></thead><tbody>${check.members.map(m=>`<tr><td>${h(m.position)}</td><td title="${h(m.forecast_id)}">${h(short(m.forecast_id))}</td><td>${num(m.residual_cm)}</td></tr>`).join('')}</tbody></table></div></details>`;
}
function renderOverview() {
  const d=state.dataset, dashboard=state.dashboard, last=dashboard?.last_observation, forecast=(state.mode==='replay'||dashboard?.latest_forecast?.target_date===addDays(d?.end_date||'2000-01-01',1))?dashboard?.latest_forecast:null, check=dashboard?.last_check;
  const [label,tone]=checkStatus(check), freshness=dashboard?.data_freshness;
  let output=heading('01','관측 현황','지하수위의 변화와 관측 자료를 한눈에 확인하세요.', '<button class="subtle" data-action="refresh">↻ 새로고침</button>');
  if(!d) {$('#view').innerHTML=output+(state.loading?'<div class="empty panel">자료를 불러오는 중입니다…</div>':blank());return;}
  output+=`<div class="toolbar" style="margin:-8px 0 20px">${badge(source(d))}${badge(state.mode==='live'?'다음 날 예측':'과거 구간 분석','neutral')}<span class="muted small">${h(version(d))} · 마지막 관측 ${h(d.end_date)}</span>${state.loading?'<span class="loading" role="status">조회 중…</span>':`<span class="muted small">· 화면 갱신 ${dateTime(dashboard?.updated_at)} KST</span>`}</div>
${state.modelReport?`<div class="notice research-note"><strong>실측 자료로 학습한 연구용 후보 모델</strong><p>${h(state.modelReport.district)} · ${h(state.modelReport.station)} · 마지막 연속 자료 ${h(state.modelReport.last_date)}. 과거 자료를 재현한 결과이며 실시간 관측이 아닙니다.</p>${state.modelReport.validation_gate_passed?'검증 구간에서 전날 값 유지 기준을 통과했습니다.':'검증 구간에서 전날 값 유지 기준을 통과하지 못했습니다. 개선이 필요한 후보입니다.'} 운영 모델로 자동 승격하지 않았습니다.</div>`:''}<div class="stats"><article class="panel stat"><div class="stat-label">최근 지하수 깊이 ${badge('관측값','neutral')}</div><div class="stat-value">${num(last?.groundwater_depth_cm)}<small>cm</small></div><div class="stat-foot">${h(last?.observed_date || '관측 자료 없음')} · 지표면 기준</div></article><article class="panel stat"><div class="stat-label">${state.mode==='live'?'다음 날 예측 깊이':'최근 과거 예측 깊이'} ${badge(forecast?'예측값':'대기','neutral')}</div><div class="stat-value">${num(forecast?.predicted_depth_cm)}<small>cm</small></div><div class="stat-foot">${forecast?h(forecast.target_date)+' · 모델 v'+h(forecast.model.registry_version):'예측 결과가 아직 없습니다'}</div></article><article class="panel stat"><div class="stat-label">최근 21건 예측 오차 ${badge('RMSE','neutral')}</div><div class="stat-value">${num(check?.rmse_cm)}<small>cm</small></div><div class="stat-foot">${h(check?.sample_count ?? 0)}/21건 · 기준 ${check?.threshold_cm==null?'미설정':num(check.threshold_cm)+' cm'}</div></article></div>
<div class="dashboard-grid"><section class="panel"><div class="panel-head"><div><h2>지하수위 변화 추이</h2><p>관측 깊이와 예측값 · 일 강수량</p></div><div class="toolbar"><label class="small muted" for="mode">보기</label><select id="mode"><option value="live" ${state.mode==='live'?'selected':''}>다음 날 예측</option><option value="replay" ${state.mode==='replay'?'selected':''}>과거 구간 분석</option></select></div></div><div class="chart-toolbar"><div class="segmented" aria-label="조회 기간">${['20','60','custom'].map(r=>`<button data-range="${r}" aria-pressed="${state.range===r}">${r==='custom'?'기간 설정':r+'일'}</button>`).join('')}</div><button class="subtle small" data-action="table">${state.table?'차트 보기':'표 보기'}</button></div>${state.range==='custom'?`<form id="range-form" class="chart-toolbar custom-range"><label>조회 시작일<input type="date" name="from" value="${h(state.from)}" required></label><label>조회 종료일<input type="date" name="to" value="${h(state.to)}" required></label><button type="submit">조회</button></form>`:''}<div class="chart-toolbar legend"><span><i></i>관측 깊이</span><span><i class="forecast"></i>예측 깊이</span><span><i class="rain"></i>강수량</span></div><div id="chart" class="chart-wrap" ${state.table?'hidden':''}></div><div id="observation-table" ${state.table?'':'hidden'}></div><div class="chart-note"><span>깊이가 클수록 지하수위가 낮습니다. ↓</span><span>${h(state.from)} — ${h(state.to)}</span></div></section>
<aside class="stack"><section class="panel panel-pad"><div class="eyebrow">MONITORING STATUS</div><div class="status-icon" aria-hidden="true">${tone==='green'?'✓':tone==='amber'?'!':'○'}</div>${badge(label,tone)}<h2 class="status-title">${check?.state==='drift'?'현장 확인을 진행해 주세요':check?.state==='within_threshold'?'설정된 오차 기준 이내입니다':'판정 근거를 준비하고 있어요'}</h2><p class="description">${check?.state==='drift'?'예측 오차가 설정된 기준을 넘었습니다. 관측 자료와 현장 상황을 함께 확인하세요.':check?.state==='within_threshold'?'예측 오차가 설정 기준 이내입니다. 현장의 안전을 보장하는 의미는 아닙니다.':'동일 모델의 예측과 실측 21건, 합의된 판정 기준이 필요합니다.'}</p><div class="divider"></div>${kv('자료 최신성',({fresh:'최신 기준 충족',stale:'관측 갱신 필요',unknown:'갱신 기준 미설정'})[freshness?.state]||'확인 전')}${kv('마지막 관측일',freshness?.last_observed_date||d.end_date)}${checkDetail(check)}</section><section class="panel panel-pad"><div class="eyebrow">PREDICTION MODEL</div><h3>${dashboard?.active_model?'지하수 예측 모델 연결됨':'지하수 예측 모델 연결 대기'}</h3><p class="model-note" id="model-reason">${dashboard?.active_model?h(dashboard.active_model.registry_name)+' · v'+h(dashboard.active_model.registry_version):'관측 자료는 조회할 수 있습니다. 지하수 모델이 연결되면 예측과 구간 분석을 실행할 수 있습니다.'}</p>${state.modelReport?`${kv('분리 평가 RMSE',num(state.modelReport.test.rmse_cm)+' cm')}${kv('전날 값 유지 RMSE',num(state.modelReport.test_baseline.rmse_cm)+' cm')}${kv('평가 표본',num(state.modelReport.test.count)+'건')}${kv('평가 시작',state.modelReport.test_start_date)}${kv('평가 종료',state.modelReport.test_end_date)}<button class="text-link" data-page="models">25개 구 모델 평가 보기 →</button>`:''}<button class="wide" data-action="predict" aria-describedby="model-reason" ${modelReady()?'':'disabled'}>${state.pending?'처리 중…':'다음 날 예측 실행'}</button><button class="text-link" data-page="operations">운영 이력 확인 →</button></section></aside></div>`;
  $('#view').innerHTML=output;
  if(!state.table) renderChart($('#chart'),state.observations,state.forecasts,state.from,state.to);
  else renderTable();
}
function renderTable() {
  const dates=[...new Set([...state.observations.map(o=>o.observed_date),...state.forecasts.map(f=>f.target_date)])].sort();
  const observed=new Map(state.observations.map(o=>[o.observed_date,o]));
  $('#observation-table').innerHTML=`<div class="table-scroll" tabindex="0" aria-label="날짜별 관측과 예측 자료"><table><caption>${dates.length}개 날짜 · 빈 값은 미관측 또는 예측 없음</caption><thead><tr><th scope="col">관측일</th><th scope="col">깊이 (cm)</th><th scope="col">강수 (mm)</th><th scope="col">예측 (cm) · 모델</th></tr></thead><tbody>${dates.map(day=>{const o=observed.get(day),fs=state.forecasts.filter(f=>f.target_date===day);return `<tr><td>${h(day)}</td><td>${num(o?.groundwater_depth_cm)}</td><td>${num(o?.rainfall_mm)}</td><td>${fs.length?fs.map(f=>`${num(f.predicted_depth_cm)} · ${h(f.model.registry_name)} v${h(f.model.registry_version)} <span class="muted">(자료 ${h(short(f.dataset_id))})</span>`).join('<br>'):'—'}</td></tr>`;}).join('')}</tbody></table></div>`;
}
function renderDatasets() {
  const parents=new Set(state.datasets.map(d=>d.parent_dataset_id));
  const leaves=state.datasets.filter(d=>!parents.has(d.id));
  $('#view').innerHTML=heading('02','데이터 관리','관측 자료를 등록하고, 분석에 사용할 버전을 선택하세요.')+`<div class="data-grid"><section class="panel panel-pad"><h2>관측 자료 등록</h2><p class="description">새 자료를 시작하거나 기존 자료에 새로운 관측일을 이어 붙입니다.</p><form id="upload-form"><div class="upload-zone"><div class="field"><label for="csv-file">CSV 파일</label><input id="csv-file" name="file" type="file" accept=".csv,text/csv" required aria-describedby="file-help"><p class="help" id="file-help">UTF-8 · 최대 10 MB · 41~10,000일의 연속된 관측 자료</p></div></div><div class="form-grid"><div class="field"><label for="source-kind">자료 구분</label><select id="source-kind" name="source_kind"><option value="simulated">시뮬레이션</option><option value="measured">실측 자료</option></select></div><div class="field" id="scenario-field"><label for="scenario">시뮬레이션 시나리오</label><select id="scenario" name="scenario"><option value="baseline">기준 시나리오</option><option value="drift">변화 시나리오</option></select></div><div class="field full"><label for="parent-dataset">등록 방식</label><select id="parent-dataset" name="parent_dataset_id"><option value="">새로운 자료로 등록</option>${leaves.map(d=>`<option value="${h(d.id)}">${version(d)}에 이어 붙이기 · ${h(d.original_name)}</option>`).join('')}</select><p class="help">이어 붙일 때는 기존 관측 전체와 추가 날짜를 함께 포함하세요. 기존 값은 바꿀 수 없습니다.</p></div></div><div class="requirements"><code>observed_date,groundwater_depth_cm,rainfall_mm</code>위 순서의 열 이름을 사용하세요. 날짜는 YYYY-MM-DD, 깊이는 0보다 큰 cm, 강수량은 0 이상의 mm(소수 첫째 자리까지)입니다. 누락·중복·미래 날짜는 등록할 수 없습니다.</div><button class="primary wide" type="submit" ${state.pending||!state.well?'disabled':''}>${state.pending?'등록 중…':'CSV 등록'}</button></form></section><section><div class="panel-head" style="padding-top:0"><div><h2>등록된 버전 <span class="muted">${state.datasets.length}</span></h2><p>선택한 버전이 모든 화면에 적용됩니다.</p></div></div><div class="version-list">${state.datasets.length?state.datasets.map(d=>`<article class="version-card ${d.id===state.dataset?.id?'selected':''}"><div class="toolbar"><div class="toolbar">${badge(version(d))}${badge(source(d),'neutral')}${d.scenario?badge(d.scenario==='baseline'?'기준 시나리오':'변화 시나리오','neutral'):''}</div><button data-dataset="${h(d.id)}" ${state.pending||d.id===state.dataset?.id?'disabled':''}>${d.id===state.dataset?.id?'선택됨':'이 버전 선택'}</button></div><h3>${h(d.original_name)}</h3><p>${h(d.start_date)} — ${h(d.end_date)} · ${num(d.row_count)}일</p><p>등록 ${dateTime(d.uploaded_at)} KST · ${d.parent_dataset_id?'이전 버전 '+h(short(d.parent_dataset_id))+'에서 확장':'독립 자료'}</p><details><summary>버전 정보</summary><p>식별자 ${h(d.id)}</p><p>형식 ${h(d.schema_version)}</p><p>파일 확인값 ${h(d.checksum)}</p></details></article>`).join(''):'<div class="empty panel">등록된 자료가 없습니다.<br>왼쪽 양식에서 첫 CSV를 등록하세요.</div>'}</div></section></div>`;
}
function renderOperations() {
  const d=state.dataset;
  let output=heading('03','운영 이력','과거 구간을 분석하고, 감지와 재학습의 실제 실행 기록을 확인하세요.','<button class="subtle" data-action="refresh">↻ 새로고침</button>');
  if(!d){$('#view').innerHTML=output+blank();return;}
  const start=addDays(d.start_date,20);
  output+=`<form id="analysis-form" class="panel run-controls"><div class="field"><label for="analysis-from">분석 시작일</label><input id="analysis-from" name="from" type="date" min="${start}" max="${h(d.end_date)}" value="${h(state.analysisFrom||start)}" required></div><div class="field"><label for="analysis-to">분석 종료일</label><input id="analysis-to" name="to" type="date" min="${start}" max="${h(d.end_date)}" value="${h(state.analysisTo||d.end_date)}" required></div><button type="submit" class="primary" ${modelReady()?'':'disabled'} aria-describedby="analysis-help">${state.pending?'접수 중…':'과거 구간 분석'}</button><p class="help" id="analysis-help">${h(modelReason())} · ${h(version(d))} / ${h(source(d))} · 대상일 이전 20일 필요 · 최대 756일</p></form><div class="run-layout"><section class="panel"><div class="panel-head"><h2>실행 목록</h2><select id="run-kind" aria-label="실행 종류"><option value="">전체 실행</option><option value="analysis" ${state.kind==='analysis'?'selected':''}>구간 분석</option><option value="retrain" ${state.kind==='retrain'?'selected':''}>재학습</option></select></div><div id="run-list"></div></section><section class="panel" id="run-detail" aria-live="polite"></section></div>`;
  $('#view').innerHTML=output;renderRunList();renderRunDetail();
}
function renderRunList() {
  if(!$('#run-list'))return;
  const runs=state.runs.filter(r=>!state.kind||r.kind===state.kind);
  $('#run-list').innerHTML=runs.length?`<div class="run-list">${runs.map(r=>`<button class="run-item" data-run="${h(r.id)}" aria-pressed="${state.run?.id===r.id}"><div class="toolbar">${badge(runLabels[r.status],r.status==='failed'?'red':isActive(r)?'amber':'neutral')}<span>${r.kind==='analysis'?'구간 분석':'재학습'}</span></div><small>${h(r.from_date)} → ${h(r.to_date)}</small><small>${dateTime(r.created_at)} · ${h(short(r.id))}</small></button>`).join('')}</div>`:'<div class="empty">이 버전의 실행 기록이 없습니다.</div>';
}
function renderRunDetail() {
  const target=$('#run-detail');if(!target)return;
  const r=state.run;
  if(!r){target.innerHTML='<div class="empty"><div class="empty-symbol">↳</div><h2>실행 기록을 선택하세요</h2><p>실제로 보고된 단계와 결과를 여기에 표시합니다.</p></div>';return;}
  const result=r.result;
  target.innerHTML=`<div class="panel-head"><div><div class="eyebrow">${h(short(r.id))} / ${r.mode==='replay'?'과거 자료 분석':'실시간 예측'}</div><h2>${r.kind==='analysis'?'구간 분석':'자동 재학습'} ${badge(runLabels[r.status],r.status==='failed'?'red':isActive(r)?'amber':'neutral')}</h2></div>${isActive(r)?'<span class="loading">2초마다 갱신</span>':''}</div><div class="result-box">${kv('자료 버전',short(r.dataset_id))}${kv('실행 범위',r.from_date+' — '+r.to_date)}${kv('입력 모델',short(r.input_model_version_id))}${kv('접수 시각',dateTime(r.created_at)+' KST')}${kv('종료 시각',r.finished_at?dateTime(r.finished_at)+' KST':'아직 종료되지 않음')}${r.parent_run_id?`<button class="text-link" data-run="${h(r.parent_run_id)}">상위 분석 보기 →</button>`:''}</div><ol class="event-list">${state.events.map(e=>`<li><div class="toolbar"><strong>${h(stageLabels[e.stage]||e.stage)}</strong>${badge(eventLabels[e.state]||e.state,e.state==='failed'?'red':'neutral')}</div><p>${h(e.message)}</p><time>${dateTime(e.occurred_at)} KST</time></li>`).join('')||'<li><p>아직 보고된 단계가 없습니다.</p></li>'}</ol>${result?`<div class="result-box"><h3>실행 결과</h3>${r.kind==='analysis'?`${kv('생성된 예측',num(result.prediction_count)+'건')}${kv('처리한 마지막 날짜',result.processed_through_date||'—')}${kv('종료 사유',result.stop_reason==='drift_detected'?'변화 감지로 구간 분석 중지':'요청 구간 처리 완료')}${result.child_run_id?`<p class="description">재학습은 별도 실행입니다. 이 분석의 완료는 재학습·모델 적용 완료를 의미하지 않습니다.</p><button class="text-link" data-run="${h(result.child_run_id)}">연결된 재학습 보기 →</button>`:''}`:`${kv('검증 오차',num(result.gate_rmse_cm)+' cm')}${kv('검증 결과',result.gate_passed?'통과':'미통과')}${kv('모델 적용',result.promoted?'적용됨':'적용되지 않음')}${kv('이전 모델',short(result.previous_model_version_id))}${kv('후보 모델',short(result.candidate_model_version_id))}`}</div>`:''}${r.error?`<div class="result-box"><h3>실행을 마치지 못했습니다</h3><p>${h(r.error.code)}</p><p class="description">입력 자료와 모델 연결 상태를 확인하세요.</p></div>`:''}${r.trigger_check_id||result?.last_check_id?`<div class="result-box"><button class="text-link" data-check="${h(r.trigger_check_id||result.last_check_id)}">감지 판정 근거 보기</button><div id="run-check"></div></div>`:''}`;
}
async function selectWell(id) {
  if(state.pending)return;
  const well=state.wells.find(w=>w.id===id);if(!well)return;
  controller?.abort();stopPolling();state.revision++;
  state.well=well;state.dataset=null;state.datasets=[];state.modelReport=null;state.dashboard=null;
  state.observations=[];state.forecasts=[];state.runs=[];state.run=null;state.loading=true;
  state.mode=well.code.startsWith('SEOUL-')?'replay':'live';storage.setItem('groundwatch:well',id);
  $('#notice').innerHTML='';render();
  try{await loadDatasets();if(state.well.id===id)await loadData({reset:true});}
  catch(error){if(state.well.id===id){state.loading=false;render();showError(error);}}
}
function renderModels() {
  const reports=state.reports;
  const better=reports.filter(r=>r.test.rmse_cm<r.test_baseline.rmse_cm).length;
  $('#view').innerHTML=heading('04','구별 모델 평가','각 구 1개 관측소 · 최근 20일 지하수 깊이와 강수량으로 다음 날 예측')+
    `<div class="notice research-note"><strong>${reports.length}개 관측소 학습 · 분리 평가에서 ${better}개가 전날 값 유지보다 낮은 오차</strong><p>학습 → 검증 → 분리 평가를 날짜 순서로 나눴습니다. 표의 RMSE는 학습과 모델 선택에 쓰지 않은 이후 자료의 오차입니다. 관측소마다 기간과 변동 폭이 달라 구 간 우열 지표로 사용하지 않습니다.</p>모두 연구용 후보이며, 자동 재학습·위험 판정·운영 승격 기준은 설정하지 않았습니다.</div>
    <section class="panel"><div class="table-scroll model-table" tabindex="0" aria-label="구별 모델 성능 비교"><table><caption>검증 Gate: LSTM 검증 RMSE ≤ 전날 값 유지 검증 RMSE. 분리 평가 결과와 별도입니다.</caption><thead><tr><th scope="col">구 · 관측소</th><th scope="col">LSTM RMSE (cm)</th><th scope="col">전날 유지 (cm)</th><th scope="col">MAE (cm)</th><th scope="col">평가 건수</th><th scope="col">평가 기간</th><th scope="col">검증 Gate</th><th scope="col">결과</th></tr></thead><tbody>${reports.map(r=>`<tr><td><strong>${h(r.district)}</strong><br><span class="muted">${h(r.station)}</span></td><td>${num(r.test.rmse_cm)}</td><td>${num(r.test_baseline.rmse_cm)}</td><td>${num(r.test.mae_cm)}</td><td>${num(r.test.count)}</td><td>${h(r.test_start_date)}<br>${h(r.test_end_date)}</td><td>${badge(r.validation_gate_passed?'통과':'미통과',r.validation_gate_passed?'green':'amber')}</td><td><button class="small" data-well="${h(r.well_id)}">관측소 보기</button></td></tr>`).join('')}</tbody></table></div></section>`;
}

async function loadDatasets(preferred) {
  const wellId=state.well.id;const datasets=await api.all(`/wells/${wellId}/datasets`);if(state.well.id!==wellId)return;state.datasets=datasets;
  state.dataset=state.datasets.find(d=>d.id===(preferred||storage.getItem('groundwatch:dataset:'+state.well.id)))||state.datasets[0]||null;
  if(state.dataset)storage.setItem('groundwatch:dataset:'+state.well.id,state.dataset.id);
}
async function loadData({reset=false}={}) {
  controller?.abort();stopPolling();controller=new AbortController();const signal=controller.signal, revision=++state.revision;
  state.loading=true;state.dataError=null;
  if(reset){state.dashboard=null;state.modelReport=null;state.observations=[];state.forecasts=[];state.run=null;state.events=[];state.runs=[];state.range='60';state.analysisFrom='';state.analysisTo='';}
  setRange();
  const query=JSON.stringify([state.dataset?.id,state.mode,state.from,state.to]);
  if(query!==state.loadedQuery){state.dashboard=null;state.observations=[];state.forecasts=[];}
  render();
  if(!state.dataset){state.loading=false;render();return;}
  const d=state.dataset, base=`/wells/${state.well.id}`;
  try {
    const windows=dateWindows(state.from,state.to);
    const [dashboard,observations,forecasts,runs,report]=await Promise.all([
      api.request(base+'/dashboard',{params:{dataset_id:d.id,mode:state.mode},signal}),
      (async()=>{const rows=[];for(const [from,to] of windows)rows.push(...await api.all(base+'/observations',{dataset_id:d.id,from,to},signal));return rows;})(),
      (async()=>{const rows=[];for(const [from,to] of windows)rows.push(...await api.all(base+'/forecasts',{dataset_id:d.id,mode:state.mode,from,to},signal));return rows;})(),
      api.all(base+'/runs',{dataset_id:d.id},signal),
      api.request(base+'/model-report',{signal})
    ]);
    if(revision!==state.revision)return;
    Object.assign(state,{dashboard:dashboard.data,modelReport:report.data,observations,forecasts,runs,loading:false,loadedQuery:query});render();
    if(state.page==='operations') {
      const id=state.run?.id||storage.getItem('groundwatch:run:'+d.id)||runs[0]?.id;
      if(id)await selectRun(id);
    }
  } catch(error){if(revision!==state.revision||error.name==='AbortError')return;state.loading=false;state.dataError=error;render();showError(error,Boolean(state.dashboard));}
}
async function selectDataset(id) {
  if(state.pending)return;
  const d=state.datasets.find(d=>d.id===id);if(!d)return;
  state.dataset=d;storage.setItem('groundwatch:dataset:'+state.well.id,id);$('#notice').innerHTML='';await loadData({reset:true});
}
async function selectRun(id) {
  stopPolling();const revision=runRevision;runController=new AbortController();const signal=runController.signal;
  try {
    const [run,events]=await Promise.all([api.request('/runs/'+id,{signal}),api.all('/runs/'+id+'/events',{},signal)]);
    if(revision!==runRevision||state.page!=='operations')return;
    if(run.data.dataset_id!==state.dataset?.id)throw new APIError('선택한 자료 버전의 실행이 아닙니다. 해당 자료 버전을 먼저 선택하세요.','INVALID_DATA');
    if(!isActive(run.data)){const runs=await api.all(`/wells/${state.well.id}/runs`,{dataset_id:state.dataset.id},signal);if(revision!==runRevision)return;state.runs=runs;}
    state.run=run.data;state.events=events;storage.setItem('groundwatch:run:'+state.dataset.id,id);
    const index=state.runs.findIndex(r=>r.id===id);if(index>=0)state.runs[index]=run.data;else state.runs.unshift(run.data);
    renderRunList();renderRunDetail();
    if(isActive(state.run)&&!document.hidden)pollTimer=setTimeout(()=>selectRun(id),2000);
  }catch(error){if(revision===runRevision&&error.name!=='AbortError')showError(error,Boolean(state.run));}
}
async function route() {
  const page=location.hash.slice(1);if(!['overview','datasets','operations','models'].includes(page))return;
  stopPolling();state.page=page;$('#notice').innerHTML='';render();
  if((page==='overview'||page==='operations')&&state.dataset&&!state.pending)await loadData();
}
async function upload(form) {
  if(state.pending)return;
  const file=form.elements.file.files[0];
  if(!file)return;
  if(!file.name.toLowerCase().endsWith('.csv')||file.size>10*1024*1024){showError(new APIError('10 MB 이하의 CSV 파일을 선택하세요.','INVALID_DATA'));return;}
  const body=new FormData(form);if(body.get('source_kind')==='measured')body.delete('scenario');if(!body.get('parent_dataset_id'))body.delete('parent_dataset_id');
  state.pending=true;form.querySelector('button[type=submit]').disabled=true;form.querySelector('button[type=submit]').textContent='등록 중…';context();
  try {
    const result=await api.request(`/wells/${state.well.id}/datasets`,{method:'POST',body});
    await loadDatasets(result.data.id);state.pending=false;await loadData({reset:true});
    if(!state.dataError)announce(result.status===200?'이미 등록된 동일한 파일입니다. 기존 버전을 선택했습니다.':`${result.data.row_count}일의 관측 자료를 등록했습니다. ${version(result.data)} 버전을 선택했습니다.`);
  }catch(error){state.pending=false;context();if(form.isConnected){form.querySelector('button[type=submit]').disabled=false;form.querySelector('button[type=submit]').textContent='CSV 등록';}showError(error);}
}
async function mutate(kind,body) {
  if(!modelReady())return;
  state.pending=true;render();
  try {
    const response=await api.mutate(`/wells/${state.well.id}/${kind}`,body);
    state.pending=false;
    if(kind==='analyses'){state.run=response.data;state.page='operations';location.hash='operations';await loadData();if(!state.dataError)announce('분석 요청을 접수했습니다. 실행 기록에서 진행 상태를 확인하세요.');}
    else {state.mode='live';await loadData();if(!state.dataError)announce('다음 날 예측 결과를 저장했습니다.');}
  }catch(error){
    state.pending=false;
    if(kind==='forecasts'&&error.code==='FORECAST_EXISTS'){
      state.mode='live';await loadData();
      if(!state.dataError)announce('같은 자료와 모델로 저장된 다음 날 예측을 표시했습니다.');
    }else{render();showError(error);}
  }
}
async function refresh() {
  if(state.pending)return;
  $('#notice').innerHTML='';
  try {if(!state.well){await boot();return;}await loadDatasets(state.dataset?.id);await loadData();}catch(error){state.dataError=error;render();showError(error,Boolean(state.dashboard));}
}
// Event delegation keeps controls and server-supplied text separate.
 document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button||button.disabled)return;
  try {
    if(button.dataset.page){location.hash=button.dataset.page;return;}
    if(button.dataset.well){await selectWell(button.dataset.well);location.hash='overview';return;}
    if(button.dataset.dataset){await selectDataset(button.dataset.dataset);return;}
    if(button.dataset.run){if(state.page!=='operations'){state.page='operations';history.replaceState(null,'','#operations');render();}await selectRun(button.dataset.run);return;}
    if(button.dataset.check){const id=button.dataset.check;const result=await api.request('/checks/'+id);if($('#run-check')&&button.isConnected){$('#run-check').innerHTML=checkDetail(result.data);$('#run-check details').open=true;}return;}
    if(button.dataset.range){state.range=button.dataset.range;if(state.range==='custom'){render();return;}await loadData();return;}
    if(button.dataset.action==='refresh')await refresh();
    if(button.dataset.action==='table'){state.table=!state.table;renderOverview();}
    if(button.dataset.action==='predict')await mutate('forecasts',{dataset_id:state.dataset.id,input_end_date:state.dataset.end_date});
  }catch(error){showError(error);}
});
document.addEventListener('change',async event=>{
  const el=event.target;
  if(el.id==='well-select')await selectWell(el.value);
  if(el.id==='dataset-select')await selectDataset(el.value);
  if(el.id==='mode'){state.mode=el.value;await loadData();}
  if(el.id==='source-kind'){$('#scenario-field').hidden=el.value==='measured';$('#scenario').disabled=el.value==='measured';}
  if(el.id==='analysis-from')state.analysisFrom=el.value;
  if(el.id==='analysis-to')state.analysisTo=el.value;
  if(el.id==='run-kind'){state.kind=el.value;renderRunList();}
});
document.addEventListener('submit',async event=>{
  const form=event.target;event.preventDefault();
  try {
    if(form.id==='upload-form')await upload(form);
    if(form.id==='range-form'){const data=new FormData(form);dateWindows(data.get('from'),data.get('to'));state.from=data.get('from');state.to=data.get('to');await loadData();}
    if(form.id==='analysis-form'){const data=new FormData(form);const windows=dateWindows(data.get('from'),data.get('to'));if(windows.length>1)throw new APIError('분석은 한 번에 최대 756일까지 가능합니다.','INVALID_DATA');await mutate('analyses',{dataset_id:state.dataset.id,from:data.get('from'),to:data.get('to'),mode:'replay'});}
  }catch(error){showError(error);}
});
window.addEventListener('hashchange',route);
let resizeTimer;
window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(state.page==='overview'&&!state.table&&$('#chart'))renderChart($('#chart'),state.observations,state.forecasts,state.from,state.to);},100);});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopPolling();else if(state.page==='operations'&&state.run)selectRun(state.run.id);});
window.addEventListener('pagehide',()=>{controller?.abort();stopPolling();});
window.addEventListener('pageshow',event=>{if(event.persisted)refresh();});
async function boot() {
  state.page=['overview','datasets','operations','models'].includes(location.hash.slice(1))?location.hash.slice(1):'overview';state.loading=true;
  try {const wells=await api.all('/wells');state.wells=wells.sort((a,b)=>a.name.localeCompare(b.name,'ko'));state.well=state.wells.find(w=>w.id===storage.getItem('groundwatch:well'))||state.wells.find(w=>w.code.startsWith('SEOUL-'))||wells[0]||null;state.mode=state.well?.code.startsWith('SEOUL-')?'replay':'live';state.reports=await api.all('/model-reports');if(!state.well)throw new APIError('등록된 관측정이 없습니다. 관측정 설정을 확인하세요.','NOT_FOUND');await loadDatasets();await loadData({reset:true});}
  catch(error){state.loading=false;state.dataError=error;render();showError(error);}
}
boot();
