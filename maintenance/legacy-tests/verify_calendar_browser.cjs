const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const tabs=await(await fetch('http://127.0.0.1:18384/json')).json();
 const ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
 let id=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
 const call=(method,params={})=>new Promise((resolve,reject)=>{const k=++id;pending.set(k,{resolve,reject});ws.send(JSON.stringify({id:k,method,params}));});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const dir=path.resolve('work/calendar-validation');fs.mkdirSync(dir,{recursive:true});
 const shot=async name=>{await pause(400);const s=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(dir,name+'.png'),Buffer.from(s.data,'base64'));};
 await call('Runtime.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1600,height:1050,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:'http://127.0.0.1:18364/'});
 for(let i=0;i<80;i++){await pause(100);if(await evaluate('document.readyState==="complete" && typeof HealthViews.calendarDay==="function"'))break;}
 await evaluate(`state.theme='light';initTheme();showToast=()=>{};$('toastContainer').innerHTML='';setInspectorCollapsed(true);$('startDate').value='2026-09-18';$('endDate').value='2026-10-17';$$('.preset-pill').forEach(p=>p.classList.remove('active'));$('preset-30d').classList.add('active');`);
 const results=[];
 for(const kind of ['activity','heartrate','sleep','body','spo2','stress']){
  await evaluate(`switchTab('${kind}')`);
  for(let i=0;i<40;i++){if(await evaluate(`!!state.healthViews['${kind}']?.model.range.calendar?.['2026']`))break;await pause(50);}
  const actual=await evaluate(`(()=>{const el=$('healthView-${kind}'),marks=[...el.querySelectorAll('.health-calendar-mark')];return {kind:'${kind}',ys:[...new Set(marks.map(m=>m.getBoundingClientRect().y))],marks:marks.length,nodes:el.querySelectorAll('*').length,colors:Object.fromEntries(marks.map(m=>[m.dataset.date,m.getAttribute('stroke')])),warning:el.textContent.includes('调休安排未更新'),cards:el.querySelectorAll('.health-card').length};})()`);
  assert.equal(actual.marks,30);assert.equal(actual.ys.length,1);assert.equal(actual.warning,false);assert.equal(actual.cards,4);assert.ok(actual.nodes<800);
  assert.equal(actual.colors['2026-09-20'],'#e78325');assert.equal(actual.colors['2026-10-10'],'#e78325');assert.equal(actual.colors['2026-10-03'],'#22a06b');
  results.push(actual);if(kind==='sleep')await shot('sleep-workday-markers');
 }
 await evaluate(`state.theme='dark';initTheme();`);await shot('stress-workday-markers-dark');
 await evaluate(`$('startDate').value='2026-12-31';$('endDate').value='2027-01-02';const m=HealthViews.build('activity',[{date:'2027-01-01',steps:1234}],{start:'2026-12-31',end:'2027-01-02',calendar:state.healthViews.stress.model.range.calendar});$('healthView-stress').innerHTML=HealthViews.render(m);`);
 assert.equal(await evaluate(`$('healthView-stress').textContent.includes('2027 年调休安排未更新')`),true);
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(dir,'calendar-browser-check.json'),JSON.stringify({results,errors,cross_year_fallback:true},null,2));
 console.log(JSON.stringify({views:results.map(r=>({kind:r.kind,marks:r.marks,y:r.ys,nodes:r.nodes})),errors,cross_year_fallback:true}));ws.close();
})().catch(e=>{console.error(e);process.exit(1);});
