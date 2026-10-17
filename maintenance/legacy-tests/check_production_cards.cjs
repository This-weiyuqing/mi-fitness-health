// 只读接口响应 -> 实际已部署脚本 -> 卡片数值，不读取浏览器凭据。
const fs=require('node:fs');
const vm=require('node:vm');
const payload=JSON.parse(fs.readFileSync(0,'utf8'));
const nodes=new Map();
const get=id=>{
  if(!nodes.has(id)) nodes.set(id,{textContent:'--',innerHTML:'',value:'2026-10-16'});
  return nodes.get(id);
};
const context=vm.createContext({document:{getElementById:get,querySelectorAll(){return [];},addEventListener(){}},localStorage:{getItem(){return '';},setItem(){}},responses:payload.responses,setTimeout(){},clearTimeout(){},setInterval(){},clearInterval(){},console});
vm.runInContext(payload.javascript,context);
vm.runInContext("showToast=()=>{}; api=async(method,path)=>responses[path.split('?')[0]];",context);
(async()=>{
  await vm.runInContext('loadOverview()',context);
  const cards=Object.fromEntries(['statSteps','statCalories','statDistance','statHr','statSleep','statSpo2','statStress'].map(id=>[id,get(id).textContent]));
  const source=payload.responses['/api/summary'].data;
  const known=source.find(row=>row.date==='2026-10-15');
  const report={deployed_script_populates_cards:cards.statSteps!=='--'&&cards.statCalories!=='--'&&cards.statSleep!=='--',phone_confirmed_day_unchanged:known?.steps===4691&&known?.active_kcal===596,cards};
  console.log(JSON.stringify(report));
  if(!report.deployed_script_populates_cards||!report.phone_confirmed_day_unchanged)process.exitCode=1;
})().catch(()=>{console.log(JSON.stringify({card_inspection_error:true}));process.exitCode=1;});
