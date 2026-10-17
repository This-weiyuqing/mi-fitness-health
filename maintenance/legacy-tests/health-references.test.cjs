const test=require('node:test');
const assert=require('node:assert/strict');
const h=require('../mi-fitness-mcp-cn/src/mi_fitness_mcp/web_assets/static/js/health-views.js');
const range={start:'2026-10-01',end:'2026-10-30'};
const stress=values=>values.map((v,i)=>({timestamp:`2026-10-${String(i+1).padStart(2,'0')}T08:00:00+08:00`,stress_score:v,level:'old-source-level'}));
test('所有压力低于25时保持20以内的纵轴，25/50/80仅在上方标注，平均值在图内',()=>{
 const m=h.build('stress',stress([5,12,18]),range);
 assert.ok(Array.isArray(m.references),'参考线尚未实现');
 const layout=h.referenceLayout(m);
 assert.equal(layout.max,20);
 assert.deepEqual(layout.outside.map(r=>r.value),[25,50,80]);
 assert.deepEqual(layout.inside.map(r=>r.value),[35/3]);
 const html=h.render(m);
 assert.equal((html.match(/class="health-reference"/g)||[]).length,1);
 assert.match(html,/平均/);assert.match(html,/放松 1–25/);assert.match(html,/重度 81–100/);
});
test('58的压力数据纵轴至60，25/50在图内，80在上方；25恰在上界时不隐藏',()=>{
 const m=h.build('stress',stress([10,58]),range),layout=h.referenceLayout(m);
 assert.equal(layout.max,60);
 assert.ok(layout.inside.some(r=>r.value===25));assert.ok(layout.inside.some(r=>r.value===50));
 assert.deepEqual(layout.outside.map(r=>r.value),[80]);
 const edge=h.referenceLayout(h.build('stress',stress([25]),range));
 assert.equal(edge.max,25);assert.ok(edge.inside.some(r=>r.key==='stress-25'));
});
test('六类页面平均值按日期和筛选结果计算，心率170不撑高纵轴',()=>{
 const activity=h.build('activity',[{date:'2026-10-01',steps:4000},{date:'2026-10-02',steps:8000}],range);
 assert.equal(activity.references.find(r=>r.key==='average').value,6000);
 assert.equal(activity.references.find(r=>r.key==='fixed').value,7000);
 const seven=h.build('activity',[{date:'2026-10-01',steps:4000},{date:'2026-10-02',steps:8000}],{start:'2026-10-02',end:'2026-10-08'});
 assert.equal(seven.references.find(r=>r.key==='average').value,8000);
 const hr=h.build('heartrate',[{timestamp:'2026-10-01T08:00:00+08:00',bpm:60,sample_type:'resting'},{timestamp:'2026-10-01T08:01:00+08:00',bpm:100,sample_type:'passive'},{timestamp:'2026-10-01T08:02:00+08:00',bpm:110,sample_type:'passive'}],range);
 assert.equal(hr.references.find(r=>r.key==='average').value,90);
 assert.equal(hr.references.find(r=>r.key==='resting-average').value,60);
 assert.ok(h.referenceLayout(hr).max<170);assert.equal(h.referenceLayout(hr).outside[0].value,170);
 const sleep=h.build('sleep',[{end_at:'2026-10-01T08:00:00+08:00',time_asleep_minutes:420},{end_at:'2026-10-01T14:00:00+08:00',time_asleep_minutes:30,is_nap:1},{end_at:'2026-10-02T08:00:00+08:00',time_asleep_minutes:510}],range);
 assert.equal(sleep.references.find(r=>r.key==='average').value,8);assert.equal(sleep.references.find(r=>r.key==='fixed').value,8);
 const body=h.build('body',[{timestamp:'2026-10-01T08:00:00+08:00',weight_kg:80},{timestamp:'2026-10-02T08:00:00+08:00',weight_kg:84}],range);
 assert.equal(body.references.find(r=>r.key==='average').value,82);assert.equal(body.references.find(r=>r.key==='fixed').value,65);
 const spo2=h.build('spo2',[{timestamp:'2026-10-01T08:00:00+08:00',spo2_pct:94},{timestamp:'2026-10-02T08:00:00+08:00',spo2_pct:98}],range);
 assert.equal(spo2.references.length,1);assert.equal(spo2.references[0].value,96);
});
test('压力四档含边界，0保持未分类；筛选和导出不改源等级',()=>{
 for(const [v,name]of [[1,'放松'],[25,'放松'],[26,'轻度'],[50,'轻度'],[51,'中度'],[80,'中度'],[81,'重度'],[100,'重度'],[0,'未分类']])assert.equal(h.pressureBand(v).label,name);
 const m=h.build('stress',stress([0,25,26,50,51,80,81,100]),{...range,pressureLevel:'moderate',limit:1});
 assert.equal(m.records.length,1);assert.equal(m.records[0].stress_score,80);assert.equal(m.cards[0].raw,80);
 assert.match(h.csv(m),/old-source-level/);assert.match(h.csv(m),/压力等级（当前分界）/);assert.match(h.csv(m),/中度/);assert.match(h.detail(m),/中度/);
});
test('重叠均值和固定值的标注分开摆放；无数值不生成伪均值',()=>{
 const m=h.build('sleep',[{end_at:'2026-10-01T08:00:00+08:00',time_asleep_minutes:480}],range);
 const layout=h.referenceLayout(m);
 assert.equal(layout.inside.length,2);assert.ok(Math.abs(layout.inside[0].labelY-layout.inside[1].labelY)>=18);
 const empty=h.build('stress',[],range);assert.ok(!empty.references.some(r=>r.key==='average'));assert.ok(!h.render(empty).includes('class="health-reference"'));
 const zero=h.build('stress',stress([0]),range);assert.equal(zero.references.find(r=>r.key==='average').value,0);
});
