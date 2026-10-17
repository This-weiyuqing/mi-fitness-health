const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const file = path.resolve('src/mi_fitness_mcp/web_assets/static/js/app.js');
function dashboard(responses) {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, {textContent: '--', innerHTML: '', value: id === 'startDate' ? '2026-10-15' : '2026-10-16', classList: {add(){}, remove(){}}});
    return nodes.get(id);
  };
  const context = vm.createContext({
    localStorage: {getItem() {return '';}, setItem() {}},
    document: {getElementById: get, querySelectorAll() {return [];}, addEventListener() {}},
    responses, console, setTimeout() {}, clearTimeout() {}, setInterval() {}, clearInterval() {},
  });
 vm.runInContext(fs.readFileSync('src/mi_fitness_mcp/web_assets/static/js/health-ui.js','utf8'),context);
  vm.runInContext(fs.readFileSync(file, 'utf8'), context);
  vm.runInContext("showToast = () => {}; api = async (method, url) => responses[url.split('?')[0]] || {status:'ok',data:[]};", context);
  return {context, get};
}

test('overview aggregates the selected range instead of taking the latest day', async () => {
  const ui = dashboard({
    '/api/summary': {status:'ok',data:[{date:'2026-10-16',steps:4063,active_kcal:250,distance_m:2385},{date:'2026-10-15',steps:4691,active_kcal:596,distance_m:2979}]},
    '/api/heart-rate': {status:'ok',data:[{timestamp:'2026-10-16T09:00:00+08:00',bpm:62}]},
    '/api/sleep': {status:'ok',data:[{end_at:'2026-10-16T08:54:00+08:00',duration_minutes:517},{end_at:'2026-10-15T07:55:00+08:00',duration_minutes:474}]},
    '/api/spo2': {status:'ok',data:[{timestamp:'2026-10-16T09:00:00+08:00',spo2_pct:98}]},
    '/api/stress': {status:'ok',data:[{timestamp:'2026-10-16T09:00:00+08:00',stress_score:0}]},
  });
  await vm.runInContext('loadOverview()',ui.context);
  assert.equal(ui.get('statSteps').textContent, (8754).toLocaleString());
  assert.equal(String(ui.get('statCalories').textContent),'846');
  assert.equal(ui.get('statDistance').textContent,'5.36');
  assert.equal(String(ui.get('statHr').textContent),'62');
  assert.equal(ui.get('statSleep').textContent,'8.3');
  assert.equal(ui.get('statSpo2').textContent,'98%');
  assert.equal(String(ui.get('statStress').textContent),'0');
});

test('range averages include all samples and group naps by wake date without filling missing days', async () => {
  const ui=dashboard({
    '/api/heart-rate':{status:'ok',data:[{bpm:60},{bpm:70}]},
    '/api/spo2':{status:'ok',data:[{spo2_pct:96},{spo2_pct:98}]},
    '/api/stress':{status:'ok',data:[{stress_score:0},{stress_score:60}]},
    '/api/sleep':{status:'ok',data:[{end_at:'2026-10-15T07:55:00+08:00',duration_minutes:474},{end_at:'2026-10-16T08:54:00+08:00',duration_minutes:517},{end_at:'2026-10-16T14:00:00+08:00',duration_minutes:60,is_nap:true}]},
  });
  ui.get('startDate').value='2026-10-01';
  await vm.runInContext('loadOverview()',ui.context);
  assert.equal(String(ui.get('statHr').textContent),'65');
  assert.equal(ui.get('statSpo2').textContent,'97%');
  assert.equal(String(ui.get('statStress').textContent),'30');
  assert.equal(ui.get('statSleep').textContent,'8.8');
  assert.match(ui.get('statSleepCoverage').textContent,/2/);
});

test('30 day preset is inclusive and refreshes the overview without manual reload', async () => {
  const ui=dashboard({});
  vm.runInContext(`Date = class extends Date { constructor(...args) { super(...(args.length ? args : ['2026-10-16T12:00:00+08:00'])); } }; calls=[]; api=async(method,path)=>{ calls.push(path); return {status:'ok',data:[]}; };`,ui.context);
  await vm.runInContext("setDatePreset('30d')",ui.context);
  assert.equal(ui.get('startDate').value,'2026-09-17');
  assert.equal(ui.get('endDate').value,'2026-10-16');
  const calls=vm.runInContext('calls',ui.context);
  assert.equal(calls.length,5);
  assert.ok(calls.every(path=>!path.includes('limit=1')));
  await vm.runInContext("setDatePreset('yesterday')",ui.context);
  assert.equal(ui.get('startDate').value,'2026-10-15');
  assert.equal(ui.get('endDate').value,'2026-10-16');
});

test('empty date range clears old values rather than showing stale measurements', async () => {
  const ui=dashboard({});
  for (const id of ['statSteps','statCalories','statDistance','statHr','statSleep','statSpo2','statStress']) ui.get(id).textContent='old-value';
  await vm.runInContext('loadOverview()',ui.context);
  for (const id of ['statSteps','statCalories','statDistance','statHr','statSleep','statSpo2','statStress']) assert.equal(ui.get(id).textContent,'--');
});

test('daily table and metric chart consume response envelope without losing units', () => {
  const ui=dashboard({});
  ui.context.payload={status:'ok',data:[{date:'2026-10-15',steps:4691,active_kcal:596,distance_m:2979}]};
  vm.runInContext('renderSummaryVisual(payload)',ui.context);
  assert.match(ui.get('summaryVisualContainer').innerHTML,/596 kcal/);
  assert.match(ui.get('summaryVisualContainer').innerHTML,/2\.98 km/);
  ui.context.payload={status:'ok',data:[{date:'2026-10-15',value:4691}]};
  vm.runInContext("renderMetricChart(payload,'steps')",ui.context);
  assert.match(ui.get('metricChartContainer').innerHTML,/4,691/);
});

test('sleep timeline reads stage list and separately reported awake minutes', () => {
  const ui=dashboard({});
  ui.context.payload={status:'ok',data:[{end_at:'2026-10-16T08:54:00+08:00',duration_minutes:517,time_awake_minutes:85,stages:[{stage:'deep',minutes:120},{stage:'light',minutes:300},{stage:'rem',minutes:97}]}]};
  vm.runInContext('renderSleepTimeline(payload)',ui.context);
  const html=ui.get('sleepTimelineWrapper').innerHTML;
  assert.match(html,/深睡 120m/);
  assert.match(html,/浅睡 300m/);
  assert.match(html,/REM 97m/);
  assert.match(html,/清醒 85m/);
});

test('failed synchronization does not show a success message', async () => {
  const ui=dashboard({});
  vm.runInContext("notices=[]; showToast=(...args)=>notices.push(args); api=async()=>({status:'error'});",ui.context);
  await vm.runInContext('triggerSync(false)',ui.context);
  const notices=vm.runInContext('notices',ui.context);
  assert.ok(!notices.some(args=>args[2]==='success'));
  assert.ok(notices.some(args=>args[2]==='error'));
});

test('key list reads masked keys from envelope and safely renders labels', () => {
  const ui=dashboard({});
  ui.context.payload={status:'ok',data:[{key_masked:'mif_sk_abcde…1234',label:'<script>example</script>',user_id:'synthetic',created_at:'2026-10-16',revoked:false}]};
  vm.runInContext('renderKeysTable(payload)',ui.context);
  const html=ui.get('keysTableWrapper').innerHTML;
  assert.match(html,/mif_sk_abcde…1234/);
  assert.ok(!html.includes('<script>'));
  assert.match(html,/revokeKeyByPrefix\('mif_sk_abcde'\)/);
});
