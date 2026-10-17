const test=require('node:test');const assert=require('node:assert/strict');
const h=require('../src/mi_fitness_mcp/web_assets/static/js/health-views.js');
const calendar={'2026':{year:2026,days:[{date:'2026-09-20',isOffDay:false},{date:'2026-10-01',isOffDay:true},{date:'2026-10-10',isOffDay:false}],papers:['https://www.gov.cn/example']}};
test('补班周末为工作日，法定假日为非工作日，未知年份明确降级',()=>{
 assert.equal(h.calendarDay('2026-09-20',calendar).off,false);
 assert.equal(h.calendarDay('2026-10-01',calendar).off,true);
 assert.equal(h.calendarDay('2026-10-10',calendar).off,false);
 assert.equal(h.calendarDay('2026-10-11',calendar).off,true);
 assert.equal(h.calendarDay('2027-01-02',calendar).provisional,true);
 assert.equal(h.calendarDay('2027-01-02',calendar).off,true);
});
test('每天短横线高度相同，橙色工作日、绿色非工作日，缺记录日期也标记',()=>{
 const m=h.build('activity',[{date:'2026-10-01',steps:1234}],{start:'2026-10-01',end:'2026-10-11',calendar});
 const html=h.render(m),marks=[...html.matchAll(/<line class="health-calendar-mark"[^>]+/g)].map(x=>x[0]);
 assert.equal(marks.length,11);assert.ok(marks.every(x=>x.includes('y1="207" y2="207"')));
 assert.ok(marks[0].includes('stroke="#22a06b"'));assert.ok(marks[9].includes('stroke="#e78325"'));
 assert.match(html,/工作日/);assert.match(html,/非工作日/);assert.equal(m.cards[0].raw,1234);
});
test('跨年查询分别判断日历，未收录年份给出提示，睡眠按北京时间醒来日',()=>{
 const m=h.build('sleep',[{start_at:'2026-12-31T23:00:00+08:00',end_at:'2027-01-01T00:30:00Z',time_asleep_minutes:480}],{start:'2026-12-31',end:'2027-01-02',calendar});
 assert.equal(m.points[1].date,'2027-01-01');assert.equal(m.points[1].values.reduce((a,b)=>a+(b||0),0),8);
 assert.match(h.render(m),/2027 年调休安排未更新/);
 const updated={...calendar,'2027':{year:2027,days:[{date:'2027-01-01',isOffDay:true}],papers:['https://www.gov.cn/example']}};
 assert.equal(h.calendarDay('2027-01-01',updated).off,true);
 assert.doesNotMatch(h.render(h.build('sleep',m.records,{...m.range,calendar:updated})),/调休安排未更新/);
});
test('多天合并柱不冒充单日属性，标记数量始终受限',()=>{
 const html=h.render(h.build('activity',[{date:'2026-01-01',steps:100}],{start:'2026-01-01',end:'2026-12-31',calendar}));
 assert.doesNotMatch(html,/class="health-calendar-mark"/);assert.match(html,/多日汇总不标注单日/);
});
