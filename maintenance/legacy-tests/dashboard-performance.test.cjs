const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function fixture(){
  const nodes=new Map();
  const get=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'--',innerHTML:'',value:id==='startDate'?'2026-09-18':id==='endDate'?'2026-10-17':'',classList:{add(){},remove(){}}});return nodes.get(id);};
  const records=Array.from({length:3000},(_,i)=>({timestamp:`2026-10-16T09:${String(i%60).padStart(2,'0')}:00+08:00`,stress_score:30}));
  const responses={summary:[{date:'2026-10-16',steps:6000,active_kcal:500,distance_m:4000}],
    'heart-rate':[{bpm:62}],sleep:[{end_at:'2026-10-16T08:00:00+08:00',duration_minutes:450}],spo2:[{spo2_pct:97}],stress:records};
  const copied=[];
  const context=vm.createContext({document:{getElementById:get,querySelectorAll(){return [];},addEventListener(){}},
    localStorage:{getItem(){return '';},setItem(){}},performance,console,setTimeout(){},setInterval(){},clearTimeout(){},clearInterval(){},
    navigator:{clipboard:{writeText(text){copied.push(text);return Promise.resolve();}}},
    fetch:async url=>({status:200,ok:true,text:async()=>JSON.stringify({status:'ok',data:responses[url.split('?')[0].split('/').pop()]||[]})})});
 vm.runInContext(fs.readFileSync('work/mi-fitness-mcp-cn/src/mi_fitness_mcp/web_assets/static/js/health-ui.js','utf8'),context);
  vm.runInContext(fs.readFileSync('work/mi-fitness-mcp-cn/src/mi_fitness_mcp/web_assets/static/js/app.js','utf8'),context);
  vm.runInContext('showToast=()=>{}; renderCount=0; originalRender=renderJsonViewer; renderJsonViewer=(data)=>{renderCount++;originalRender(data);};',context);
  return {context,get,copied};
}
test('overview paints one small response instead of five full datasets',async()=>{
  const ui=fixture();await vm.runInContext('loadOverview()',ui.context);
  assert.equal(vm.runInContext('renderCount',ui.context),1);
  assert.equal(ui.get('statStress').textContent,'30');
  assert.equal(ui.get('statSteps').textContent,(6000).toLocaleString());
  assert.equal(vm.runInContext('state.lastRequestInfo.path.split("?")[0]',ui.context),'/api/summary');
});
test('silent and superseded requests do not overwrite inspector state',async()=>{
  const ui=fixture();ui.get('inspectorBody').innerHTML='keep-current';
  await vm.runInContext("api('GET','/api/stress',null,{inspect:false})",ui.context);
  await vm.runInContext("api('GET','/api/stress',null,{isCurrent:()=>false})",ui.context);
  assert.equal(ui.get('inspectorBody').innerHTML,'keep-current');
  assert.equal(vm.runInContext('state.lastResponse',ui.context),null);
});
test('large detail preview is bounded while copy keeps every record',async()=>{
  const ui=fixture();await vm.runInContext("api('GET','/api/stress')",ui.context);
  const html=ui.get('inspectorBody').innerHTML;
  assert.ok((html.match(/<span /g)||[]).length<=1000);
  assert.match(html,/预览/);
  assert.equal(vm.runInContext('state.lastResponse.data.length',ui.context),3000);
  vm.runInContext('copyResponse()',ui.context);
  assert.equal(JSON.parse(ui.copied[0]).data.length,3000);
  vm.runInContext("filterInspectorJson('timestamp')",ui.context);
  assert.ok((ui.get('inspectorBody').innerHTML.match(/<span /g)||[]).length<=1000);
});

test('a late overview response cannot overwrite a newer manual inspector query',async()=>{
  const ui=fixture();
  const pending={};
  ui.context.fetch=url=>new Promise(resolve=>{pending[url]=resolve;});
  const first=vm.runInContext("api('GET','/api/summary',null,{isCurrent:()=>true})",ui.context);
  const second=vm.runInContext("api('GET','/api/coverage')",ui.context);
  const response=marker=>({status:200,ok:true,text:async()=>JSON.stringify({marker})});
  pending['/proxy/api/coverage'](response('new'));await second;
  pending['/proxy/api/summary'](response('old'));await first;
  assert.equal(vm.runInContext('state.lastResponse.marker',ui.context),'new');
  assert.equal(vm.runInContext('state.lastRequestInfo.path',ui.context),'/api/coverage');
});
