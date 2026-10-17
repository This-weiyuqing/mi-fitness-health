const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const tabs=await(await fetch('http://127.0.0.1:18384/json')).json();
 const ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
 let id=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
 const call=(method,params={})=>new Promise((resolve,reject)=>{const k=++id;pending.set(k,{resolve,reject});ws.send(JSON.stringify({id:k,method,params}));});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const dir=path.resolve('work/axis-minimum-validation');fs.mkdirSync(dir,{recursive:true});
 const shot=async name=>{await pause(400);const s=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(dir,name+'.png'),Buffer.from(s.data,'base64'));};
 await call('Runtime.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1600,height:1050,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:'http://127.0.0.1:18364/'});
 for(let i=0;i<80;i++){await pause(100);if(await evaluate('document.readyState==="complete" && typeof HealthViews.referenceLayout==="function"'))break;}
 await evaluate(`state.theme='light';initTheme();showToast=()=>{};$('toastContainer').innerHTML='';setInspectorCollapsed(true);$('startDate').value='2026-09-18';$('endDate').value='2026-10-17';$$('.preset-pill').forEach(p=>p.classList.remove('active'));$('preset-30d').classList.add('active');window.testOriginalFetch=fetch;window.pressurePeak=18;fetch=async(url,options)=>String(url).startsWith('/proxy/api/stress')?new Response(JSON.stringify({status:'ok',data:Array.from({length:30},(_,i)=>({timestamp:new Date(Date.UTC(2026,8,18+i,8)).toISOString(),stress_score:i===15?window.pressurePeak:5+i%12,level:'source-original'}))}),{status:200}):testOriginalFetch(url,options);`);
 const results=[];
 for(const [kind,min] of [['body',40],['spo2',80],['heartrate',40]]){
  const actual=await evaluate(`(async()=>{await switchTab('${kind}');const m=state.healthViews['${kind}'].model;const layout=HealthViews.referenceLayout(m);return {kind:'${kind}',min:layout.min,max:layout.max,axisLabels:[...$('healthView-${kind}').querySelectorAll('svg text[text-anchor="end"]')].map(t=>t.textContent),bars:$('healthView-${kind}').querySelectorAll('rect:not(.health-reference-label)').length};})()`);
  assert.equal(actual.min,min);assert.equal(Number(actual.axisLabels[0]),min);assert.ok(actual.max>min);assert.ok(actual.bars>0);results.push(actual);await shot(kind+'-axis');
 }
 assert.deepEqual(errors,[]);const result={results,errors};fs.writeFileSync(path.join(dir,'axis-browser-check.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));ws.close();
})().catch(e=>{console.error(e);process.exit(1);});
