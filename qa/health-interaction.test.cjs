const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const HealthViews=require('../src/mi_fitness_mcp/web_assets/static/js/health-views.js');
function fixture(){
 const nodes=new Map(),saved={};let callback;
 const get=id=>{if(!nodes.has(id))nodes.set(id,{value:({startDate:'2026-10-15',endDate:'2026-10-17',napsSelect:'true'})[id]||'',textContent:'',innerHTML:'',checked:false,dataset:{},setAttribute(k,v){this[k]=v;},classList:{toggle(){},add(){},remove(){}}});return nodes.get(id);};
 const c=vm.createContext({HealthViews,AbortController,console,performance,document:{getElementById:get,querySelectorAll(){return [];},addEventListener(name,fn){callback=fn;},documentElement:{setAttribute(){}}},localStorage:{getItem(k){return saved[k]||'';},setItem(k,v){saved[k]=v;}},setTimeout(){},setInterval(){},clearTimeout(){},clearInterval(){}});
 vm.runInContext(fs.readFileSync('src/mi_fitness_mcp/web_assets/static/js/health-ui.js','utf8'),c);
 vm.runInContext(fs.readFileSync('src/mi_fitness_mcp/web_assets/static/js/app.js','utf8'),c);
 vm.runInContext('showToast=()=>{};',c);
 return{c,get,saved};
}
test('切换到睡眠页自动查询并清空上个接口，修改日期会重新加载',async()=>{
 const f=fixture();vm.runInContext('calls=[];api=async(method,path)=>{calls.push(path);return {status:"ok",data:[]};};state.lastResponse={old:true};',f.c);
 await vm.runInContext("switchTab('sleep')",f.c);
 assert.equal(vm.runInContext('state.lastResponse',f.c),null);
 assert.equal(vm.runInContext('calls.length',f.c),1);
 assert.match(f.get('healthView-sleep').innerHTML,/睡眠分析明细/);
 await vm.runInContext("setDatePreset('7d')",f.c);
 assert.equal(vm.runInContext('calls.length',f.c),2);
});
test('后返回的旧日期请求不会覆盖新日期结果或控制台',async()=>{
 const f=fixture();const waits=[];f.c.pending=waits;
 vm.runInContext('state.activeTab="sleep";api=(method,path,body,view)=>new Promise(resolve=>pending.push({resolve,view}));',f.c);
 const first=vm.runInContext('querySleep()',f.c);
 f.get('startDate').value='2026-10-16';
 const second=vm.runInContext('querySleep()',f.c);
 assert.equal(waits[0].view.isCurrent(),false);
 waits[1].resolve({status:'ok',data:[{end_at:'2026-10-16T08:00:00+08:00',time_asleep_minutes:400}]});await second;
 waits[0].resolve({status:'ok',data:[{end_at:'2026-10-15T08:00:00+08:00',time_asleep_minutes:100}]});await first;
 assert.equal(vm.runInContext('state.healthViews.sleep.model.records[0].time_asleep_minutes',f.c),400);
});
test('失败与无数据分别显示，控制台开关会记忆选择',async()=>{
 const f=fixture();vm.runInContext('state.activeTab="spo2";api=async()=>null;',f.c);
 await vm.runInContext('querySpo2()',f.c);
 assert.match(f.get('healthView-spo2').innerHTML,/查询失败/);
 vm.runInContext('api=async()=>({status:"ok",data:[]});',f.c);
 await vm.runInContext('querySpo2()',f.c);
 assert.match(f.get('healthView-spo2').innerHTML,/未保存/);
 vm.runInContext('setInspectorCollapsed(true)',f.c);
 assert.equal(f.saved.mi_fitness_inspector_collapsed,'true');
 assert.equal(f.get('inspectorToggle').textContent,'展开控制台');
 assert.equal(f.get('inspectorToggle')['aria-expanded'],'false');
});
