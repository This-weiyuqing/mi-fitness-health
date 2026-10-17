const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const HealthViews=require('../src/mi_fitness_mcp/web_assets/static/js/health-views.js');
function summary(kind='stress',number=1,total=21){return {status:'ok',kind,range:{start:'2026-10-15',end:'2026-10-17'},statistics:{count:total,primary_mean:33,primary_min:10,primary_max:60},coverage:1,stride:1,points:[{date:'2026-10-16',values:[33],missing:false}],page:{number,size:10,total,rows:[{timestamp:'2026-10-16T00:00:00Z',stress_score:number}]}};}
function fixture(){
 const nodes=new Map(),links=[],requests=[],calendars=[];
 const get=id=>{if(!nodes.has(id))nodes.set(id,{value:({startDate:'2026-10-15',endDate:'2026-10-17',napsSelect:'true'})[id]||'',textContent:'',innerHTML:'',checked:false,setAttribute(){},classList:{toggle(){},add(){},remove(){}},querySelector(){return get(id+'-table');}});return nodes.get(id);};
 const context=vm.createContext({HealthViews,AbortController,console,performance,URL,document:{getElementById:get,querySelectorAll(){return [];},addEventListener(){},createElement(){const a={click(){links.push(this.href);},remove(){}};return a;},body:{appendChild(){}}},localStorage:{getItem(){return '';},setItem(){}},setTimeout(){},setInterval(){},clearTimeout(){},clearInterval(){},fetch:url=>new Promise(resolve=>{if(url.startsWith('/api/calendar'))calendars.push({url,resolve});else requests.push({url,resolve});})});
 for(const name of ['health-ui','app'])vm.runInContext(fs.readFileSync(`src/mi_fitness_mcp/web_assets/static/js/${name}.js`,'utf8'),context);
 vm.runInContext('showToast=()=>{};state.activeTab="stress";',context);
 const reply=(i,p)=>requests[i].resolve({status:200,ok:true,text:async()=>JSON.stringify(p)});
 return {context,get,links,requests,calendars,reply,run:code=>vm.runInContext(code,context)};
}
test('test_pagination_fetches_only_page_and_preserves_chart',async()=>{
 const f=fixture(),initial=f.run('loadHealthView("stress")');assert.match(f.requests[0].url,/^\/proxy\/api\/views\/stress\?/);f.reply(0,summary());await initial;
 const model=f.run('state.healthViews.stress.model'),html=f.get('healthView-stress').innerHTML;
 const second=f.run('healthPage("stress",2)');assert.match(f.requests[1].url,/\/views\/stress\/records\?.*page=2/);
 const p=summary('stress',2);delete p.statistics;delete p.points;f.reply(1,p);await second;
 assert.equal(f.run('state.healthViews.stress.model'),model);assert.equal(model.cards[0].raw,33);assert.equal(f.get('healthView-stress').innerHTML,html);assert.match(f.get('healthView-stress-table').innerHTML,/2 \/ 3/);
 f.run('exportHealthRecords("stress")');assert.match(f.links[0],/^\/proxy\/api\/views\/stress\/export\?/);assert.doesNotMatch(f.links[0],/page=/);
});
test('test_late_page_and_overview_responses_do_not_overwrite_new_range',async()=>{
 const f=fixture(),initial=f.run('loadHealthView("stress")');f.reply(0,summary());await initial;
 const old=f.run('healthPage("stress",2)');f.get('startDate').value='2026-10-16';const fresh=f.run('loadHealthView("stress")');f.reply(2,summary('stress',1,5));await fresh;
 const html=f.get('healthView-stress').innerHTML,inspector=f.get('inspectorBody').innerHTML;
 f.reply(1,summary('stress',2));await old;f.calendars[0].resolve({ok:true,json:async()=>({years:{old:true}})});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(f.get('healthView-stress').innerHTML,html);assert.equal(f.get('inspectorBody').innerHTML,inspector);assert.equal(f.run('state.healthViews.stress.model.total'),5);
 f.run('state.activeTab="overview"');const overview=f.run('loadOverview()');f.get('endDate').value='2026-10-16';f.reply(3,{status:'ok',data:{steps:999}});await overview;assert.equal(f.get('statSteps').textContent,'--');assert.equal(f.get('inspectorBody').innerHTML.includes('999'),false);
});
test('switching type and filters rejects pending page results, latest page wins',async()=>{
 const f=fixture(),initial=f.run('loadHealthView("stress")');f.reply(0,summary());await initial;
 const a=f.run('healthPage("stress",2)'),b=f.run('healthPage("stress",3)');f.reply(2,summary('stress',3));await b;f.reply(1,summary('stress',2));await a;assert.equal(f.run('state.healthViews.stress.page'),3);
 const pending=f.run('healthPage("stress",2)');f.get('stressLevel').value='mild';f.run('state.activeTab="sleep"');f.reply(3,summary('stress',2));await pending;assert.equal(f.run('state.healthViews.stress.page'),3);
});
test('shrinking totals re-fetch the last valid page instead of showing false empty',async()=>{
 const f=fixture(),initial=f.run('loadHealthView("stress")');f.reply(0,summary());await initial;
 const pending=f.run('healthPage("stress",3)');const p=summary('stress',3,11);p.page.rows=[];f.reply(1,p);await new Promise(resolve=>setImmediate(resolve));assert.match(f.requests[2].url,/page=2/);f.reply(2,summary('stress',2,11));await pending;assert.equal(f.run('state.healthViews.stress.page'),2);assert.equal(f.run('state.healthViews.stress.model.total'),11);
});
test('test_empty_and_failure_remain_distinct',async()=>{
 const f=fixture();let p=f.run('loadHealthView("stress")');f.reply(0,{status:'error'});await p;assert.match(f.get('healthView-stress').innerHTML,/查询失败/);
 p=f.run('loadHealthView("stress")');const empty=summary('stress',1,0);empty.page.rows=[];f.reply(1,empty);await p;assert.match(f.get('healthView-stress').innerHTML,/未保存/);assert.doesNotMatch(f.get('healthView-stress').innerHTML,/查询失败/);
});
test('filters use exact Beijing dates and server selection parameters for all eight views',async()=>{
 const f=fixture();f.get('hrType').value='resting';f.get('hrLimit').value='25';f.get('stressLevel').value='unclassified';f.get('stressLimit').value='12';f.get('latestOnlyCheck').checked=true;
 for(const kind of HealthViews.kinds){f.context.kind=kind;f.run('state.activeTab=kind');const pending=f.run('loadHealthView(kind)');const i=f.requests.length-1;const u=new URL(f.requests[i].url,'http://local');assert.equal(u.pathname,'/proxy/api/views/'+kind);assert.equal(u.searchParams.get('start_date'),'2026-10-15');assert.equal(u.searchParams.get('end_date'),'2026-10-17');
 if(kind==='heartrate'){assert.equal(u.searchParams.get('limit'),'25');assert.equal(u.searchParams.get('sample_type'),'resting');}if(kind==='stress'){assert.equal(u.searchParams.get('pressure_level'),'unclassified');assert.equal(u.searchParams.get('limit'),'12');}if(kind==='body')assert.equal(u.searchParams.get('latest_only'),'true');
 f.reply(i,summary(kind));await pending;}
});

for(const change of ['date','type','filter','limit'])test(`pending pages and calendars reject changed ${change} selection`,async()=>{
 const f=fixture(),initial=f.run('loadHealthView("stress")');f.reply(0,summary());await initial;
 const page=f.run('healthPage("stress",2)'),model=f.run('state.healthViews.stress.model');
 if(change==='date')f.get('endDate').value='2026-10-16';
 if(change==='type')f.run('state.activeTab="sleep"');
 if(change==='filter')f.get('stressLevel').value='mild';
 if(change==='limit')f.get('stressLimit').value='5';
 const html=f.get('healthView-stress').innerHTML,inspector=f.get('inspectorBody').innerHTML;
 f.reply(1,summary('stress',2));await page;f.calendars[0].resolve({ok:true,json:async()=>({years:{unexpected:true}})});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(f.run('state.healthViews.stress.page'),1);assert.equal(model.range.calendar,undefined);assert.equal(f.get('healthView-stress').innerHTML,html);assert.equal(f.get('inspectorBody').innerHTML,inspector);
});
test('a current calendar can update date marks after paging without reverting rows',async()=>{
 const f=fixture(),initial=f.run('loadHealthView("stress")');f.reply(0,summary());await initial;
 const next=f.run('healthPage("stress",2)');f.reply(1,summary('stress',2));await next;
 f.calendars[0].resolve({ok:true,json:async()=>({years:{'2026':{days:[{date:'2026-10-16',isOffDay:true}],papers:['synthetic']}}})});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(f.run('state.healthViews.stress.page'),2);assert.equal(f.run('state.healthViews.stress.model.records[0].stress_score'),2);assert.match(f.get('healthView-stress').innerHTML,/2 \/ 3/);assert.match(f.get('healthView-stress').innerHTML,/stroke="#22a06b"/);
});
test('a failed page leaves summary intact and allows retrying the same page',async()=>{
 const f=fixture(),initial=f.run('loadHealthView("stress")');f.reply(0,summary());await initial;
 const html=f.get('healthView-stress').innerHTML;
 let next=f.run('healthPage("stress",2)');f.reply(1,{status:'error'});await next;assert.match(f.get('healthView-stress-table').innerHTML,/明细查询失败/);assert.equal(f.get('healthView-stress').innerHTML,html);assert.equal(f.run('state.healthViews.stress.page'),1);
 next=f.run('healthPage("stress",2)');f.reply(2,summary('stress',2));await next;assert.equal(f.run('state.healthViews.stress.page'),2);assert.doesNotMatch(f.get('healthView-stress-table').innerHTML,/查询失败/);
});
test('out-of-order overview loads preserve new range values and inspector',async()=>{
 const f=fixture();f.run('state.activeTab="overview"');const old=f.run('loadOverview()');f.get('startDate').value='2026-10-16';const current=f.run('loadOverview()');
 f.reply(1,{status:'ok',data:{steps:42}});await current;const inspector=f.get('inspectorBody').innerHTML;
 f.reply(0,{status:'ok',data:{steps:999}});await old;assert.equal(f.get('statSteps').textContent,'42');assert.equal(f.get('inspectorBody').innerHTML,inspector);assert.match(f.get('overviewRange').textContent,/2026-10-16 至 2026-10-17/);
});
