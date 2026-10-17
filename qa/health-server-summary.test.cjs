const test=require('node:test');
const assert=require('node:assert/strict');
const H=require('../src/mi_fitness_mcp/web_assets/static/js/health-views.js');
const range={start:'2026-10-01',end:'2026-10-30'};
function payload(kind,statistics,total=90000){return {status:'ok',kind,statistics,coverage:23,stride:1,points:Array.from({length:30},(_,i)=>({date:`2026-10-${String(i+1).padStart(2,'0')}`,values:[40],missing:false})),page:{number:1,size:10,total,rows:Array.from({length:10},()=>({timestamp:'2026-10-15T00:00:00Z',stress_score:1,bpm:1,weight_kg:1,steps:1}))}};}
test('test_server_summary_drives_cards_without_raw_records',()=>{
 const m=H.fromSummary('stress',payload('stress',{count:90000,primary_mean:47.5,primary_min:0,primary_max:120}),range);
 assert.equal(m.cards[0].raw,47.5);assert.equal(m.cards[1].raw,0);assert.equal(m.cards[2].raw,120);assert.equal(m.cards[3].raw,23);
 assert.equal(m.references.find(r=>r.key==='average').value,47.5);assert.equal(m.records.length,10);assert.equal(m.total,90000);assert.equal(m.points.length,30);
 assert.match(H.detail(m),/90,000/);assert.match(H.detail(m),/1 \/ 9000/);assert.match(H.render(m),/health-calendar-mark/);
});
test('all eight kinds map numeric server statistics and latest projections',()=>{
 const cases={activity:[{primary_sum:800,total_active_kcal:50,total_distance_m:2500,mean_daily_steps:400},[800,50,2.5,23]],heartrate:[{passive_mean_bpm:70,resting_mean_bpm:60,primary_min:40,primary_max:180,primary_mean:69},[70,60,40,180]],sleep:[{mean_daily_asleep_minutes:450,mean_daily_deep_minutes:90,nap_count:3},[450,23,90,3]],workouts:[{count:17,primary_sum:600,total_distance_m:9000,total_calories_kcal:500},[17,600,9,500]],body:[{count:18,primary_mean:64,latest:{weight_kg:65,bmi:22,body_fat_pct:19}},[65,22,19,18]],spo2:[{primary_mean:97,primary_min:89,primary_max:100},[97,89,100,23]],abnormal:[{count:20,primary_sum:90,latest:{start_at:'2026-10-15T00:00:00Z'}},[20,90,23,null]]};
 for(const [kind,[stats,expected]] of Object.entries(cases)){
  const m=H.fromSummary(kind,payload(kind,stats),range);assert.deepEqual(m.cards.map(c=>c.raw),expected,kind);
  if(['body','spo2','heartrate'].includes(kind))assert.equal(H.referenceLayout(m).min,{body:40,spo2:80,heartrate:40}[kind]);
 }
});
test('server total governs empty chart even when a requested detail page has no rows',()=>{
 const p=payload('stress',{count:90000,primary_mean:null});p.page.rows=[];
 const m=H.fromSummary('stress',p,range);assert.match(H.render(m),/<svg/);assert.doesNotMatch(H.render(m),/未保存/);assert.ok(!m.references.some(r=>r.key==='average'));
 p.page.total=0;p.statistics.count=0;assert.doesNotMatch(H.render(H.fromSummary('stress',p,range)),/<svg/);
 const b=H.fromSummary('body',payload('body',{count:0,latest:null},0),range);assert.equal(b.cards[0].value,'—');
});

test('server points, fixed references and two-color date marks keep the existing renderer',()=>{
 const calendar={'2026':{days:[{date:'2026-10-01',isOffDay:true},{date:'2026-10-10',isOffDay:false}],papers:['synthetic']}};
 const p=payload('heartrate',{primary_mean:65,resting_mean_bpm:60,passive_mean_bpm:70,primary_min:40,primary_max:75});
 p.points=p.points.map(point=>({...point,values:[70,60,null]}));
 const m=H.fromSummary('heartrate',p,{...range,calendar}),html=H.render(m);
 assert.equal(m.points,p.points);assert.equal(H.referenceLayout(m).min,40);assert.equal(H.referenceLayout(m).max,70);assert.deepEqual(H.referenceLayout(m).outside.map(r=>r.value),[170]);
 const marks=[...html.matchAll(/<line class="health-calendar-mark"[^>]+/g)].map(x=>x[0]);assert.equal(marks.length,30);assert.ok(marks.every(x=>x.includes('y1="207" y2="207"')));assert.ok(marks[0].includes('stroke="#22a06b"'));assert.ok(marks[9].includes('stroke="#e78325"'));
});
