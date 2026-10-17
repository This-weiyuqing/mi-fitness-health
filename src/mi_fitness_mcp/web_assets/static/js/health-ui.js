/* 查询页交互；沿用现有请求代理、日期和授权。 */
function invalidateHealthQuery(){
  ++state.healthRequestId;
  if(state.healthController)state.healthController.abort();
  state.healthController=null;
}
function clearInspector(){
  ++state.inspectorRequestId;
  state.lastResponse=null;state.lastRequestInfo=null;
  $('metaUrl').textContent='尚未查询';$('metaStatus').textContent='READY';$('metaLatency').textContent='—';
  $('inspectorBody').innerHTML='<div class="inspector-empty-state">当前页面尚未查询，旧页面的响应已清除。</div>';
}
function setInspectorCollapsed(collapsed){
  $('mainLayout').classList.toggle('inspector-collapsed',collapsed);
  $('inspectorPanel').hidden=collapsed;
  $('inspectorToggle').textContent=collapsed?'展开控制台':'收起控制台';
  $('inspectorToggle').setAttribute('aria-expanded',String(!collapsed));
  localStorage.setItem('mi_fitness_inspector_collapsed',String(collapsed));
}
function toggleInspector(){setInspectorCollapsed(!$('inspectorPanel').hidden);}
function healthPath(kind){
  const endpoints={activity:'/api/summary',heartrate:'/api/heart-rate',sleep:'/api/sleep',workouts:'/api/workouts',body:'/api/body-measurements',spo2:'/api/spo2',stress:'/api/stress',abnormal:'/api/abnormal-heart-beat'};
  let query=getRangeQuery(endpoints[kind]);
  // 接口按源日期筛选；时间戳类型向两侧各取一天，再按北京时间精确归属。
  if(kind!=='activity'&&getSd()&&getEd()){
    const shift=(date,n)=>new Date(Date.parse(date)+n*86400000).toISOString().slice(0,10);
    query=endpoints[kind]+'?start_date='+shift(getSd(),-1)+'&end_date='+shift(getEd(),1);
  }
  if(kind==='heartrate')query+=getSelQuery('hrType','sample_type');
  if(kind==='sleep')query+='&include_naps='+$('napsSelect').value;
  if(kind==='body')query+='&latest_only=false';

  return query;
}
function healthSelection(kind){
  const id={heartrate:'hrLimit',spo2:'spo2Limit',stress:'stressLimit'}[kind];
  const text=id?$(id).value.trim():'';
  return {limit:text?Number(text):null,latestOnly:kind==='body'&&$('latestOnlyCheck').checked,pressureLevel:kind==='stress'?$('stressLevel').value:'',note:healthScopeNote(kind)};
}
function healthScopeNote(kind){
  const notes=[];
  const limit={heartrate:'hrLimit',spo2:'spo2Limit',stress:'stressLimit'}[kind];
  if(limit&&$(limit).value.trim())notes.push('仅显示最近 '+$(limit).value.trim()+' 条；统计仅针对筛选结果');
  if(kind==='body'&&$('latestOnlyCheck').checked)notes.push('仅返回最新一条');
  if(kind==='sleep')notes.push($('napsSelect').value==='true'?'包含小睡':'不含小睡');
  if(kind==='heartrate'&&$('hrType').value)notes.push('采样类型 '+$('hrType').value);
  if(kind==='stress'&&$('stressLevel').value)notes.push('压力等级 '+({relaxed:'放松 1–25',mild:'轻度 26–50',moderate:'中度 51–80',severe:'重度 81–100'}[$('stressLevel').value]||$('stressLevel').value));
  return notes.join('；');
}
function reloadActiveView(){
  if(state.activeTab==='overview')return loadOverview();
  if(HealthViews.kinds.includes(state.activeTab))return loadHealthView(state.activeTab);
  if(state.activeTab==='series')return queryMetricSeries();
}
async function loadHealthView(kind){
  invalidateHealthQuery();
  const id=state.healthRequestId, start=getSd(),end=getEd();
  const container=$('healthView-'+kind);
  state.healthViews[kind]=null;
  clearInspector();
  if(!start||!end||start>end){container.innerHTML='<div class="glass-panel health-empty">请选择有效的开始和结束日期。</div>';return;}
  const selection=healthSelection(kind);
  if(selection.limit!==null&&(!Number.isInteger(selection.limit)||selection.limit<1)){container.innerHTML='<div class="glass-panel health-empty">数量限制需要填写正整数，或留空显示全部记录。</div>';return;}
  const path=healthPath(kind),selectionKey=JSON.stringify(selection);
  container.innerHTML='<div class="glass-panel health-empty">正在查询健康记录…</div>';
  const controller=new AbortController();state.healthController=controller;
  const calendarRequest=typeof fetch==='function'?fetch('/api/calendar?start='+start.slice(0,4)+'&end='+end.slice(0,4),{signal:controller.signal})
    .then(response=>response.ok?response.json():null).then(value=>value?.years||{}).catch(()=>({})):Promise.resolve({});
  const isCurrent=()=>id===state.healthRequestId&&state.activeTab===kind&&getSd()===start&&getEd()===end&&healthPath(kind)===path&&JSON.stringify(healthSelection(kind))===selectionKey;
  const result=await api('GET',path,null,{isCurrent,signal:controller.signal});
  if(!isCurrent())return;
  if(!result||result.status!=='ok'||!Array.isArray(result.data)){
    container.innerHTML='<div class="glass-panel health-empty" role="alert">查询失败，未显示旧数据。请重试或展开控制台查看原因。</div>';return;
  }
  try{
    const model=HealthViews.build(kind,result.data,{start,end,...selection});
    state.healthViews[kind]={model,page:1};
    container.innerHTML=HealthViews.render(model,1);
    // 日历晚到只更新当前查询，健康记录不等待外部日历下载。
    calendarRequest.then(calendar=>{
      if(!isCurrent()||state.healthViews[kind]?.model!==model)return;
      model.range.calendar=calendar;
      const page=state.healthViews[kind].page;
      container.innerHTML=HealthViews.render(model,page);
    });
  }catch(error){
    container.innerHTML='<div class="glass-panel health-empty" role="alert">数据展示失败，请检查日期范围或展开控制台查看原始记录。</div>';
  }
}
function healthPage(kind,page){
  const saved=state.healthViews[kind];if(!saved)return;
  saved.page=Math.min(Math.max(1,Math.ceil(saved.model.records.length/10)),Math.max(1,page));
  $('healthView-'+kind).querySelector('.health-table-page').innerHTML=HealthViews.detail(saved.model,saved.page);
}
function exportHealthRecords(kind){
  const saved=state.healthViews[kind];if(!saved)return;
  const blob=new Blob(['\uFEFF',HealthViews.csv(saved.model)],{type:'text/csv;charset=utf-8'});
  const url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download=`${saved.model.title}_${saved.model.range.start}_${saved.model.range.end}.csv`;
  document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function initHealthViews(){
  setInspectorCollapsed(localStorage.getItem('mi_fitness_inspector_collapsed')!=='false');
  for(const kind of HealthViews.kinds){
    $('healthView-'+kind).addEventListener('click',event=>{
      const button=event.target.closest('button');if(!button)return;
      if(button.hasAttribute('data-health-page'))healthPage(kind,Number(button.dataset.healthPage));
      if(button.hasAttribute('data-health-export'))exportHealthRecords(kind);
    });
  }
  for(const id of ['hrType','hrLimit','napsSelect','latestOnlyCheck','spo2Limit','stressLevel','stressLimit']){
    $(id).addEventListener('change',()=>reloadActiveView());
  }
}
