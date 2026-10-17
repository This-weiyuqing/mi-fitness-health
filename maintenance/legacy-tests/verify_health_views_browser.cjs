const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const tabs=await(await fetch('http://127.0.0.1:18384/json')).json();
 const ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise(r=>ws.onopen=r);let id=0;const pending=new Map(),errors=[];
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}};
 const call=(method,params={})=>new Promise((resolve,reject)=>{const k=++id;pending.set(k,{resolve,reject});ws.send(JSON.stringify({id:k,method,params}));});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 await call('Runtime.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1600,height:1050,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:'http://127.0.0.1:18364/'});
 for(let i=0;i<80;i++){await pause(100);if(await evaluate('document.readyState==="complete" && typeof loadHealthView==="function"'))break;}
 await evaluate(`setInspectorCollapsed(true);localStorage.setItem('mi_fitness_theme','light');state.theme='light';initTheme();showToast=()=>{};$('toastContainer').innerHTML='';$$('.preset-pill').forEach(p=>p.classList.remove('active'));$('preset-30d').classList.add('active');$('startDate').value='2026-09-18';$('endDate').value='2026-10-17';`);
 const results=[];const dir=path.resolve('work/health-ui-validation');fs.mkdirSync(dir,{recursive:true});
 for(const kind of ['activity','heartrate','sleep','workouts','body','spo2','stress','abnormal']){
  const r=await evaluate(`(async()=>{const start=performance.now();await switchTab('${kind}');const el=$('healthView-${kind}');const saved=state.healthViews['${kind}'];return {kind:'${kind}',ms:performance.now()-start,nodes:el.querySelectorAll('*').length,rows:el.querySelectorAll('tbody tr').length,records:saved?.model.records.length,empty:el.textContent.includes('未保存'),cards:el.querySelectorAll('.health-card').length,consoleHidden:$('inspectorPanel').hidden};})()`);
  assert.equal(r.cards,4);assert.ok(r.rows<=10);assert.ok(r.nodes<750);assert.ok(r.consoleHidden);results.push(r);
  if(['sleep','heartrate','body'].includes(kind)){
   await evaluate('document.querySelector(".app-content").scrollTop=0');await pause(350);
   const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(dir,kind+'.png'),Buffer.from(shot.data,'base64'));
  }
 }
 await evaluate("(async()=>{await switchTab('heartrate');healthPage('heartrate',2)})()");
 assert.equal(await evaluate("state.healthViews.heartrate.page"),2);
 assert.equal(await evaluate("$('healthView-heartrate').querySelectorAll('tbody tr').length"),10);
 await evaluate('setInspectorCollapsed(false)');
 assert.equal(await evaluate("getComputedStyle($('inspectorPanel')).display==='none'"),false);
 await call('Page.reload');await pause(700);
 assert.equal(await evaluate("$('inspectorPanel').hidden"),false);
 await evaluate("(async()=>{setInspectorCollapsed(true);showToast=()=>{};$('toastContainer').innerHTML='';state.theme='dark';initTheme();$('startDate').value='2026-09-18';$('endDate').value='2026-10-17';await switchTab('sleep')})()");
 await pause(350);let shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(dir,'sleep-dark.png'),Buffer.from(shot.data,'base64'));
 await call('Emulation.setDeviceMetricsOverride',{width:1100,height:900,deviceScaleFactor:1,mobile:false});
 assert.equal(await evaluate('document.documentElement.scrollWidth<=window.innerWidth'),true);
 await call('Emulation.setDeviceMetricsOverride',{width:760,height:900,deviceScaleFactor:1,mobile:false});
 const narrow=await evaluate('({width:document.documentElement.scrollWidth,viewport:window.innerWidth})');
 assert.equal(narrow.width<=narrow.viewport,true);
 await evaluate('setInspectorCollapsed(false)');
 assert.equal(await evaluate("getComputedStyle($('inspectorPanel')).display==='none'"),false);
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(dir,'browser-check.json'),JSON.stringify({results,errors,narrow},null,2));console.log(JSON.stringify({results,errors,narrow}));ws.close();
})().catch(e=>{console.error(e);process.exit(1);});
