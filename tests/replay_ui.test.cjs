// Run with: node tests/replay_ui.test.cjs
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const source=readFileSync('serving_app/static/groundwatch.js','utf8');
const code=source.slice(source.indexOf('function showReplayPreparation'),source.indexOf('function renderForecasts'));
async function scenario(status){
 const elements=new Map();
 const $=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,style:{},selectedOptions:[{dataset:{}}],setAttribute(){}});return elements.get(id);};
 $('namespace').value='session';$('mode').value='historical_replay';
 const calls=[];const notices=[];
 const context={$,state:{view:'operations',selected:'11110'},query:()=> 'replay_id=session',escapeHTML:String,
 translations:{historical_replay:'과거 관측 검증'},numeric:Number.isFinite,lower:s=>String(s||'').toLowerCase(),text:String,
 updateSupplyControls(){},renderForecasts(){},notice:(m,error=false)=>notices.push({m,error}),
 api:async path=>{calls.push(path);if(path.startsWith('/pipeline'))return {replay_id:'session',replay_status:status,as_of:'2026-07-10'};
 if(path.startsWith('/districts'))return {districts:[]};
 if(path.startsWith('/forecasts'))return {ready_count:25,forecasts:[],as_of:'2026-07-10'};
 throw Error('Unexpected request '+path);}};
 vm.createContext(context);vm.runInContext(code,context);await context.refresh();
 return {calls,notices,context,elements};
}
(async()=>{
 const pending=await scenario('initializing');
 assert.equal(pending.calls.some(p=>p.startsWith('/forecasts')),false,'never request forecasts before models are ready');
 assert.equal(pending.context.state.waitingReplay,'session');assert.equal(pending.notices.at(-1).error,false);
 assert.match(pending.notices.at(-1).m,/준비하고/);assert.equal(pending.context.state.loading,false);
 const ready=await scenario('ready');assert.equal(ready.calls.some(p=>p.startsWith('/forecasts')),true);
 assert.equal(ready.context.state.waitingReplay,null);assert.equal(ready.elements.get('ready-count').textContent,25);
 const failed=await scenario('failed');assert.equal(failed.calls.some(p=>p.startsWith('/forecasts')),false);
 assert.equal(failed.notices.at(-1).error,true);assert.equal(failed.context.state.waitingReplay,null);
 console.log('Replay UI: pending, ready, failed states passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
const progressCode=source.slice(source.indexOf('function renderPipelineProgress'),source.indexOf('async function loadPipeline'));
const progressEl={hidden:true,classList:{toggle(){}},setAttribute(){}};
const progressContext={$:()=>progressEl,state:{}};vm.createContext(progressContext);vm.runInContext(progressCode,progressContext);
for(const [response,expected] of [
 [{replay_id:'s',replay_status:'initializing',active_jobs:[{kind:'train',result:{processed:4,total:25}}]},/4\/25/],
 [{replay_id:'s',advance_active:true,active_jobs:[{kind:'advance',result:{processed:3,total:21}}]},/3\/21/],
 [{replay_id:'s',active_jobs:[{kind:'fine_tune'}]},/재학습 중/],
 [{replay_id:'s',latest_advance_job:{status:'failed',error:'worker failed'}},/실패·중단/],
 [{replay_id:'s',candidate_version:2},/평가 대기/]
]){progressContext.renderPipelineProgress(response);assert.match(progressEl.textContent,expected);}
console.log('Pipeline progress: initialization, advance, retrain, failure, evaluation wait passed');
// Scenario selection must agree with the replay that the progress controls use.
const scenarioElements=new Map();
const scenario$=id=>{if(!scenarioElements.has(id))scenarioElements.set(id,{value:'',selectedOptions:[{dataset:{}}],classList:{toggle(){}},setAttribute(k,v){this[k]=v;}});return scenarioElements.get(id);};
const scenarioContext={$:scenario$,state:{}};vm.createContext(scenarioContext);
vm.runInContext(source.slice(source.indexOf('function renderScenarioControls'),source.indexOf('async function loadPipeline')),scenarioContext);
scenarioContext.renderScenarioControls({defaults:{}});
assert.equal(scenario$('normal-demo')['aria-pressed'],'false');assert.equal(scenario$('shift-demo')['aria-pressed'],'false');
assert.match(scenario$('scenario-status').textContent,/선택된 시연 없음/);
scenarioContext.renderScenarioControls({replay_id:'normal123',defaults:{},remaining_days:90});
assert.equal(scenario$('normal-demo')['aria-pressed'],'true');assert.equal(scenario$('shift-demo')['aria-pressed'],'false');
scenarioContext.renderScenarioControls({replay_id:'drift123',defaults:{},drift_demo:{},remaining_days:69});
assert.equal(scenario$('shift-demo')['aria-pressed'],'true');assert.equal(scenario$('normal-demo')['aria-pressed'],'false');
assert.match(scenario$('scenario-status').textContent,/드리프트 시연/);
scenarioContext.renderScenarioControls({replay_id:'drift123',defaults:{},drift_demo:{},remaining_days:69,advance_active:true});
assert.equal(scenario$('shift-demo').disabled,true);assert.equal(scenario$('restart-demo').disabled,true);
// Clicking the selected situation must not create another replay or reset progress.
scenario$('namespace').value='drift123';scenarioContext.state.selectedScenario='level_shift';
scenarioContext.state.pipeline={};scenarioContext.notice=()=>{};
vm.runInContext(source.slice(source.indexOf('async function startDemo'),source.indexOf("$('normal-demo').addEventListener")),scenarioContext);
scenarioContext.startDemo('level_shift',{}).then(()=>{assert.equal(scenarioContext.state.startingDemo,undefined);console.log('Scenario selection and selected-click preservation passed');}).catch(e=>{console.error(e);process.exitCode=1;});

// Signed groundwater values, missing truth and display precision must stay distinct.
const compareContext={numeric:Number.isFinite,text:String,escapeHTML:String};vm.createContext(compareContext);
vm.runInContext(source.slice(source.indexOf('function comparison('),source.indexOf('function renderForecasts')),compareContext);
for(const [actual,predicted,tone] of [[-21.3,-21.5,'above'],[-21.7,-21.5,'below'],[-21.5,-21.5,''],[-21.50001,-21.5,''],[null,-21.5,''],[-21.5,null,'']]){
 assert.equal(compareContext.comparison(actual,predicted).tone,tone);
}
assert.match(compareContext.comparisonHTML({actual:-21.3,prediction:-21.5},'gl.-m'),/actual-value above/);
assert.match(compareContext.comparisonHTML({actual:-21.7,prediction:-21.5},'gl.-m'),/actual-value below/);
assert.equal(compareContext.comparisonHTML({actual:null,prediction:-21.5},'gl.-m'),'');
console.log('Same-date comparison: higher, lower, equal, missing and precision cases passed');
const chartContext={...compareContext,escapeHTML:String};vm.createContext(chartContext);
vm.runInContext(source.slice(source.indexOf('function comparison('),source.indexOf('function renderForecasts')),chartContext);
vm.runInContext(source.slice(source.indexOf('function chart('),source.indexOf('function compactModel')),chartContext);
const chartEl={};chartContext.chart(chartEl,[{date:'2026-10-06',groundwater_level:-21.3,prediction:-21.5},{date:'2026-10-07',groundwater_level:-21.7,prediction:-21.5},{date:'2026-10-08',groundwater_level:null,prediction:-21.6}],[{key:'groundwater_level',color:'green',label:'입력'},{key:'prediction',color:'orange',label:'예측'}],'gl.-m',false);
assert.equal((chartEl.innerHTML.match(/class="comparison-point above"/g)||[]).length,1);
assert.equal((chartEl.innerHTML.match(/class="comparison-point below"/g)||[]).length,1);
assert.match(chartEl.innerHTML,/다음 날 예측/);
assert.doesNotMatch(chartEl.innerHTML,/NaN/);
console.log('Chart comparison: observed points only; unlabelled future stays distinct');
