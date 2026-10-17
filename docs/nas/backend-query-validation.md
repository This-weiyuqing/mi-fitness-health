# 后端汇总与分页：本机验证记录

日期：2026-10-17。候选镜像 `local/mi-fitness-nas:20261017-summary8`。本报告全部结果来自本机生成的SQLite和独立浏览器/Linux容器，**NAS未部署，没有NAS性能实测**。没有读取真实凭据、健康库、原始归档或导出。

## 数据与统计一致性

合成范围2026-09-18至2026-10-17，共30天。1x每天3000条心率、1000条血氧、1000条压力；另有每日两设备活动/体重、夜间睡眠与小睡、两条运动/异常样本。10x仅增加三个高频类别密度，分别90万/30万/30万条，不改变日期范围。

同一个只读SQLite通过旧QueryService+冻结前端oracle和新ViewQueryService核对7/30天的八类卡片、图表点、覆盖天数；完整CSV的共有业务字段集合与旧查询相同。每类另对带limit=31的完整筛选结果核对分页并集、唯一id和重复读取次序；相同时间的体重设备、运动和异常记录均覆盖。没有用大库的数千次OFFSET翻页冒充现实浏览过程。

同刻多设备体重是明确的规格差异：旧接口没有主键次序，冻结oracle最后一天取72.9kg；新接口按真实时间及id倒序取72.91kg。旧oracle及其输入不改，新的latest/每日点单独按稳定主键规则断言；记录集合和均值不变。睡眠CSV的小睡值True/False按布尔语义与旧库0/1核对，原CSV字节不改。

## 实测体积、耗时与内存

JSON均按UTF-8紧凑编码计字节。耗时是一次本机服务调用，不含浏览器渲染和网络；两条路径都启用tracemalloc。内存为Python分配峰值，**不包含SQLite原生内存、进程RSS或浏览器内存**。旧全量响应只在本机测量，未交给浏览器渲染。

|密度/类型|记录数|旧JSON字节|新首屏字节|旧/新秒|旧/新Python峰值字节|
|---|---:|---:|---:|---:|---:|
|1x心率|90,000|7,255,988|3,470|0.9609 / 0.8096|106,300,937 / 33,031|
|1x血氧|30,000|1,851,368|2,863|0.2890 / 0.2311|33,815,314 / 30,301|
|1x压力|30,000|2,775,578|3,162|0.3056 / 0.2509|35,601,460 / 31,109|
|10x心率|900,000|73,569,039|3,570|9.6272 / 8.3072|1,062,972,329 / 32,869|
|10x血氧|300,000|18,849,369|2,911|3.0202 / 2.5436|336,293,170 / 30,147|
|10x压力|300,000|28,092,399|3,239|3.2429 / 2.6703|356,123,564 / 30,963|

六个新首屏均只有10条明细和30个图表桶，没有原始全量数组。密度10倍时首屏只增加100/48/77字节；`test_payload_does_not_scale_with_raw_samples`断言响应低于1.25倍并验证固定明细/桶数。SQL仍须扫描所选记录；本机90万心率的新汇总需要8.3072秒，不能据此宣称NAS查询会瞬时完成。

## 真实浏览器与Linux容器

独立无头Edge profile实际访问总览和八页，7/30天共16视图；每次首屏恰一条views请求，翻页只取records且保留图表。完整数据模式下首屏JSON为1571–6599字节，整个文档节点812–3093（包括已打开但隐藏的页面）。本机30天首屏心率约0.8秒、血氧/压力约0.25秒；具体每页耗时在忽略目录的browser/report.json，属于本机单次观测。

心率参考线、40bpm纵轴下限、工作日橙色/非工作日绿色已在真实SVG断言；深浅主题和1440px/390px截图已检查。窄屏沿用已有布局，头部控件较拥挤，本任务没有改样式。控制台、失败空态和日期/页面取消均覆盖；最终完整验收0个页面异常、0条旧全量接口请求。迟到/筛选/翻页竞态另由现有Node测试覆盖。

手填Key、扫码state Key、仅server Key、server Key优先于不同浏览器Key四种身份的原生附件均保存31条，1403字节且内容逐字节相同；POST表单立即清除，Key不在URL，没有CSV fetch或Blob缓冲。server-only是原生新标签GET附件，由Browser下载事件观测，容器HTTP再独立确认GET。QA最初用请求头模拟Basic，原生新标签GET未带该头而401；改成真实Basic挑战缓存后四模式通过，产品未改。

首轮浏览器只保存到一条text为Uncaught的异常，缺少stack，无法定位或宣称修复。随后增强exceptionDetails并完成两轮验收，未复现；原失败摘要仍保留在artifacts，后续若再出现须收集完整stack继续定位。

本机Linux两个独立容器使用summary8安装包代码，通过内部网络互通，无宿主机端口，CPU各0.5、内存512/256MiB、根文件系统只读；仅挂载QA脚本和合成库（只读）。GET/POST导出均200/chunked、31条1403字节；8次读首块后关闭，再次查询成功。匿名web为401，无默认上下文backend为503，错误Key为401，另一合成用户查询0条，外源Origin为403。取消后backend文件描述符8、RSS约68MiB；资源释放的精确路径由streaming专项测试覆盖，不把单次RSS当内存泄漏证明。audit3与summary8的 `/opt/health/runtime.py` SHA256同为 `1ac5a53cdbd59376a07a0021c145e55ce03e36e6890278291bed9298e03a54a5`。

相关Python验证85项通过（1条Starlette/httpx既有弃用警告），全部Node验证53项通过。部署shell和PowerShell语法通过；用虚构环境渲染前后Compose逐字段比较，恰只有backend/web镜像变化，worker、端口、环境和挂载一致。

## 复现与离线交付

在主仓库使用现有Python依赖环境并设置 `PYTHONPATH=src`。下列命令只处理本仓库artifacts中的合成数据，不得替换成真实库路径：

```powershell
python qa/benchmark_server_queries.py
python qa/serve_query_fixture.py backend --port 18431
python qa/serve_query_fixture.py web --port 18432
python qa/serve_query_fixture.py web --port 18433 --server-key
node qa/verify_server_queries_browser.cjs
python -m pytest tests/test_view_queries.py tests/test_view_statistics.py tests/test_view_api.py tests/test_view_export.py tests/test_web_streaming.py tests/test_web.py -q
node --test qa/*.test.cjs
```

三个fixture各在独立本机终端启动；自动启动时必须隐藏窗口。浏览器脚本自行创建独立Edge profile并退出。密度库已存在时benchmark复用它；重新生成时使用新的artifacts输出目录，generate拒绝覆盖现有库。

离线构建使用 `deploy/query-summary/Dockerfile`，上下文只复制当前 `src/mi_fitness_mcp/` 源码（排除pycache），不把仓库运行文件送入构建。基础镜像须核对为audit3 `sha256:f4cbe187a98e3d3223e28e79b6edd115446ba62a78931f54f3bb0a6991a9395d`，构建选 `--network none --pull=false`；同时覆盖源码目录与installed purelib，保持audit3运行入口，无联网安装。

本机离线发布目录为 `artifacts/query-summary/release/`：镜像tar、image-id及同包配置digest、基础镜像id、覆盖配置、就绪/更新脚本、预期当前配置哈希及manifest.sha256。Docker引擎身份核对只接受本包确切的索引/配置digest，先校验整个tar；NAS引擎尚未实际导入验证。摘要和镜像包不提交Git。`Update-Nas.ps1`不带Deploy仅校验；正式执行必须先取得仅更新backend/web的明确确认，由用户交互输入sudo密码。更新脚本核对manifest和现有覆盖配置SHA256、保留旧覆盖与镜像、不变更.env，使用 `up -d --no-deps --no-build --pull never backend web`，比较其余健康服务容器id/镜像。失败恢复旧覆盖并尝试回退这两个服务。

当前NAS覆盖配置防覆盖哈希由controller在部署前只读取得：`3cdbdc882b169f5785d6d1c3c46ceb159e209c567d6e28ceb31b15d4280fcdd8`。实际正式更新时脚本再次验证；若有漂移即停止。此记录不是部署确认。NAS就绪脚本只访问资源/代理状态、匿名认证、日历和无效日期路由，不进行健康导出、合成/压力测试。
