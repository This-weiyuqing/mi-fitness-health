const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const file='work/mi-fitness-mcp-cn/src/mi_fitness_mcp/web_assets/static/js/health-views.js';
const load=()=>{assert.ok(fs.existsSync(file),'健康数据展示模块尚未实现');return require('../../'+file);};
const range={start:'2026-10-15',end:'2026-10-17'};
test('睡眠按北京时间醒来日汇总并包含小睡，不以缺失补零',()=>{
 const h=load();const m=h.build('sleep',[
 {start_at:'2026-10-14T23:00:00+08:00',end_at:'2026-10-15T07:00:00+08:00',time_asleep_minutes:474,duration_minutes:480,time_awake_minutes:6,stages:[{stage:'deep',minutes:120},{stage:'light',minutes:300},{stage:'rem',minutes:54}]},
 {end_at:'2026-10-15T14:00:00+08:00',time_asleep_minutes:30,is_nap:1},
 {end_at:'2026-10-16T00:37:00Z',time_asleep_minutes:517}],range);
 assert.equal(m.cards[0].raw,510.5);assert.equal(m.cards[1].raw,2);assert.equal(m.cards[3].raw,1);
 assert.deepEqual(m.points.map(p=>p.values.reduce((s,x)=>s+(x??0),0)),[8.4,517/60,0]);
 assert.equal(m.points[2].missing,true);
});
test('心率均值不混合静息和被动记录，0压力保留且缺失不补零',()=>{
 const h=load();const m=h.build('heartrate',[{timestamp:'2026-10-15T08:00:00+08:00',bpm:60,sample_type:'resting'},{timestamp:'2026-10-15T08:01:00+08:00',bpm:100,sample_type:'passive'}],range);
 assert.equal(m.cards[0].raw,100);assert.equal(m.cards[1].raw,60);
 assert.deepEqual(m.points[0].values,[100,60,null]);
 const s=h.build('stress',[{timestamp:'2026-10-15T08:00:00+08:00',stress_score:0}],range);
 assert.equal(s.cards[0].raw,0);assert.equal(s.points[1].missing,true);
});
test('八类页面都有四项概览、图表和分页明细，空记录不代表正常',()=>{
 const h=load();for(const kind of h.kinds){
 const m=h.build(kind,[],range);assert.equal(m.cards.length,4);assert.ok(m.columns.length>=3);
 const html=h.render(m,1);assert.match(html,/health-trend/);assert.match(html,/health-details/);assert.match(html,/未保存/);
 }
});
test('大数据只渲染一页，图表点数有上限，完整导出不会漏行且阻止表格公式注入',()=>{
 const h=load();const rows=Array.from({length:10000},(_,i)=>({timestamp:'2026-10-15T08:00:00+08:00',bpm:60+i%20,sample_type:i===0?'=DANGEROUS()':'passive'}));
 const m=h.build('heartrate',rows,range);const html=h.render(m,1);
 assert.equal((html.match(/<tr>/g)||[]).length,11);assert.ok(html.length<22000);
 assert.ok(m.points.length<=120);assert.equal(m.records.length,10000);
 const csv=h.csv(m);assert.equal(csv.split('\r\n').length,10001);assert.match(csv,/'=DANGEROUS\(\)/);
 const last=h.render(m,1000);assert.match(last,/1000 \/ 1000/);
});
test('源文本转义，最新体重按时间确定，有限记录明确标注',()=>{
 const h=load();const m=h.build('body',[{timestamp:'2026-10-16T09:00:00+08:00',weight_kg:87.3},{timestamp:'2026-10-15T09:00:00+08:00',weight_kg:88}],{...range,note:'仅返回最新一条'});
 assert.equal(m.cards[0].raw,87.3);assert.match(h.render(m),/仅返回最新一条/);
 const a=h.build('workouts',[{start_at:'2026-10-15T08:00:00+08:00',activity_type:'<img src=x onerror=alert(1)>'}],range);
 assert.ok(!h.render(a).includes('<img'));
});
test('长范围体重分桶选桶内最近测量，卡片明细和图表都按北京时间日期过滤',()=>{
 const h=load();const m=h.build('body',[{timestamp:'2026-01-01T09:00:00+08:00',weight_kg:80},{timestamp:'2026-01-02T09:00:00+08:00',weight_kg:75}],{start:'2026-01-01',end:'2026-12-31'});
 assert.equal(m.points[0].values[0],75);
 const boundary=h.build('heartrate',[{timestamp:'2026-10-14T20:00:00Z',bpm:70,sample_type:'passive'},{timestamp:'2026-10-17T20:00:00Z',bpm:110,sample_type:'passive'}],range);
 assert.equal(boundary.records.length,1);assert.equal(boundary.cards[0].raw,70);
});
