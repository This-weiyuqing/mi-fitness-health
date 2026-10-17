/* 本机 Edge 独立profile真实DOM验收，无第三方依赖。仅访问合成fixture。 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const ROOT=path.resolve(__dirname,'..');
const OUT=path.resolve(process.env.QUERY_QA_OUTPUT||path.join(ROOT,'artifacts/query-summary/browser'));
assert(OUT.startsWith(path.join(ROOT,'artifacts')+path.sep));
const EDGE=process.env.QUERY_QA_EDGE||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const BASE=process.env.QUERY_QA_URL||'http://127.0.0.1:18432';
assert(['127.0.0.1','localhost'].includes(new URL(BASE).hostname),'只允许本机fixture');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
class CDP{
 constructor(ws){this.ws=ws;this.next=0;this.pending=new Map();this.handlers=new Map();ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id){const p=this.pending.get(m.id);this.pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}else for(const fn of this.handlers.get(m.method)||[])fn(m.params,m.sessionId);});}
 send(method,params={},sessionId){return new Promise((resolve,reject)=>{const id=++this.next;this.pending.set(id,{resolve,reject});this.ws.send(JSON.stringify({id,method,params,sessionId}));});}
 on(method,fn){if(!this.handlers.has(method))this.handlers.set(method,[]);this.handlers.get(method).push(fn);}
}
async function main(){
 fs.mkdirSync(OUT,{recursive:true});
 const profile=path.join(OUT,'profile-'+Date.now());
 const edge=spawn(EDGE,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:'ignore'});
 let cdp;
 try{
  let port;for(let n=0;n<100;n++){try{port=fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0];break;}catch{await sleep(100);}}
  assert(port,'Edge未就绪');
  const info=await(await fetch('http://127.0.0.1:'+port+'/json/version')).json();
  const ws=new WebSocket(info.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});cdp=new CDP(ws);
  const {targetId}=await cdp.send('Target.createTarget',{url:'about:blank'});
  const {sessionId:sid}=await cdp.send('Target.attachToTarget',{targetId,flatten:true});
  const send=(m,p)=>cdp.send(m,p,sid);
  const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});assert(!r.exceptionDetails,JSON.stringify(r.exceptionDetails));return r.result.value;};
  const requests=[],errors=[],downloads=[],downloadStarts=[],responses=[],report={base:BASE,scope:'本机合成fixture；未接触用户浏览器或NAS',views:[],downloads:[],failures:[]};
  cdp.on('Network.requestWillBeSent',(p,s)=>{if(s===sid)requests.push({id:p.requestId,url:p.request.url,method:p.request.method});});
  cdp.on('Network.responseReceived',(p,s)=>{if(s===sid)responses.push({id:p.requestId,url:p.response.url,status:p.response.status,bytes:p.response.encodedDataLength});});
  cdp.on('Runtime.exceptionThrown',(p,s)=>{if(s===sid)errors.push(p.exceptionDetails);});
  cdp.on('Browser.downloadProgress',p=>downloads.push(p));
  cdp.on('Browser.downloadWillBegin',p=>downloadStarts.push(p));
  await send('Runtime.enable');await send('Network.enable');await send('Page.enable');
  // 通过真实Basic挑战建立浏览器凭据缓存；注入请求头无法代表原生GET附件认证。
  cdp.on('Fetch.requestPaused',(p,s)=>{if(s===sid)send('Fetch.continueRequest',{requestId:p.requestId}).catch(()=>{});});
  cdp.on('Fetch.authRequired',(p,s)=>{if(s===sid)send('Fetch.continueWithAuth',{requestId:p.requestId,authChallengeResponse:{response:'ProvideCredentials',username:'admin',password:'synthetic-web-password'}}).catch(()=>{});});
  await send('Fetch.enable',{handleAuthRequests:true});
  await cdp.send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:OUT,eventsEnabled:true});
  await send('Page.addScriptToEvaluateOnNewDocument',{source:"localStorage.setItem('mi_fitness_api_key','synthetic-query-key');"});
  await send('Page.navigate',{url:BASE});
  for(let n=0;n<100;n++){if(await evaluate("typeof switchTab==='function' && document.readyState==='complete'"))break;await sleep(100);}
  if(process.env.QUERY_QA_SCREENSHOTS_ONLY==='1'){
   await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
   await evaluate("(async()=>{$('hrLimit').value='';await setDatePreset('30d');await switchTab('heartrate');})()");
   assert(await evaluate("$('preset-30d').classList.contains('active')"));
   await sleep(4500);
   for(const theme of ['dark','light']){
    await evaluate(`state.theme='${theme}';initTheme();`);
    await sleep(500);
    fs.writeFileSync(path.join(OUT,theme+'.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
   }
   await send('Emulation.setDeviceMetricsOverride',{width:390,height:1100,deviceScaleFactor:1,mobile:false});
   await sleep(500);
   fs.writeFileSync(path.join(OUT,'narrow.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
   console.log('PASS: 1440px深浅主题与390px窄屏截图；只重拍截图，未重复性能/整体验证。');return;
  }
  await evaluate("$('startDate').value='2026-10-11';$('endDate').value='2026-10-17';loadOverview()");
  assert.equal(await evaluate("$('statSteps').textContent.includes('--')"),false);
  for(const days of [7,30])for(const kind of ['activity','heartrate','sleep','workouts','body','spo2','stress','abnormal']){
   const start=days===7?'2026-10-11':'2026-09-18',before=requests.length;
   const elapsed=await evaluate(`(async()=>{$('startDate').value='${start}';$('endDate').value='2026-10-17';$('hrLimit').value='';$('spo2Limit').value='';$('stressLimit').value='';$('latestOnlyCheck').checked=false;const t=performance.now();await switchTab('${kind}');return performance.now()-t;})()`);
   const value=await evaluate(`(()=>{const m=state.healthViews.${kind}?.model;return m?{rows:m.records.length,total:m.total,points:m.points.length,dom:document.querySelectorAll('*').length,html:$('healthView-${kind}').innerHTML,cards:m.cards.map(c=>c.raw),references:m.references}:null;})()`);
   assert(value,kind+'未生成模型');assert(value.rows<=10);assert(value.points<=120);assert(value.html.includes('<svg'),kind+'缺图表');
   const relevant=requests.slice(before).filter(r=>new URL(r.url).pathname==='/proxy/api/views/'+kind);
   assert.equal(relevant.length,1,kind+'首屏请求次数');
   const response=responses.find(r=>r.id===relevant[0].id);assert.equal(response.status,200);
   const body=await send('Network.getResponseBody',{requestId:relevant[0].id});const bytes=Buffer.byteLength(body.body);
   report.views.push({days,kind,detailRows:value.rows,total:value.total,points:value.points,domNodes:value.dom,summaryBytes:bytes,loadMs:Math.round(elapsed*100)/100});
   if(value.total>10){const chart=await evaluate(`$('healthView-${kind}').querySelector('svg').outerHTML`);await evaluate(`healthPage('${kind}',2)`);assert.equal(await evaluate(`state.healthViews.${kind}.page`),2);assert.equal(await evaluate(`$('healthView-${kind}').querySelector('svg').outerHTML`),chart);assert(requests.slice(before).some(r=>r.url.includes('/records?')&&r.url.includes('page=2')));}
  }
  await evaluate("(async()=>{$('hrLimit').value='31';await switchTab('heartrate');})()");
  assert(await evaluate("document.querySelector('#healthView-heartrate svg').innerHTML.includes('40')"),'心率纵轴下限');
  assert(await evaluate("state.healthViews.heartrate.model.references.length>0"),'参考线');
  for(let n=0;n<30;n++){if(await evaluate("Object.keys(state.healthViews.heartrate.model.range.calendar||{}).length>0"))break;await sleep(100);}
  assert(await evaluate("Object.keys(state.healthViews.heartrate.model.range.calendar||{}).length>0"),'日历未载入');
  assert(await evaluate("document.querySelector('#healthView-heartrate svg').innerHTML.includes('#22a06b')"),'非工作日颜色');
  await evaluate("setDatePreset('30d')");
  assert(await evaluate("$('preset-30d').classList.contains('active')"));
  for(const theme of ['light','dark']){
   await evaluate(`if(state.theme!=='${theme}')toggleTheme();`);
   await sleep(500);
   assert.equal(await evaluate("document.documentElement.dataset.theme"),theme);
   const image=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(OUT,theme+'.png'),Buffer.from(image.data,'base64'));
  }
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
  await sleep(500);
  fs.writeFileSync(path.join(OUT,'narrow.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
  await send('Emulation.clearDeviceMetricsOverride');
  // 手填、扫码state、server优先（独立fixture端口）均使用原生附件，不在浏览器读取CSV。
  for(const mode of ['input','state']){
   await evaluate(`(async()=>{state.apiKey=${mode==='state'?"'synthetic-query-key'":"''"};$('apiKeyInput').value='synthetic-query-key';$('hrLimit').value='31';await loadHealthView('heartrate');exportHealthRecords('heartrate');})()`);
   let completed;for(let n=0;n<150;n++){completed=downloads.filter(d=>d.state==='completed').length;if(completed>=report.downloads.length+1)break;await sleep(100);}
   assert(completed>=report.downloads.length+1,'原生附件未完成');
   const file=path.join(OUT,'mi_fitness_heartrate_2026-09-18_2026-10-17.csv');assert(fs.existsSync(file));
   const csv=fs.readFileSync(file,'utf8');assert.equal(csv.trim().split('\n').length,32);
   assert.equal(await evaluate("document.querySelectorAll('form input[name=api_key]').length"),0);
   const request=requests.filter(r=>r.url.includes('/heartrate/export?')).at(-1);assert.equal(request.method,'POST');assert(!request.url.includes('synthetic'));
   fs.renameSync(file,path.join(OUT,mode+'.csv'));report.downloads.push({mode,method:request.method,bytes:Buffer.byteLength(csv),rows:31});
  }
  const serverBase=process.env.QUERY_QA_SERVER_URL||'http://127.0.0.1:18433';
  assert(['127.0.0.1','localhost'].includes(new URL(serverBase).hostname));
  await send('Page.navigate',{url:serverBase});
  for(let n=0;n<100;n++){if(await evaluate("typeof switchTab==='function' && document.readyState==='complete' && location.port==='"+new URL(serverBase).port+"'"))break;await sleep(100);}
  for(const mode of ['server-only','server-priority']){
   await evaluate(`(async()=>{state.apiKey=${mode==='server-priority'?"'synthetic-other-key'":"''"};$('apiKeyInput').value='';$('startDate').value='2026-09-18';$('endDate').value='2026-10-17';$('hrLimit').value='31';await switchTab('heartrate');exportHealthRecords('heartrate');})()`);
   assert.equal(await evaluate('state.healthViews.heartrate.model.total'),31,'服务端Key身份应优先');
   let completed;for(let n=0;n<150;n++){completed=downloads.filter(d=>d.state==='completed').length;if(completed>=report.downloads.length+1)break;await sleep(100);}
   if(completed<report.downloads.length+1)fs.writeFileSync(path.join(OUT,'download-failure.json'),JSON.stringify({mode,downloads,requests:requests.slice(-8),responses:responses.slice(-8),errors},null,2));
   assert(completed>=report.downloads.length+1,'server Key原生附件未完成');
   const file=path.join(OUT,'mi_fitness_heartrate_2026-09-18_2026-10-17.csv'),csv=fs.readFileSync(file,'utf8');
   assert.equal(csv,fs.readFileSync(path.join(OUT,'input.csv'),'utf8'),'摘要/附件合成身份不一致');
   const download=downloadStarts.at(-1);assert(new URL(download.url).pathname==='/proxy/api/views/heartrate/export');assert(!download.url.includes('synthetic'));
   // GET原生链接target=_blank，下载由Browser事件观测；POST在当前页另验真实method。
   const method=mode==='server-only'?'GET (native anchor)':'POST';
   if(mode==='server-priority')assert.equal(requests.filter(r=>r.url.includes('/heartrate/export?')).at(-1).method,'POST');
   fs.renameSync(file,path.join(OUT,mode+'.csv'));report.downloads.push({mode,method,bytes:Buffer.byteLength(csv),rows:31});
  }
  // 真实代理故障和取消；取消只应留下当前范围的模型。
  await evaluate("(async()=>{const saved=window.fetch;window.fetch=(url,options)=>url.includes('/views/stress?')?Promise.resolve(new Response('{}',{status:503})):saved(url,options);await switchTab('stress');window.fetch=saved;})()");
  assert(await evaluate("$('healthView-stress').textContent.includes('查询失败')"));
  await evaluate("(async()=>{const original=window.fetch;window.fetch=(url,opt)=>url.includes('/views/stress?')?new Promise(resolve=>setTimeout(()=>resolve(new Response(JSON.stringify({status:'error'}))),300)):original(url,opt);const old=switchTab('stress');await switchTab('body');await old;window.fetch=original;})()");
  assert.equal(await evaluate('state.activeTab'),'body');assert(await evaluate('!!state.healthViews.body?.model'));
  const raw=requests.filter(r=>/\/proxy\/api\/(heart-rate|sleep|workouts|body-measurements|spo2|stress|abnormal-heart-beat|summary|metric-series)(\?|$)/.test(r.url));assert.deepEqual(raw,[],'浏览器不应调用全量原始接口');
  report.pageExceptions=errors;report.rawRequests=raw;report.requestCount=requests.length;
  fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify(report,null,2)+'\n','utf8');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify(report,null,2));
 }finally{if(cdp){await cdp.send('Browser.close').catch(()=>{});cdp.ws.close();}else edge.kill();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
