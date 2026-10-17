# 后端汇总与分页：最终审查及交付

日期：2026-10-17。状态：实现、本机验证、各任务审查及最终跨模块审查通过，尚未部署NAS。

主目录：D:\CodeProject\mi-fitness-health；分支nas-health；最终产品代码提交317194c（最后一提交仅为QA截图采样修正，产品实现截至6292755，部署脚本截至ecbd485）。本记录提交只更新文档，不改候选镜像、发布包或产品。

本机：85项Python、53项Node、7/30天八类页面、四身份原生附件、隔离容器验证完成。性能范围和限制见 backend-query-validation.md。90万心率旧响应73569039字节，新首屏3570字节；这不是NAS耗时测量。统计/图表/每页10条明细由服务器返回，CSV双端流式，不在浏览器构建全量数组。

离线包：artifacts/query-summary/release；tar SHA256为2aeb958f5251d25a8d749f289c725cbb38043e7e687c0cef1c2dce6c063509b9，manifest SHA256为a1a2d51843b4b3b5bbf71bbfb38c8ca87ab2733f83d41e7b1c875641f63e346e。已本机复核全部9项发布哈希，未带Deploy参数。

仅拟替换健康backend/web为local/mi-fitness-nas:20261017-summary8，worker保持audit3；原密码来源、数据库和密钥挂载、日历及端口不变，失败尝试回退。正式更新前仍需用户明确批准，并在本机交互终端输入sudo密码。

兼容副本已同步13个文件、0删除；最终复核0文件需更新，未覆盖并发修改。未推送网络仓库。

已知边界：一次早期浏览器采集只有Uncaught文本、没有堆栈；增强记录后的两轮完整验收未再现，原证据保留，未宣称修复。窄屏头部拥挤是保留的原样式。SQL仍随样本数扫描；大数据NAS查询耗时尚未实测。同刻多设备体重使用明确的稳定主键次序，个别latest可能与旧未定义次序不同，均值/样本集合不变。

## 最终独立审查原文

# 整分支最终独立审查

范围：`497fd1c..317194c21c51373b82decb351840ea9985dd349a`，分支 `nas-health`。首先阅读已批准的 `docs/nas/backend-query-design.md`、`docs/superpowers/plans/2026-10-17-backend-query-summary.md`，继而核对各任务已通过审查、最终验证记录、整分支产品/部署差异与直接调用方。本轮重点为跨模块集成，未重复局部全量审查或测试。

**Spec verdict：APPROVED。**

**Quality verdict：APPROVED。** 未发现本次引入且需要阻塞交付的新缺陷，无 must-fix。

## 跨模块证据

| 核查项 | 结果与位置 |
| --- | --- |
| 筛选集合贯通 | `storage/view_queries.py:95` 的共享 CTE 统一用户、北京时间范围、心率类型、小睡和压力等级，之后再取最近 N 条/最新记录。`:190`、`:219`、`:257`、`:264` 的统计、图表、分页总数及导出复用同一选择。`web_assets/static/js/health-ui.js:23` 为首屏、records、export 构造同一日期/筛选参数，导出不携带当前 page。 |
| 统计及前端消费 | `services/view_query_service.py:17` 输出统计、coverage、points 和 page；`health-views.js:128` 直接消费服务端统计，不以当前 10 条重算均值。分页 detail 使用 page.total 与当前 rows，`health-ui.js:88` 仅替换明细并在总数减少时回退有效末页。`app.js:374` 单次 overview 请求的字段与服务端 `view_query_service.py:31` 一致。睡眠实睡回退、缺失值、样本均值和体重全部测量均值保持设计口径。 |
| SQLite 一致性和排序 | `view_queries.py:86` 显式 query_only/BEGIN，`view_query_service.py:17` 将首屏所有读取置于同一事务；分页另开短事务。所有读取按真实整秒、小数秒、id 排序；北京时间归日避免 SQLite 毫秒舍入跨午夜。`storage/__init__.py:269` 最终关闭连接；未改数据库结构或同步写入实现。 |
| 旧响应与日历 | `health-ui.js:67` 的当前查询判断包含请求编号、类型、日期与筛选；`:88` 又核对分页编号和当前 model。日历晚到只作用于当前 model，并使用最新页码/rows 重绘。overview 另有请求编号与范围保护。已有前端测试明确覆盖这些交错路径。 |
| 查询/导出身份一致 | `app.js:152` 与 `health-ui.js:110` 共用 getHeaders：state Key 优先、输入框回退。浏览器 Key 用临时同源 POST 表单提交并立即清除；无 Key 保留原生 GET。`web.py:156` 和 `:180` 对服务器 Key 统一优先，并按大小写无关方式去除旧头，避免摘要/导出用户不同。POST 只对白名单导出转换为无 body GET。 |
| Origin 与授权 | `web.py:68` 的既有 Host、Basic、Origin 检查仍先于代理执行；新 API 仍经过全局 `_gate`（`api.py:176`），并由 `_resolve_context`（`:243`）解析身份。Key 未进入导出 URL，响应头白名单不回传鉴权头；after_request 保留 no-store。 |
| 双端流生命周期 | `api.py:978` 在每个导出的单一线程内创建、推进和关闭迭代器，取消时关闭任务排入原线程且不被 shutdown 丢弃；`:1003` 在发送失败/断开时显式 aclose。`view_queries.py:264` 分批 fetchmany(256)，finally 关游标。`web.py:195` 的 finally 与 `:203` 的 call_on_close 分别覆盖已消费及未开始消费的响应；没有全量 CSV 缓冲。正在执行的 SQLite 读取可先完成再关闭，是已有明确边界。 |
| 部署范围 | 对照既有 `deploy/compose.override.yml` 与 `deploy/query-summary/compose.override.yml`，除注释外仅 backend/web 镜像不同；worker、端口、密码来源、日历挂载相同，数据库挂载继承未改的 base compose。`update-health.sh:54` 只对 backend/web 使用 `up --no-deps --no-build --pull never`，另比较其他健康服务 id/image。`:50` 安装回退 trap，保留旧配置与镜像。 |
| 发布身份与生产核对 | `update-health.sh:25` 严格验证去末尾 CR/LF 后的 digest，仅接受同包索引/配置身份。`check-ready.py:35` 仅取 OpenAPI paths 元数据，不发健康查询/导出；资源、代理、匿名拒绝、挂载/端口和日历检查符合批准边界。最终截图提交仅改 QA，产品、镜像与发布包未因截图采样变化。 |

上述产品路径均相对于 `src/mi_fitness_mcp/`。

## 采信的验证及本轮检查

- 已核对 `docs/nas/backend-query-validation.md`、task-4-report.md、task-1-review.md、task-2-review.md、task-3-fix-1-review.md、task-4-fix-1-review.md，并阅读对应流式、分页测试和一致性入口的直接证据。
- 采信最终已有 **85 Python + 53 Node**、真实浏览器 16 视图与四种身份原生附件、独立 Linux 容器、合成 1x/10x 和发布身份/就绪模型验证。本轮没有重跑这些已有效的检查，也未把这些数字称为本轮执行结果。
- 本轮实际执行 `git diff --check 497fd1c..317194c`，exit 0；读取时 HEAD 为 `317194c21c51373b82decb351840ea9985dd349a`，工作区干净。未发现需要额外最小复现的具体产品疑点。

## 已知边界与交付结论

- 同刻体重旧 oracle 72.9、新稳定 id 次序 72.91 是已批准的规格差异，记录集合及均值不变，不列为回归。
- 首轮 Uncaught 缺 stack 无法归因，随后增强观测两轮未复现；继续保留其记录，不宣称已修复，也不单凭该历史事件要求重跑所有验收。
- SQLite 范围扫描仍随样本规模增长；90 万心率的本机统计仍约 8.3 秒。首屏约 3.6 KB 证明传输有界，不证明 NAS 即时响应。已有窄屏控件拥挤和依赖弃用警告不扩大处理。
- **NAS 未部署。** 本审查批准本机实现和可审阅发布候选，不代替仅替换 backend/web 的用户部署确认，也不声称 NAS 引擎导入已实测。
- 本轮仅新增本报告；未改产品、QA、部署源、发布包、Git index 或 HEAD；未连接 NAS，未读取真实健康记录、数据库或凭据。


## 执行中作出的决定（完整记录）

Ruling: Tool rejected a fresh implementation agent with thread limit reached. Reuse idle implementation agent with a fresh task brief, retain separate read-only reviewer — no close-agent capability is exposed — cost if wrong: more context carryover; narrow task scope and independent review mitigate it.

Ruling: CSV iteration must use one dedicated worker thread (including SQLite iterator creation/next/close), with async chunk delivery — SQLite connections are thread-bound and event-loop SQL would stall unrelated requests — cost if wrong: an extra worker per active export; no full-result buffering and lifecycle tests bound the cost.

Ruling: Preserve selected client identity for CSV via a same-origin POST form and export-only proxy adaptation — ordinary attachment links cannot send X-API-Key and returning a full Blob violates bounded browser memory — cost if wrong: a narrowly scoped POST download branch; test auth/Origin/GET compatibility and no Key in URL.

Ruling: For equal-instant body measurements, latest uses the approved time/id DESC order (synthetic tie72.9 vs72.91 now chooses72.91), not the old API's unspecified tie order — freeze the oracle, compare unambiguous fixtures and test ties separately — cost if wrong: one tied measurement may differ from old display; sample set and mean remain unchanged, report explicitly.
