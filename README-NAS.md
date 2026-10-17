# NAS健康同步项目

本目录是项目主代码目录。上游介绍保留在README.md，本项目部署与维护说明以本文件及docs/nas为准。

## 当前版本

2026-10-17：backend/worker为20261017-audit3，web为20261017-ui7；UI7已成功部署。包含小米中国区云同步、SQLite长期保存与原始归档、备份恢复、密码鉴权、八类健康查询、紧凑参考线、纵轴下限和工作日/非工作日标记。ChatGPT隧道仍未启用。

后端汇总与分页优化已在本机以合成数据完成集成验证，离线候选镜像为 `20261017-summary8`；NAS仍为上述audit3/ui7，尚未部署。八类查询的统计、最多120个图表桶与每页10条明细由后端返回，CSV按流传输。

## 目录

- src/mi_fitness_mcp：当前全部产品代码（包含前后端）。
- tests：上游及已修改的模块测试；qa：当前网页统计、交互与日历回归测试。
- deploy/runtime.py：归档、加密凭据与同步worker运行支持；deploy/readonly.py：未启用的只读MCP支持。
- deploy/compose.yml、deploy/compose.override.yml：部署配置源文件，无密码。
- maintenance/legacy-tests：旧验证脚本源码，仅作历史留存。
- docs/nas：当前版本、代码迁移与后端优化设计。
- scripts/sync_legacy_workspace.py：把本仓库产品代码同步回旧工作区，逐文件检测冲突。

## 本机验证

沿用pyproject.toml中的Python依赖，建议uv创建独立开发环境。已有环境可执行 `python -m pytest tests/test_web.py -q` 和 `python qa/test_workday_calendar.py`；前端使用 `node --test qa/*.test.cjs`。测试只使用临时或合成数据。

此仓库不包含.env、密钥环、数据库、真实健康记录、镜像包和第三方依赖缓存；不向Git提交这些内容。上游历史保持，远程upstream只作来源，未创建或推送任何网络仓库。

汇总优化的合成数据、旧查询对照和独立Edge验收入口为 `qa/serve_query_fixture.py`、`qa/benchmark_server_queries.py`、`qa/verify_server_queries_browser.cjs`。全部数据库、浏览器profile、截图、日志和离线包仅放忽略的 `artifacts/query-summary/`。实际测量、限制与复现步骤见 [后端查询验证报告](docs/nas/backend-query-validation.md)。

## summary8候选更新包

`deploy/query-summary/`包含离线增量Dockerfile、仅替换backend/web镜像的覆盖配置、哈希防覆盖和回退脚本。基础镜像audit3必须在本机已有，构建不安装依赖；worker继续audit3。发布包为本机 `artifacts/query-summary/release/`，不提交Git。

已有镜像tar时，`python deploy/query-summary/prepare-release.py`仅重建发布脚本、UTF-8无BOM/LF元数据及manifest，不构建或修改镜像tar。shell读取镜像身份时兼容旧CRLF，并严格校验`sha256:<64位小写十六进制>`。

正式更新前须明确确认仅替换健康项目backend和web。确认后由用户在交互PowerShell运行 `deploy/query-summary/Update-Nas.ps1 -Package artifacts/query-summary/release -Deploy` 并在终端输入sudo密码；不加 `-Deploy` 只校验本地发布包。脚本沿用原端口、密码来源和数据/日历挂载，不处理其他NAS服务。就绪检查只检查资源、代理、鉴权、日历和OpenAPI路由元数据，不发健康查询/导出请求，不运行合成或负向参数测试。

## 后续维护

首先修改本目录并按影响运行本机测试，再执行兼容副本同步并核对Git差异。NAS部署需使用已验证的版本和明确批准的容器范围。现有旧版增量Dockerfile依赖本机基础镜像；完整可复现构建将在后端优化实施时统一整理，不能把旧覆盖镜像文件当成从零构建方案。
