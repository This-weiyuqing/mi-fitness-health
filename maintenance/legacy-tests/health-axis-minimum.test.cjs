const test=require('node:test');const assert=require('node:assert/strict');
const h=require('../mi-fitness-mcp-cn/src/mi_fitness_mcp/web_assets/static/js/health-views.js');
const range={start:'2026-10-01',end:'2026-10-30'};
test('体重40、血氧80、心率40为固定起点，上限继续按实际数据决定',()=>{
 for(const [kind,row,min,max] of [
 ['body',{timestamp:'2026-10-01T08:00:00+08:00',weight_kg:87.3},40,90],
 ['spo2',{timestamp:'2026-10-01T08:00:00+08:00',spo2_pct:97},80,100],
 ['heartrate',{timestamp:'2026-10-01T08:00:00+08:00',bpm:77,sample_type:'passive'},40,80]]){
  const m=h.build(kind,[row],range),layout=h.referenceLayout(m);
  assert.equal(layout.min,min);assert.equal(layout.max,max);
  assert.match(h.render(m),new RegExp('text-anchor="end">'+min+'<'));
 }
});
test('参考线和柱高使用相同的新轴比例，170不撑大心率轴',()=>{
 const m=h.build('body',[{timestamp:'2026-10-01T08:00:00+08:00',weight_kg:87.3}],range);
 const line=h.referenceLayout(m).inside.find(r=>r.value===65);
 assert.equal(line.lineY,93);
 const hr=h.referenceLayout(h.build('heartrate',[{timestamp:'2026-10-01T08:00:00+08:00',bpm:77,sample_type:'passive'}],range));
 assert.deepEqual(hr.outside.map(r=>r.value),[170]);assert.equal(hr.min,40);
});
test('低于下限的记录保留原值，图上明确标记且不产生负高度',()=>{
 const m=h.build('heartrate',[{timestamp:'2026-10-01T08:00:00+08:00',bpm:35,sample_type:'resting'}],range);
 const html=h.render(m);
 assert.equal(m.records[0].bpm,35);assert.equal(m.cards[1].raw,35);
 assert.match(html,/低于纵轴下限/);assert.ok(!/height="-/.test(html));
 assert.ok(h.referenceLayout(m).max>40);
});
test('其他图表继续从0开始，压力低于25时仍保持紧凑纵轴',()=>{
 for(const kind of ['activity','sleep','workouts','stress','abnormal'])assert.equal(h.referenceLayout(h.build(kind,[],range)).min,0);
 const m=h.build('stress',[{timestamp:'2026-10-01T08:00:00+08:00',stress_score:18}],range);
 assert.equal(h.referenceLayout(m).max,20);
});
