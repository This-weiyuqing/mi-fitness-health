// 本机 Edge 实测，固定合成数据，不访问 NAS。
const fs = require('node:fs');
const path = require('node:path');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function main() {
  const tabs = await (await fetch('http://127.0.0.1:18382/json')).json();
  const tab = tabs.find(tab => tab.type === 'page');
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve,reject) => {ws.onopen=resolve;ws.onerror=reject;});
  let id=0;
  const pending = new Map();
  ws.onmessage = event => {
    const result=JSON.parse(event.data);
    if (result.id && pending.has(result.id)) {
      const {resolve,reject}=pending.get(result.id);pending.delete(result.id);
      result.error ? reject(result.error) : resolve(result.result);
    }
  };
  function call(method,params={}) {return new Promise((resolve,reject)=>{const next=++id;pending.set(next,{resolve,reject});ws.send(JSON.stringify({id:next,method,params}));});}
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');
  await call('Network.setBlockedURLs',{urls:['https://*']});
  await call('Emulation.setDeviceMetricsOverride',{width:1400,height:900,deviceScaleFactor:1,mobile:false});
  const version=process.argv[2] || 'before';
  const preset=process.argv[3] || '30d';
  await call('Page.navigate',{url:'http://127.0.0.1:18363/?version='+version});
  let ready=false;
  for(let i=0;i<100;i++) {
    await sleep(100);
    const result=await call('Runtime.evaluate',{expression:"document.readyState==='complete' && document.getElementById('statSpo2')?.textContent==='97%'",returnByValue:true});
    if(result.result.value){ready=true;break;}
  }
  if(!ready)throw new Error('Fixture dashboard did not become ready');
  const measured=await call('Runtime.evaluate',{expression:`(async()=>{
    const measurements={version:${JSON.stringify(version)},renders:0,render_ms:0,max_inspector_nodes:0};
    const original=renderJsonViewer;
    renderJsonViewer=function(data){const start=performance.now();original(data);measurements.render_ms+=performance.now()-start;measurements.renders++;measurements.max_inspector_nodes=Math.max(measurements.max_inspector_nodes,document.getElementById('inspectorBody').querySelectorAll('*').length);};
    const tasks=[];const observer=new PerformanceObserver(list=>tasks.push(...list.getEntries().map(entry=>entry.duration)));
    observer.observe({type:'longtask'});
    const start=performance.now();await setDatePreset(${JSON.stringify(preset)});
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    measurements.elapsed_ms=performance.now()-start;
    measurements.steps=document.getElementById('statSteps').textContent;
    measurements.spo2=document.getElementById('statSpo2').textContent;
    measurements.stress=document.getElementById('statStress').textContent;
    measurements.inspector_nodes=document.getElementById('inspectorBody').querySelectorAll('*').length;
    measurements.header_backdrop=getComputedStyle(document.querySelector('.top-header')).backdropFilter;
    measurements.inspector_visible=getComputedStyle(document.querySelector('.app-inspector')).display!=='none';
    await new Promise(resolve=>setTimeout(resolve,100));observer.disconnect();
    measurements.long_tasks=tasks;renderJsonViewer=original;
    return measurements;
  })()`,awaitPromise:true,returnByValue:true});
  if(measured.exceptionDetails)throw new Error(JSON.stringify(measured.exceptionDetails));
  const result=measured.result.value;
  result.preset=preset;
  const target=path.resolve('work/perf-validation/'+version+'-'+preset+'.json');
  fs.writeFileSync(target,JSON.stringify(result,null,2)+'\n','utf8');
  const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  fs.writeFileSync(path.resolve('work/perf-validation/'+version+'-'+preset+'.png'),Buffer.from(screenshot.data,'base64'));
  console.log(JSON.stringify(result));ws.close();
}
main().catch(error=>{console.error(error);process.exit(1);});
