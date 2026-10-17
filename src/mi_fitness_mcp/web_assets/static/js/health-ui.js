/* 查询页交互；沿用现有请求代理、日期和授权。 */
function invalidateHealthQuery(){
  ++state.healthRequestId;
  if(state.healthController)state.healthController.abort();
  state.healthController=null;
  if(state.healthPageController)state.healthPageController.abort();
  state.healthPageController=null;
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
function healthPath(kind,endpoint=''){
  let query=getRangeQuery('/api/views/'+kind+endpoint);
  const selection=healthSelection(kind);
  if(kind==='heartrate')query+=getSelQuery('hrType','sample_type');
  if(kind==='sleep')query+='&include_naps='+$('napsSelect').value;
  if(kind==='body')query+='&latest_only='+selection.latestOnly;
  if(kind==='stress'&&selection.pressureLevel)query+='&pressure_level='+encodeURIComponent(selection.pressureLevel);
  if(selection.limit!==null)query+='&limit='+selection.limit;
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
  if(!result||result.status!=='ok'||!result.statistics||!Array.isArray(result.points)||!result.page||!Array.isArray(result.page.rows)){
    container.innerHTML='<div class="glass-panel health-empty" role="alert">查询失败，未显示旧数据。请重试或展开控制台查看原因。</div>';return;
  }
  try{
    const model=HealthViews.fromSummary(kind,result,{start,end,...selection});
    state.healthViews[kind]={model,page:model.page,isCurrent,path};
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
async function healthPage(kind,page){
  const saved=state.healthViews[kind];if(!saved||!saved.isCurrent())return;
  page=Math.min(1000000,Math.max(1,Math.min(Math.ceil(saved.model.total/10)||1,page)));
  if(state.healthPageController)state.healthPageController.abort();
  const controller=new AbortController();state.healthPageController=controller;
  const requestId=state.healthPageRequestId=(state.healthPageRequestId||0)+1;
  const isCurrent=()=>requestId===state.healthPageRequestId&&state.healthViews[kind]===saved&&saved.isCurrent();
  // 同步期间总数可能减少；退到有效末页，不把越界页误报为无数据。
  while(isCurrent()){
    const result=await api('GET',healthPath(kind,'/records')+'&page='+page,null,{isCurrent,signal:controller.signal});
    if(!isCurrent())return;
    const target=$('healthView-'+kind).querySelector('.health-table-page');
    if(!result||result.status!=='ok'||!result.page||!Array.isArray(result.page.rows)){
      target.innerHTML='<div class="health-empty" role="alert">明细查询失败，请重试。</div>'+HealthViews.detail(saved.model,saved.page);return;
    }
    const last=Math.max(1,Math.ceil(result.page.total/10));
    if(page>last){page=last;continue;}
    saved.page=result.page.number;saved.model.page=saved.page;
    saved.model.records=result.page.rows;saved.model.total=result.page.total;
    target.innerHTML=HealthViews.detail(saved.model,saved.page);return;
  }
}
function exportHealthRecords(kind){
  const saved=state.healthViews[kind];if(!saved||!saved.isCurrent())return;
  const path='/proxy'+healthPath(kind,'/export'),key=getHeaders()['X-API-Key'];
  if(key){
    // 原生附件下载通过短暂表单传查询身份，Key 不进入 URL 或长期 DOM。
    const form=document.createElement('form'),input=document.createElement('input');
    form.method='POST';form.action=path;form.hidden=true;form.autocomplete='off';
    input.type='hidden';input.name='api_key';input.value=key;
    form.appendChild(input);document.body.appendChild(form);
    try{form.submit();}finally{input.value='';form.remove();}
    return;
  }
  const link=document.createElement('a');
  link.href=path;link.download='';
  document.body.appendChild(link);link.click();link.remove();
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
