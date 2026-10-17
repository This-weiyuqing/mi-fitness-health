# 后端汇总与分页查询 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将健康页面的样本汇总、筛选、分页和导出移到后端，显著减少浏览器接收与处理的数据，保持现有展示和统计口径。

**Architecture:** SQLite在只读事务内完成筛选、聚合与首屏分页，专用查询服务输出数值统计和图表点。新增只读接口供网页使用，已有原始查询接口保留；前端继续负责文字格式化、图表坐标和布局。CSV通过后端和网页代理逐段传输，不在任一层先收集全部记录。

**Tech Stack:** 现有Python 3.11+、SQLite、FastAPI、Flask/httpx与原生JavaScript/SVG，不增加产品依赖。

**Spec:** `docs/nas/backend-query-design.md`，用户于2026-10-17确认“按此设计继续”。

## Global Constraints

- 主代码目录：`D:\CodeProject\mi-fitness-health`；分支`nas-health`，当前基线`8546ba2`。
- 所有开发、合成数据和性能测试在本机执行。NAS只做正式部署和必要的就绪核对。
- 保持现有八类健康数据查询页面、指标口径、参考线、纵轴下限、工作日颜色与分页交互。
- 首屏明细固定每页10条，图表最多120桶；日期范围最多3660天，页码正整数且最大1000000。
- 不新增数据表、不重写历史时间戳；不修改同步worker、密码或端口。
- 后续修改首先写入此目录；旧Codex工作区通过受控镜像保留兼容副本，冲突时停止，不覆盖用户另外改动。
- 不上传密码、数据库、健康导出、镜像包、运行日志或密钥。未经另行授权不推送远端。
- 正式更新前再次确认将替换的健康项目backend和web；其他服务不变。

## Review Focus

1. UTC日期与北京时间醒来日跨午夜，睡眠小睡和实际睡眠字段回退不能改变归属（任务1、3）。
2. 相同时间戳、不同心率类型及体重设备，分页/最近N条必须有稳定主键次序，统计不能先分页再求均值（任务1）。
3. SQL里的NULL、压力0和越界值、空范围不能被转成假0或正常结果（任务1、2、3）。
4. 用户切换日期/页面/明细页后，迟到的旧响应不能覆盖新范围或控制台（任务3）。
5. 导出中途断开、代理抛错或CSV公式文本，不得泄露凭据、积压全量内容或遗留连接（任务2、4）。

## 文件职责与接口约定

新增`src/mi_fitness_mcp/storage/view_queries.py`负责白名单字段、参数化SQL、读事务、聚合和分页；不改变现有Database初始化与写入代码。新增`src/mi_fitness_mcp/services/view_query_service.py`负责八类统计口径与返回模型。现有`api.py`只接入新服务与参数验证，`web.py`只为新CSV出口增加流式代理分支，其他代理行为保留。

统一查询参数：`start_date`、`end_date`、`sample_type`、`include_naps`、`pressure_level`、`latest_only`、`limit`。`limit`留空表示全部，给定时必须正整数；筛选后按时间倒序和主键选最近N条，再统计/分页。`kind`固定为`activity/heartrate/sleep/workouts/body/spo2/stress/abnormal`。

统一结果：`{status:'ok', kind, range:{start,end}, statistics, points:[{date,values,missing}], coverage, stride, page:{number,size:10,total,rows}}`。`statistics`只含数值或null：`count, primary_sum, primary_mean, primary_min, primary_max, total_distance_m, total_active_kcal, total_calories_kcal, activity_days, mean_daily_steps, mean_daily_asleep_minutes, mean_daily_deep_minutes, nap_count, passive_mean_bpm, resting_mean_bpm, latest`；无关字段可省略，`latest`仅为规范化明细投影。`primary_*`分别使用各类主字段；睡眠单位分钟，图表值仍为小时。分页接口只返回`status/kind/range/page`，不重新执行聚合。空均值返回null。

查询范围、筛选、行投影的构建共用一个实现，列表、汇总和导出不能分别复制筛选逻辑。首屏所有聚合和明细处于同一读取事务；后续翻页使用各自短事务，排序按时间对应的真实时刻与主键，不长期阻塞同步。同步产生新记录后，重新查询可看到新数据；不承诺整个浏览会话冻结快照。

### Task 1: 后端查询与统计服务

**Files:** 新增`storage/view_queries.py`、`services/view_query_service.py`（均位于`src/mi_fitness_mcp/`）；新增`tests/test_view_queries.py`、`tests/test_view_statistics.py`、`qa/view-statistics-oracle.cjs`。

**Interfaces:** `ViewSelection(kind:str,start_date:str,end_date:str,sample_type:str|None=None,include_naps:bool=True,pressure_level:str|None=None,latest_only:bool=False,limit:int|None=None)`是不可变参数对象。`ViewRepository(db:Database,user_id:str)`提供`snapshot()`上下文（返回sqlite3.Connection）、`statistics(selection,connection)->dict`、`points(selection,connection)->list[dict]`、`page(selection,page:int,connection)->dict`、`iter_records(selection,connection)->Iterator[dict]`。`ViewQueryService(db:Database,user_id:str)`提供`get_view(selection,page:int=1)->dict`、`get_page(selection,page:int=1)->dict`、`get_overview(start_date:str,end_date:str)->dict`和`iter_export(selection)->Iterator[dict]`。

- [ ] 写失败测试：`test_selection_before_limit_and_paging`断言31条压力样本先筛26–50再取最近11条，第一页10条、第二页1条；总数11、均值来自全部11条，完整导出也是这11条。
- [ ] 写失败测试：`test_equal_timestamps_stable_order_and_owner_isolation`将相同时间的多种类型/设备记录与其他用户混入，断言连续两次查询顺序一致、分页并集恰为筛选集合且没有别人的记录。
- [ ] 写失败测试：`test_china_midnight_sleep_and_nulls`用北京时间跨日、UTC等价时刻、8小时实睡+15分钟清醒、小睡和NULL阶段数据，断言醒来日、实睡480分钟、有效日期均值正确；压力0保留，缺失日不补0。
- [ ] `qa/view-statistics-oracle.cjs`仅在测试中调用基线`HealthViews.build`，读取stdin合成记录，输出卡片原始数值、图表、参考均值。`test_all_eight_kinds_match_frontend_baseline`逐类比较后端结果与oracle，浮点容差1e-9；不把JS运行时加入产品依赖。
- [ ] 运行`python -m pytest tests/test_view_queries.py tests/test_view_statistics.py -q`，确认尚无新模块导致失败。
- [ ] 实现上述接口。表与字段用固定白名单、值参数化。时间先用用户+宽时间范围缩小候选，再以SQLite时区转换精确筛选；无时区时间戳按既有数据的UTC含义解释并在测试固定。睡眠分期在SQLite JSON函数中计算，不加载所有会话至Python列表。均值按样本sum/count，不平均日均值。长范围桶大小`ceil(days/120)`；体重每桶选最近记录，其他桶口径与oracle一致。
- [ ] `get_overview`只输出`steps,active_kcal,distance_m,resting_mean_bpm,mean_daily_asleep_minutes,mean_spo2_pct,mean_stress,activity_days,sleep_days,resting_count,spo2_count`，不含原始列表。睡眠以批准设计的实际实睡字段优先，统一旧总览只读duration字段的差异。
- [ ] 增加`test_first_view_uses_one_read_snapshot`与`test_large_input_uses_sql_paging`，断言首屏同一事务、明细只读取当前页、摘要不调用原始样本全量查询方法。运行本任务测试通过后，只暂存相关文件，保存本地提交。

### Task 2: 只读API、CSV与代理

**Files:** 修改`src/mi_fitness_mcp/api.py`、`web.py`；新增`tests/test_view_api.py`、`tests/test_view_export.py`、`tests/test_web_streaming.py`。

**Consumes:** 任务1的`ViewSelection`、`ViewQueryService`。
**Produces:** `GET /api/views/{kind}`、`GET /api/views/{kind}/records`、`GET /api/views/{kind}/export`、`GET /api/overview`；既有接口及响应不变。

- [ ] 写失败测试：`test_view_auth_validation_and_legacy_compatibility`断言未授权访问被拒绝、已授权可查；非法kind、倒序日期、>3660天、page<=0/>1000000、limit<=0与无效压力等级被拒绝；已有`/api/heart-rate`仍返回原始列表。
- [ ] 写失败测试：`test_export_matches_filtered_set_and_escapes_formula`断言CSV恰含同一筛选集合和源字段，压力包含源level与当前等级、UTF-8 BOM和中文表头，文本`=1+1`被安全转义，导出不受当前页限制。
- [ ] 写失败测试：`test_stream_disconnect_closes_cursor_and_proxy_response`断言取消消费会关闭数据库连接与httpx响应，不先执行全量list/read；代理鉴权头不转发到浏览器响应，未授权网页导出返回401。
- [ ] 运行`python -m pytest tests/test_view_api.py tests/test_view_export.py tests/test_web_streaming.py -q`，确认新接口缺失导致失败。
- [ ] 路由中通过既有`_resolve_context`取得db/user，沿用现有授权，不额外发放Key。导出使用FastAPI StreamingResponse，连接生命周期在迭代器内，游标分批读取。仅新导出路径使用Flask流式代理和httpx流式响应，正常结束/异常/断开均在finally关闭；其他代理路径不改。
- [ ] 运行本任务测试及`tests/test_web.py`，通过后保存本地提交。异常响应沿用现有错误样式，不把失败当空数据。

### Task 3: 前端只消费摘要与当前页

**Files:** 修改`web_assets/static/js/health-views.js`、`health-ui.js`、`app.js`及`templates/index.html`（位于`src/mi_fitness_mcp/`）；新增`qa/health-server-summary.test.cjs`、`qa/health-server-pagination.test.cjs`；修改受影响的`qa/dashboard.test.cjs`、`qa/dashboard-performance.test.cjs`、`qa/health-interaction.test.cjs`。

**Consumes:** 任务2的只读接口。
**Produces:** `HealthViews.fromSummary(kind,payload,range)->model`、现有`loadHealthView`/`healthPage`/`exportHealthRecords`改用新接口；`loadOverview`只调用一次`/api/overview`。

- [ ] 写失败测试：`test_server_summary_drives_cards_without_raw_records`传入30个图表点和10条明细但总数90000，断言卡片和参考均值严格使用服务端statistics，不使用10条明细重算。
- [ ] 写失败测试：`test_pagination_fetches_only_page_and_preserves_chart`断言翻页调用records端点、仅替换表格；CSV下载由导出URL完成，没有在JS拼接全量数组。
- [ ] 写失败测试：`test_late_page_and_overview_responses_do_not_overwrite_new_range`覆盖翻页中换日期、换类型及日历晚到；旧响应不能覆盖新表格、图表、控制台。`test_empty_and_failure_remain_distinct`保留空与失败的区别。
- [ ] 运行`node --test qa/health-server-summary.test.cjs qa/health-server-pagination.test.cjs`，确认新入口缺失失败。
- [ ] `fromSummary`沿用已有配置、格式化、渲染器，构造卡片/参考值，不调用build执行样本聚合。表格取payload.page.rows，总数取page.total；CSV改为原生浏览器同源附件下载。固定参考值、纵轴下限40/80/40及双色日期横线不变。旧build保留为对照和兼容辅助，不走新的页面请求链。
- [ ] 修改总览为单个紧凑接口，保留取消/过期请求保护；新静态资源版本升级。运行新增前端测试和受影响的原有前端测试，通过后保存本地提交。

### Task 4: 本机整体验证、可部署包与兼容同步

**Files:** 新增`qa/serve_query_fixture.py`、`qa/benchmark_server_queries.py`、`qa/verify_server_queries_browser.cjs`；新增`deploy/query-summary/Dockerfile`、`compose.override.yml`、`update-health.sh`、`check-ready.py`、`Update-Nas.ps1`；更新`README-NAS.md`与`docs/nas/backend-query-validation.md`。

**Consumes:** 已通过任务1–3的服务和接口。
**Produces:** 只包含backend/web替换的离线包、可核对的数据一致性与性能报告；包和截图放入忽略的artifacts目录，不提交Git。

- [ ] 本机生成30天合成数据，每天3000条心率、1000条血氧、1000条压力，另含活动/睡眠/体重/运动/异常样本。再以10倍密度比较首屏响应体积，`test_payload_does_not_scale_with_raw_samples`断言仍只含10条明细、<=120桶、无原始全量数组；记录具体字节、耗时和内存，不预先宣称倍数提升。
- [ ] 通过同一只读数据库分别调用旧查询+基线统计与新汇总，核对7天/30天各类数值和CSV集合；检查分页并集及相同时间排序。只使用本机生成的记录。
- [ ] 浏览器实际检查总览、八类健康页、7天/30天切换、翻页、导出、深浅主题、控制台、参考线和工作日标记；记录首屏节点、响应体积与加载耗时；断言没有全量原始接口请求和浏览器异常。
- [ ] 本机Linux容器验证新backend/web的联通、认证、CSV流传输、取消与挂载；保留worker旧版本。更新包的防覆盖哈希从部署前只读查询取得，脚本使用`up -d --no-deps ... backend web`，核对worker及其他健康服务未重建，并保留回退镜像与覆盖配置。不得在NAS运行合成、压力或单元测试。
- [ ] 做一次独立代码审查，修复本次引入的重大问题，仅重跑受影响验证。更新报告区分“本机已验证”与“NAS未部署”。运行`python scripts/sync_legacy_workspace.py`核对兼容副本，再核对差异保存本地提交，不推送。
- [ ] 给用户查看实际变更、测量结果与最终更新包，按规则确认仅更新健康backend和web。得到部署确认后，打开本机交互终端由用户输入sudo密码，部署就绪核对通过再报告成功。

## 自查结论

已覆盖批准设计的八类统计、总览、分页、导出、只读兼容、时区、筛选、长范围、界面保持、本机性能验证、Git与旧副本同步、NAS回退。任务1先定义统一筛选及数值协议，任务2/3依赖该协议，顺序实施可避免接口分叉；推荐当前会话原生执行，最后独立审查。此文档为实施计划，不代表接口已经实现或性能已经改善。
