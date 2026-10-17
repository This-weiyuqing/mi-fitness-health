"""本机修改网页资源，保留文件编码和换行。"""
from pathlib import Path
import re

base=Path('work/mi-fitness-mcp-cn/src/mi_fitness_mcp/web_assets')
def edit(path,fn):
    raw=path.read_bytes();crlf=b'\r\n' in raw
    text=raw.decode('utf-8').replace('\r\n','\n')
    updated=fn(text)
    path.write_bytes((updated.replace('\n','\r\n') if crlf else updated).encode('utf-8'))

def app(s):
    s=s.replace("  inspectorRequestId: 0,", "  inspectorRequestId: 0,\n  healthRequestId: 0,\n  healthViews: {},\n  healthController: null,")
    s=s.replace("  if (state.activeTab === 'overview') return loadOverview();", "  return reloadActiveView();",1)
    s=s.replace("function switchTab(tabId) {\n  state.activeTab = tabId;", "function switchTab(tabId) {\n  invalidateHealthQuery();\n  clearInspector();\n  state.activeTab = tabId;")
    s=s.replace("  if (tabId === 'overview') return loadOverview();", "  return reloadActiveView();",1)
    s=s.replace("      headers: getHeaders(),\n    };", "      headers: getHeaders(),\n      ...(view.signal ? {signal: view.signal} : {}),\n    };",1)
    replacements={
        'querySummary':"return loadHealthView('activity');",
        'queryHeartRate':"return loadHealthView('heartrate');",
        'querySleep':"return loadHealthView('sleep');",
        'queryWorkouts':"return loadHealthView('workouts');",
        'queryBody':"return loadHealthView('body');",
        'querySpo2':"return loadHealthView('spo2');",
        'queryStress':"return loadHealthView('stress');",
        'queryAbnormalHr':"return loadHealthView('abnormal');",
    }
    for name,body in replacements.items():
        s,n=re.subn(r'async function '+name+r'\(\) \{.*?\n\}',f'async function {name}() {{\n  {body}\n}}',s,count=1,flags=re.S)
        assert n==1,name
    s=s.replace('  initTheme();\n  initDates();','  initTheme();\n  initHealthViews();\n  initDates();',1)
    s=s.replace("      if (state.activeTab === 'overview') loadOverview();", "      clearInspector();\n      reloadActiveView();",1)
    return s

def html(s):
    s=s.replace('20261017-ui3','20261017-ui4')
    s=s.replace('<div class="main-layout">','<div class="main-layout inspector-collapsed" id="mainLayout">',1)
    s=s.replace('<aside class="app-inspector">','<aside class="app-inspector" id="inspectorPanel" hidden>',1)
    s=s.replace('<button class="preset-pill" data-preset="month" id="preset-month">本月</button>', '<button class="preset-pill" data-preset="month" id="preset-month">本月</button>\n          <button class="btn btn-outline btn-sm" id="inspectorToggle" onclick="toggleInspector()" aria-expanded="false" aria-controls="inspectorPanel" style="margin-left:auto">展开控制台</button>')
    for kind in ['activity','heartrate','sleep','workouts','body','spo2','stress','abnormal']:
        pattern=r'(<section class="tab-pane" id="tab-'+kind+r'">)(.*?)(\n        </section>)'
        s,n=re.subn(pattern,lambda m:m[1]+m[2]+'\n          <div class="health-results" id="healthView-'+kind+'" aria-live="polite"></div>'+m[3],s,count=1,flags=re.S)
        assert n==1,kind
    s=s.replace('<div id="summaryVisualContainer"','<div hidden id="summaryVisualContainer"').replace('<div id="sleepTimelineWrapper"','<div hidden id="sleepTimelineWrapper"')
    s=s.replace('<div class="btn-group">','<div class="btn-group">\n            <button class="btn btn-secondary btn-sm" onclick="setInspectorCollapsed(true)" title="收起控制台">收起</button>',1)
    s=s.replace('<script src="/static/js/app.js', '<script src="/static/js/health-views.js?v=20261017-ui4"></script>\n  <script src="/static/js/health-ui.js?v=20261017-ui4"></script>\n  <script src="/static/js/app.js',1)
    return s
edit(base/'static/js/app.js',app)
edit(base/'templates/index.html',html)
