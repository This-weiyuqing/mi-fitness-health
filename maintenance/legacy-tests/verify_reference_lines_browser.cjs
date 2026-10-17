const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const tabs=await(await fetch('http://127.0.0.1:18384/json')).json();
 const ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
 let id=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
 const call=(method,params={})=>new Promise((resolve,reject)=>{const k=++id;pending.set(k,{resolve,reject});ws.send(JSON.stringify({id:k,method,params}));});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const dir=path.resolve('work/reference-lines-validation');fs.mkdirSync(dir,{recursive:true});
 const shot=async name=>{await pause(400);const s=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(dir,name+'.png'),Buffer.from(s.data,'base64'));};
 await call('Runtime.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1600,height:1050,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:'http://127.0.0.1:18364/'});
 for(let i=0;i<80;i++){await pause(100);if(await evaluate('document.readyState==="complete" && typeof HealthViews.referenceLayout==="function"'))break;}
 await evaluate(`state.theme='light';initTheme();showToast=()=>{};$('toastContainer').innerHTML='';setInspectorCollapsed(true);$('startDate').value='2026-09-18';$('endDate').value='2026-10-17';$$('.preset-pill').forEach(p=>p.classList.remove('active'));$('preset-30d').classList.add('active');window.testOriginalFetch=fetch;window.pressurePeak=18;fetch=async(url,options)=>String(url).startsWith('/proxy/api/stress')?new Response(JSON.stringify({status:'ok',data:Array.from({length:30},(_,i)=>({timestamp:new Date(Date.UTC(2026,8,18+i,8)).toISOString(),stress_score:i===15?window.pressurePeak:5+i%12,level:'source-original'}))}),{status:200}):testOriginalFetch(url,options);`);
 const stress=await evaluate(`(async()=>{await switchTab('stress');const m=state.healthViews.stress.model;return {max:HealthViews.referenceLayout(m).max,inside:HealthViews.referenceLayout(m).inside.map(r=>r.value),outside:HealthViews.referenceLayout(m).outside.map(r=>r.value),renderedLines:$('healthView-stress').querySelectorAll('.health-reference').length,sourceKept:m.records[0].level,columns:m.columns.length};})()`);
 assert.equal(stress.max,20);assert.deepEqual(stress.outside,[25,50,80]);assert.equal(stress.renderedLines,1);await shot('pressure-below25');
 const higher=await evaluate(`(async()=>{window.pressurePeak=58;await queryStress();const m=state.healthViews.stress.model;return {max:HealthViews.referenceLayout(m).max,outside:HealthViews.referenceLayout(m).outside.map(r=>r.value),lines:$('healthView-stress').querySelectorAll('.health-reference').length};})()`);
 assert.equal(higher.max,60);assert.deepEqual(higher.outside,[80]);assert.equal(higher.lines,3);await shot('pressure-below60');
 const selected=await evaluate(`(async()=>{$('stressLevel').value='moderate';await queryStress();return {count:state.healthViews.stress.model.records.length,average:state.healthViews.stress.model.cards[0].raw,text:$('healthView-stress').textContent};})()`);
 assert.equal(selected.count,1);assert.equal(selected.average,58);assert.match(selected.text,/中度/);
 const heart=await evaluate(`(async()=>{await switchTab('heartrate');const m=state.healthViews.heartrate.model;return {max:HealthViews.referenceLayout(m).max,outside:HealthViews.referenceLayout(m).outside.map(r=>r.value),inside:HealthViews.referenceLayout(m).inside.map(r=>r.key),bars:$('healthView-heartrate').querySelectorAll('rect:not(.health-reference-label)').length};})()`);
 assert.equal(heart.max,80);assert.deepEqual(heart.outside,[170]);assert.equal(heart.inside.length,2);assert.ok(heart.bars>30);await shot('heart-reference-lines');
 for(const kind of ['activity','sleep','body','spo2']){await evaluate(`switchTab('${kind}')`);await shot(kind+'-reference-lines');}
 await evaluate(`(async()=>{window.pressurePeak=18;$('stressLevel').value='';state.theme='dark';initTheme();await switchTab('stress');})()`);await shot('pressure-dark');
 await call('Emulation.setDeviceMetricsOverride',{width:760,height:900,deviceScaleFactor:1,mobile:false});
 assert.equal(await evaluate('document.documentElement.scrollWidth<=window.innerWidth'),true);
 assert.deepEqual(errors,[]);
 const result={stress,higher,selected:{count:selected.count,average:selected.average},heart,errors};fs.writeFileSync(path.join(dir,'reference-browser-check.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));ws.close();
})().catch(e=>{console.error(e);process.exit(1);});
