/* 健康数据展示：页面消费服务端摘要和当前页，build 保留为基线辅助。 */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.HealthViews=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const kinds=['activity','heartrate','sleep','workouts','body','spo2','stress','abnormal'];
  const finite=n=>typeof n==='number'&&Number.isFinite(n);
  const num=(v,p=1)=>finite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:p}):'—';
  const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const sum=(rows,key)=>{const a=rows.map(r=>r[key]).filter(finite);return a.length?a.reduce((s,x)=>s+x,0):null;};
  const avg=(rows,key)=>{const a=rows.map(r=>r[key]).filter(finite);return a.length?a.reduce((s,x)=>s+x,0)/a.length:null;};
  const extrema=(rows,key,maximum)=>{let v=null;for(const r of rows)if(finite(r[key]))v=v===null?r[key]:(maximum?Math.max(v,r[key]):Math.min(v,r[key]));return v;};
  function day(value){
    if(/^\d{4}-\d{2}-\d{2}$/.test(value||''))return value;
    const t=Date.parse(value);return Number.isFinite(t)?new Date(t+28800000).toISOString().slice(0,10):'';
  }
  function stamp(value){const t=Date.parse(value);return Number.isFinite(t)?new Date(t+28800000).toISOString().slice(0,19).replace('T',' '):'—';}
  const minutes=v=>finite(v)?`${Math.floor(Math.round(v)/60)}小时${Math.round(v)%60}分`:'—';
  const asleep=r=>finite(r.time_asleep_minutes)?r.time_asleep_minutes:r.duration_minutes;
  const stage=(r,s)=>{const a=(Array.isArray(r.stages)?r.stages:[]).filter(x=>x.stage===s&&finite(x.minutes));return a.length?a.reduce((n,x)=>n+x.minutes,0):null;};
  const card=(label,raw,unit='',note='',format=num)=>({label,raw,value:format(raw),unit,note});
  const colors=['#3186cb','#90c9f0','#ac92e7','#94a3b8'];
  const pressureLevels=[
    {key:'relaxed',label:'放松',min:1,max:25,color:'#22a06b'},
    {key:'mild',label:'轻度',min:26,max:50,color:'#d9a20b'},
    {key:'moderate',label:'中度',min:51,max:80,color:'#e78325'},
    {key:'severe',label:'重度',min:81,max:100,color:'#db5267'},
  ];
  function pressureBand(value){
    if(!finite(value)||value<1||value>100)return {key:'unclassified',label:'未分类'};
    return pressureLevels.find(level=>value<=level.max);
  }
  function calendarDay(date,calendar={}){
    const year=calendar?.[date.slice(0,4)];
    const known=year&&Array.isArray(year.days)&&year.days.length&&Array.isArray(year.papers)&&year.papers.length;
    const override=known?year.days.find(row=>row.date===date):null;
    const weekday=new Date(date+'T00:00:00Z').getUTCDay();
    return {off:override?override.isOffDay:weekday===0||weekday===6,provisional:!known};
  }
  function calendarLegend(m){
    if(!recordTotal(m))return '';
    if(m.stride>1)return '<div class="health-caption">多日汇总不标注单日工作属性；缩小到 120 天以内可查看每日标记。</div>';
    const missing=[...new Set(m.points.filter(p=>calendarDay(p.date,m.range.calendar).provisional).map(p=>p.date.slice(0,4)))];
    return `<div class="health-calendar-legend"><span><i style="background:#e78325"></i>工作日</span><span><i style="background:#22a06b"></i>非工作日</span></div><div class="health-caption">${missing.length?esc(missing.join('、'))+' 年调休安排未更新，暂按周一至周五/周末区分。':'按中国大陆节假日及调休安排标注。'}</div>`;
  }
  const config={
    activity:{title:'每日活动',date:'date',field:'steps',unit:'步',trend:'每日步数',mode:'sum',columns:[['日期','date'],['步数（步）','steps'],['距离（km）','distance_m',v=>finite(v)?num(v/1000,2):'—'],['活动热量（kcal）','active_kcal'],['总热量（kcal）','total_kcal'],['活动时长（分钟）','active_minutes']]},
    heartrate:{title:'心率监测',date:'timestamp',field:'bpm',unit:'bpm',trend:'每日心率均值',mode:'mean',columns:[['记录时间','timestamp',stamp],['心率（bpm）','bpm'],['采样类型','sample_type',v=>({resting:'静息',passive:'被动采样',active:'运动',manual:'手动'}[v]||v||'未标注')]]},
    sleep:{title:'睡眠分析',date:'end_at',field:'time_asleep_minutes',unit:'小时',trend:'每日睡眠时长',mode:'sleep',columns:[['醒来日期','end_at',day],['入睡时间','start_at',stamp],['醒来时间','end_at',stamp],['实睡时长','_asleep',minutes],['深睡','_deep',minutes],['浅睡','_light',minutes],['REM','_rem',minutes],['清醒（分钟）','time_awake_minutes'],['小睡','is_nap',v=>v?'是':'否'],['评分','sleep_score']]},
    workouts:{title:'运动记录',date:'start_at',field:'duration_minutes',unit:'分钟',trend:'每日运动时长',mode:'sum',columns:[['开始时间','start_at',stamp],['运动类型','activity_type'],['时长（分钟）','duration_minutes'],['距离（km）','distance_m',v=>finite(v)?num(v/1000,2):'—'],['热量（kcal）','calories_kcal'],['平均心率（bpm）','avg_heart_rate_bpm'],['最高心率（bpm）','max_heart_rate_bpm']]},
    body:{title:'体成分与体重',date:'timestamp',field:'weight_kg',unit:'kg',trend:'每日最近一次体重',mode:'latest',columns:[['测量时间','timestamp',stamp],['体重（kg）','weight_kg'],['BMI','bmi'],['体脂率（%）','body_fat_pct'],['肌肉量（kg，源字段）','muscle_mass_kg'],['水分（%）','water_pct'],['骨量（kg）','bone_mass_kg'],['内脏脂肪等级','visceral_fat_score'],['基础代谢（kcal/日）','basal_metabolism_kcal'],['代谢年龄（岁）','metabolic_age']]},
    spo2:{title:'血氧饱和度',date:'timestamp',field:'spo2_pct',unit:'%',trend:'每日血氧均值',mode:'mean',columns:[['记录时间','timestamp',stamp],['血氧（%）','spo2_pct'],['日期','timestamp',day]]},
    stress:{title:'压力指数',date:'timestamp',field:'stress_score',unit:'指数',trend:'每日压力均值',mode:'mean',columns:[['记录时间','timestamp',stamp],['压力指数','stress_score'],['等级','_pressureBand']]},
    abnormal:{title:'异常心跳',date:'start_at',field:'duration_seconds',unit:'次',trend:'每日已保存事件数',mode:'count',columns:[['开始时间','start_at',stamp],['结束时间','end_at',stamp],['持续时长（秒）','duration_seconds']]},
  };
  function build(kind,records,range){
    const c=config[kind];if(!c)throw new Error('不支持的查询类型');
    let rows=records.filter(r=>{const key=day(r[c.date]);return key&&key>=range.start&&key<=range.end;})
      .sort((a,b)=>Date.parse(b[c.date])-Date.parse(a[c.date]));
    if(kind==='stress'&&range.pressureLevel)rows=rows.filter(r=>pressureBand(r.stress_score).key===range.pressureLevel);
    if(range.latestOnly)rows=rows.slice(0,1);
    if(range.limit)rows=rows.slice(0,range.limit);
    const groups=new Map();
    for(const r of rows){const key=day(r[c.date]);if(key&&key>=range.start&&key<=range.end){if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);}}
    const coverage=groups.size, latest=rows[0]||{};
    let cards,legend=[c.trend];
    if(kind==='activity')cards=[card('期间总步数',sum(rows,'steps'),'步'),card('活动消耗',sum(rows,'active_kcal'),'kcal'),card('累计距离',sum(rows,'distance_m')===null?null:sum(rows,'distance_m')/1000,'km'),card('记录覆盖',coverage,'天')];
    else if(kind==='sleep'){
      const daily=[...groups.values()].map(g=>({minutes:sum(g.map(r=>({value:asleep(r)})),'value'),deep:sum(g.map(r=>({value:stage(r,'deep')})),'value')}));
      cards=[card('日均实睡',avg(daily,'minutes'),'','仅计算有记录的日期，含筛选后小睡',minutes),card('记录覆盖',coverage,'天'),card('日均深睡',avg(daily,'deep'),'','仅计算有深睡记录的日期',minutes),card('小睡记录',rows.filter(r=>r.is_nap).length,'次')];
      legend=['深睡','浅睡','REM','未分期'];
    }else if(kind==='heartrate'){
      cards=[card('被动心率均值',avg(rows.filter(r=>r.sample_type==='passive'),'bpm'),'bpm'),card('静息心率均值',avg(rows.filter(r=>r.sample_type==='resting'),'bpm'),'bpm'),card('最低心率',extrema(rows,'bpm',false),'bpm'),card('最高心率',extrema(rows,'bpm',true),'bpm')];
      legend=['被动采样','静息','其他类型'];
    }else if(kind==='workouts')cards=[card('运动次数',rows.length,'次'),card('运动时长',sum(rows,'duration_minutes'),'分钟'),card('累计距离',sum(rows,'distance_m')===null?null:sum(rows,'distance_m')/1000,'km'),card('运动热量',sum(rows,'calories_kcal'),'kcal')];
    else if(kind==='body')cards=[card('最近体重',latest.weight_kg,'kg'),card('最近 BMI',latest.bmi),card('最近体脂率',latest.body_fat_pct,'%'),card('测量记录',rows.length,'次',rows.length<2?'不足两次测量，无法判断体重变化趋势':'')];
    else if(kind==='abnormal')cards=[card('已保存事件',rows.length,'次'),card('累计时长',sum(rows,'duration_seconds'),'秒'),card('有记录日期',coverage,'天'),card('最近事件',null,'','',()=>rows.length?stamp(latest.start_at):'未保存')];
    else cards=[card(`平均${kind==='spo2'?'血氧':'压力'}`,avg(rows,c.field),c.unit),card('最低值',extrema(rows,c.field,false),c.unit),card('最高值',extrema(rows,c.field,true),c.unit),card('记录覆盖',coverage,'天')];
    const span=Math.floor((Date.parse(range.end)-Date.parse(range.start))/86400000)+1;
    if(!Number.isFinite(span)||span<1||span>3660)throw new Error('请选择有效日期范围（最多3660天）');
    const stride=Math.ceil(span/120), points=[];
    for(let i=0;i<span;i+=stride){
      const date=new Date(Date.parse(range.start)+i*86400000).toISOString().slice(0,10);
      const g=[];for(let j=i;j<Math.min(i+stride,span);j++){const key=new Date(Date.parse(range.start)+j*86400000).toISOString().slice(0,10);for(const r of groups.get(key)||[])g.push(r);}
      let values;
      if(kind==='sleep'){
        const total=sum(g.map(r=>({v:asleep(r)})),'v');
        const stages=['deep','light','rem'].map(s=>sum(g.map(r=>({v:stage(r,s)})),'v'));
        const phaseSum=stages.reduce((s,x)=>s+(x??0),0);
        values=total===null?[null,null,null,null]:phaseSum>total?[null,null,null,total/60]:[...stages.map(x=>x===null?null:x/60),Math.max(0,total-phaseSum)/60];
      }else if(kind==='heartrate')values=[avg(g.filter(r=>r.sample_type==='passive'),'bpm'),avg(g.filter(r=>r.sample_type==='resting'),'bpm'),avg(g.filter(r=>!['passive','resting'].includes(r.sample_type)),'bpm')];
      else if(c.mode==='latest'){
        const last=g.reduce((best,r)=>finite(r[c.field])&&(!best||Date.parse(r[c.date])>Date.parse(best[c.date]))?r:best,null);
        values=[last?.[c.field]??null];
      }
      else values=[!g.length?null:c.mode==='count'?g.length:c.mode==='sum'?sum(g,c.field):avg(g,c.field)];
      points.push({date,values,missing:values.every(x=>x===null)});
    }
    const labels=Object.fromEntries(c.columns.map(([label,key])=>[key,label]));
    const cell=(r,key)=>key==='_asleep'?asleep(r):key==='_deep'?stage(r,'deep'):key==='_light'?stage(r,'light'):key==='_rem'?stage(r,'rem'):key==='_pressureBand'?pressureBand(r.stress_score).label:r[key];
    const references=[];
    const reference=(key,label,value,color)=>{if(finite(value))references.push({key,label,value,color});};
    let referenceNote='';
    if(kind==='activity'){
      reference('average','日均',avg([...groups.values()].map(g=>({value:sum(g,'steps')})),'value'),'#d97706');
      reference('fixed','参考',7000,'#22a06b');referenceNote='平均步数按有步数记录的日期计算。';
    }else if(kind==='heartrate'){
      reference('average','总平均',avg(rows,'bpm'),'#d97706');
      reference('resting-average','静息平均',avg(rows.filter(r=>r.sample_type==='resting'),'bpm'),'#9467cf');
      reference('fixed','参考',170,'#db5267');referenceNote='总平均包含全部筛选样本，静息平均仅计算静息记录。';
    }else if(kind==='sleep'){
      reference('average','日均实睡',cards[0].raw===null?null:cards[0].raw/60,'#d97706');
      reference('fixed','参考',8,'#22a06b');referenceNote='平均线按有实睡记录的醒来日计算，包含筛选后的小睡。';
    }else if(kind==='body'){
      reference('average','平均',avg(rows,'weight_kg'),'#d97706');reference('fixed','参考',65,'#22a06b');
      referenceNote='平均线使用全部筛选体重测量记录；柱状图保留每日最近一次测量。';
    }else if(kind==='spo2'){
      reference('average','平均',avg(rows,'spo2_pct'),'#d97706');referenceNote='平均线按全部筛选血氧样本计算。';
    }else if(kind==='stress'){
      reference('average','平均',avg(rows,'stress_score'),'#d97706');
      pressureLevels.slice(0,3).forEach(level=>reference('stress-'+level.max,level.label+'上界',level.max,level.color));
      referenceNote='平均线按全部筛选压力样本计算；0 或超出 1–100 的数值保留为未分类。';
    }
    return {kind,...c,cards,legend,points,records:rows,range:{...range},coverage,stride,labels,cell,references,referenceNote};
  }
  function fromSummary(kind,payload,range){
    const c=config[kind];if(!c)throw new Error('不支持的查询类型');
    const s=payload.statistics,coverage=payload.coverage,latest=s.latest||{};
    const distance=finite(s.total_distance_m)?s.total_distance_m/1000:null;
    let cards,legend=[c.trend];
    if(kind==='activity')cards=[card('期间总步数',s.primary_sum,'步'),card('活动消耗',s.total_active_kcal,'kcal'),card('累计距离',distance,'km'),card('记录覆盖',coverage,'天')];
    else if(kind==='sleep'){
      cards=[card('日均实睡',s.mean_daily_asleep_minutes,'','仅计算有记录的日期，含筛选后小睡',minutes),card('记录覆盖',coverage,'天'),card('日均深睡',s.mean_daily_deep_minutes,'','仅计算有深睡记录的日期',minutes),card('小睡记录',s.nap_count,'次')];
      legend=['深睡','浅睡','REM','未分期'];
    }else if(kind==='heartrate'){
      cards=[card('被动心率均值',s.passive_mean_bpm,'bpm'),card('静息心率均值',s.resting_mean_bpm,'bpm'),card('最低心率',s.primary_min,'bpm'),card('最高心率',s.primary_max,'bpm')];
      legend=['被动采样','静息','其他类型'];
    }else if(kind==='workouts')cards=[card('运动次数',s.count,'次'),card('运动时长',s.primary_sum,'分钟'),card('累计距离',distance,'km'),card('运动热量',s.total_calories_kcal,'kcal')];
    else if(kind==='body')cards=[card('最近体重',latest.weight_kg,'kg'),card('最近 BMI',latest.bmi),card('最近体脂率',latest.body_fat_pct,'%'),card('测量记录',s.count,'次',s.count<2?'不足两次测量，无法判断体重变化趋势':'')];
    else if(kind==='abnormal')cards=[card('已保存事件',s.count,'次'),card('累计时长',s.primary_sum,'秒'),card('有记录日期',coverage,'天'),card('最近事件',null,'','',()=>s.count?stamp(latest.start_at):'未保存')];
    else cards=[card(`平均${kind==='spo2'?'血氧':'压力'}`,s.primary_mean,c.unit),card('最低值',s.primary_min,c.unit),card('最高值',s.primary_max,c.unit),card('记录覆盖',coverage,'天')];
    const references=[];
    const reference=(key,label,value,color)=>{if(finite(value))references.push({key,label,value,color});};
    let referenceNote='';
    if(kind==='activity'){
      reference('average','日均',s.mean_daily_steps,'#d97706');reference('fixed','参考',7000,'#22a06b');referenceNote='平均步数按有步数记录的日期计算。';
    }else if(kind==='heartrate'){
      reference('average','总平均',s.primary_mean,'#d97706');reference('resting-average','静息平均',s.resting_mean_bpm,'#9467cf');reference('fixed','参考',170,'#db5267');referenceNote='总平均包含全部筛选样本，静息平均仅计算静息记录。';
    }else if(kind==='sleep'){
      reference('average','日均实睡',finite(s.mean_daily_asleep_minutes)?s.mean_daily_asleep_minutes/60:null,'#d97706');reference('fixed','参考',8,'#22a06b');referenceNote='平均线按有实睡记录的醒来日计算，包含筛选后的小睡。';
    }else if(kind==='body'){
      reference('average','平均',s.primary_mean,'#d97706');reference('fixed','参考',65,'#22a06b');referenceNote='平均线使用全部筛选体重测量记录；柱状图保留每日最近一次测量。';
    }else if(kind==='spo2'){
      reference('average','平均',s.primary_mean,'#d97706');referenceNote='平均线按全部筛选血氧样本计算。';
    }else if(kind==='stress'){
      reference('average','平均',s.primary_mean,'#d97706');pressureLevels.slice(0,3).forEach(level=>reference('stress-'+level.max,level.label+'上界',level.max,level.color));referenceNote='平均线按全部筛选压力样本计算；0 或超出 1–100 的数值保留为未分类。';
    }
    const labels=Object.fromEntries(c.columns.map(([label,key])=>[key,label]));
    const cell=(r,key)=>key==='_pressureBand'?pressureBand(r.stress_score).label:r[key];
    return {kind,...c,cards,legend,points:payload.points,records:payload.page.rows,total:payload.page.total,page:payload.page.number,range:{...range},coverage,stride:payload.stride,labels,cell,references,referenceNote};
  }
  const recordTotal=m=>m.total??m.records.length;
  function referenceLayout(m){
    const stacked=m.kind==='sleep',min=({body:40,spo2:80,heartrate:40})[m.kind]??0;let dataMax=min;
    for(const point of m.points)dataMax=Math.max(dataMax,stacked?point.values.reduce((s,v)=>s+(v??0),0):Math.max(...point.values.map(v=>v??0)));
    const span=dataMax>min?dataMax-min:min>0?10:1;
    const power=10**Math.floor(Math.log10(span));
    const rounded=[1,1.2,1.5,2,2.5,3,4,5,6,8,10].find(n=>n>=span/power)||10;
    const max=min+rounded*power;
    const inside=m.references.filter(r=>r.value>=min&&r.value<=max).map(r=>({...r,lineY:172-(r.value-min)/(max-min)*158})).sort((a,b)=>a.lineY-b.lineY);
    inside.forEach((r,i)=>{r.labelY=Math.max(25,Math.min(164,r.lineY-5),i?inside[i-1].labelY+19:25);});
    if(inside.length&&inside.at(-1).labelY>164){const shift=inside.at(-1).labelY-164;inside.forEach(r=>r.labelY-=shift);}
    return {min,max,inside,outside:m.references.filter(r=>r.value>max||r.value<min)};
  }
  function referenceHeader(m){
    const layout=referenceLayout(m),outside=recordTotal(m)?layout.outside:[];
    if(!outside.length)return '';
    return `<div class="health-reference-overflow">${outside.map(r=>`<span class="health-reference-badge" style="color:${r.color}" title="超出当前纵轴，仅在上方标注">${esc(r.label)} ${esc(num(r.value))}${esc(m.unit)} ${r.value<layout.min?'↓':'↑'}</span>`).join('')}<span class="health-caption">超出当前纵轴</span></div>`;
  }
  function pressureLegend(m){
    return m.kind==='stress'?`<div class="health-pressure-legend">${pressureLevels.map(level=>`<span><i style="background:${level.color}"></i>${level.label} ${level.min}–${level.max}</span>`).join('')}</div>`:'';
  }
  function chart(m){
    if(!recordTotal(m))return '<div class="health-empty">NAS 在所选期间未保存此类记录。未保存不表示正常或没有发生。</div>';
    const height=158, step=880/m.points.length, stacked=m.kind==='sleep';
    const layout=referenceLayout(m),max=layout.max,min=layout.min;let content='',below=false;
    for(let i=0;i<=4;i++){const y=14+height-i*height/4;content+=`<line x1="58" y1="${y}" x2="948" y2="${y}" class="health-grid"/><text x="48" y="${y+4}" text-anchor="end">${esc(num(min+(max-min)*i/4))}</text>`;}
    m.points.forEach((p,i)=>{
      const x=62+i*step,width=Math.min(step*.65,24);let base=14+height;
      if(p.missing)content+=`<text x="${x+step/2}" y="${base-4}" text-anchor="middle" class="health-missing">·</text>`;
      p.values.forEach((v,j)=>{if(v===null)return;const h=(stacked?v:Math.max(min,v)-min)/(max-min)*height;
        const bx=stacked?x+(step-width)/2:x+(step-width)/2+j*width/p.values.length;
        const bw=stacked?width:width/p.values.length;
        const y=stacked?base-h:14+height-h;
        content+=`<rect x="${bx}" y="${y}" width="${bw}" height="${h}" fill="${colors[j]}"><title>${esc(p.date)} ${esc(m.legend[j])}：${esc(num(v,2))} ${esc(m.unit)}</title></rect>`;
        if(v<min){below=true;content+=`<text x="${bx+bw/2}" y="172" text-anchor="middle"><title>${esc(p.date)} ${esc(num(v,2))}${esc(m.unit)}，低于纵轴下限 ${min}</title>↓</text>`;}
        if(stacked)base=y;
      });
      if(i===0||i===m.points.length-1||i%Math.max(1,Math.ceil(m.points.length/7))===0)content+=`<text x="${x+step/2}" y="194" text-anchor="middle">${esc(p.date.slice(5))}</text>`;
      if(m.stride===1){
        const classification=calendarDay(p.date,m.range.calendar),cx=x+step/2,half=Math.min(4,step*.3);
        content+=`<line class="health-calendar-mark" data-date="${p.date}" x1="${cx-half}" x2="${cx+half}" y1="207" y2="207" stroke="${classification.off?'#22a06b':'#e78325'}" stroke-width="2.5" stroke-linecap="round"><title>${p.date} ${classification.off?'非工作日':'工作日'}${classification.provisional?'（暂按周末判断，调休安排未更新）':''}</title></line>`;
      }
    });
    for(const r of layout.inside){
      const label=`${r.label} ${num(r.value)}${m.unit}`;
      const width=Math.min(225,[...label].reduce((n,c)=>n+(c.charCodeAt(0)>255?11:6.5),12));
      content+=`<line class="health-reference" data-reference-key="${r.key}" data-reference-value="${r.value}" x1="58" y1="${r.lineY}" x2="948" y2="${r.lineY}" stroke="${r.color}" stroke-width="1.2" stroke-dasharray="5 4"/>`;
      content+=`<path d="M65 ${r.lineY} L65 ${r.labelY-5}" stroke="${r.color}" fill="none"/><rect class="health-reference-label" x="66" y="${r.labelY-12}" width="${width}" height="17" rx="3" stroke="${r.color}" stroke-width="0.5"/><text x="71" y="${r.labelY}" style="fill:${r.color}">${esc(label)}</text>`;
    }
    return `<svg viewBox="0 0 960 220" role="img" aria-label="${esc(m.trend)}（${esc(m.unit)}）">${content}</svg>${calendarLegend(m)}${below?'<div class="health-caption">↓ 表示低于纵轴下限；明细和统计保留原值。</div>':''}`;
  }
  function detail(m,page=1){
    const total=recordTotal(m),pages=Math.max(1,Math.ceil(total/10));page=Math.min(pages,Math.max(1,m.total===undefined?page:m.page));
    const slice=m.total===undefined?m.records.slice((page-1)*10,page*10):m.records;
    return `<div class="data-table-container"><table class="data-table"><thead><tr>${m.columns.map(([label])=>`<th>${esc(label)}</th>`).join('')}</tr></thead><tbody>${slice.map(r=>`<tr>${m.columns.map(([,key,format])=>{const value=m.cell(r,key);return `<td>${esc(format?format(value):finite(value)?num(value,2):value)}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div>${!total?'<div class="health-empty">NAS 在所选期间未保存此类记录</div>':''}<div class="health-pagination"><span>共 ${total.toLocaleString('zh-CN')} 条 · 每页 10 条</span><div><button class="btn btn-outline btn-sm" data-health-page="${page-1}" ${page===1?'disabled':''}>上一页</button><span> ${page} / ${pages} </span><button class="btn btn-outline btn-sm" data-health-page="${page+1}" ${page===pages?'disabled':''}>下一页</button></div></div>`;
  }
  function render(m,page=1){
    const title=`${m.range.start} 至 ${m.range.end} · 北京时间`;
    return `<div class="health-range">${esc(title)}${m.range.note?` · ${esc(m.range.note)}`:''}</div><div class="health-cards">${m.cards.map(c=>`<div class="health-card"><div>${esc(c.label)}</div><strong>${esc(c.value)} <small>${esc(c.unit)}</small></strong><div class="health-caption">${esc(c.note)}</div></div>`).join('')}</div><section class="glass-panel health-trend"><div class="panel-header"><h3>${esc(m.trend)}（${esc(m.unit)}）</h3><div class="health-legend">${m.legend.map((v,i)=>`<span><i style="background:${colors[i]}"></i>${esc(v)}</span>`).join('')}</div></div>${referenceHeader(m)}${chart(m)}${pressureLegend(m)}<div class="health-caption">${esc(m.referenceNote)}缺失记录留空，不补 0；悬停可查看数值。${m.stride>1?`每柱汇总 ${m.stride} 天，明细保留全部记录。`:''}${m.kind==='sleep'?'按醒来日期汇总，实睡不含清醒。阶段数据不完整或不一致时显示为未分期。':''}</div></section><section class="glass-panel health-details"><div class="panel-header"><h3>${esc(m.title)}明细</h3><button class="btn btn-outline btn-sm" data-health-export>导出全部查询结果</button></div><div class="health-table-page">${detail(m,page)}</div></section>`;
  }
  function csv(m){
    // 导出完整接口字段；防止电子表格把源文本作为公式执行。
    const keys=[...new Set(m.records.flatMap(r=>Object.keys(r)))];
    if(m.kind==='stress')keys.push('_pressureBand');
    const quote=v=>{let s=v===null||v===undefined?'':typeof v==='object'?JSON.stringify(v):String(v);if(typeof v==='string'&&/^[\s]*[=+@-]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};
    const header=k=>m.kind==='stress'&&k==='level'?'源等级（原值）':k==='_pressureBand'?'压力等级（当前分界）':m.labels[k]||k;
    return [keys.map(k=>quote(header(k))).join(','),...m.records.map(r=>keys.map(k=>quote(k==='_pressureBand'?m.cell(r,k):r[k])).join(','))].join('\r\n');
  }
  return {kinds,build,fromSummary,render,detail,csv,day,stamp,pressureBand,referenceLayout,calendarDay};
});
