# 项目目录整理

用户批准将三个容器的专属文件与共享状态分别存放，历史安装文件归档至项目目录。

```text
mi-fitness-health/
├── compose.yml
├── compose.override.yml
├── .env
├── web/calendar/
├── backend/secrets/
├── worker/
├── shared/state/
└── archive/
    ├── initial-install/
    ├── ui4/
    ├── ui5/
    ├── ui6/
    ├── ui7/
    ├── password-change/
    ├── rollback-configs/
    └── directory-migration/
```

`worker` 目前没有独立的持久化文件，使用 `shared/state`。backend 与 worker 的容器内路径仍是 `/state`；web 的缓存路径仍是 `/calendar`。凭据文件在容器内仍为只读。尚未启用的 readonly 服务挂载路径一并更新，但不启动该服务。

迁移工具：`deploy/directory-migration/migrate.py`。执行前验证旧配置 SHA256、三个容器的版本、其他容器引用和同文件系统。停止本项目三个服务后，对各文件树内容、属主和权限做快照，原地 rename，再核对内容与权限，修改三处宿主挂载路径。镜像、环境变量、端口、重启策略不得变化。失败时停止本项目容器，恢复原路径和配置，再启动原服务。

原 Compose 文件和迁移结果保存在 NAS 的 `archive/directory-migration/`；历史回退配置在 `archive/rollback-configs/` 中。历史脚本和配置仅归档留存，其中的旧路径不再适用，不应直接执行。

本机合成演练入口：`deploy/directory-migration/test_migrate.py`，覆盖成功迁移、就绪失败回退、其他容器引用阻止及配置变化阻止。NAS 只进行实际迁移与部署就绪核对，不运行合成测试或健康查询测试。

已获用户明确授权后，使用 PowerShell 7 执行 `deploy/directory-migration/Invoke-Migration.ps1 -Run`。sudo 密码仅在本机交互窗口输入，不写入脚本或聊天。

迁移已于 2026-10-17 17:02（北京时间）完成，终端返回 0。NAS 实际记录为 `archive/directory-migration-retry-1792227666562967051/result.json`，共核对并移动 21 个文件/目录树，三个健康容器及实际网页探针通过，外部旧临时目录已全部移入项目。核对包含文件哈希、权限和属主；未复制或拆分健康数据库。

`verification.json` 确认三个容器镜像与环境变量值均未改变，其中 backend/web 仅环境变量排列顺序变化，worker 顺序亦未改变。端口、挂载和重启策略核对通过，未操作其他项目容器。原安装包、维护脚本和回退配置全部保留，无数据删除。

实际生效配置 SHA256：

- `compose.yml`：`b5c965c653948e97e02e22774bd15253dbde74d5e25616fa0115f047a36556dd`
- `compose.override.yml`：`d77485b3d3177def55c200478ba9e4645689f8476f46c13a47487be22edcd1c1`

迁移工具只接受原始旧目录与配置，不可对已完成迁移的项目重复执行。后续更新需从新的本地部署源生成发布包；现有旧离线发布包和 archive 内旧脚本不适用于新目录。

首次迁移的文件校验和容器重建通过，但验收未通过，已自动回退；原配置 SHA256 与迁移前一致。NAS 事件表明 web/worker 启动约一秒后即触发回退，原脚本未保存子进程 stderr，因此无法还原该次具体异常。检查发现运行状态检查没有等待 web HTTP 服务，已增加最多 90 秒的真实网页探针重试。失败阶段和脱敏 stderr 保存在每次迁移记录目录的 `errors.log`；历史回退记录保留，重试另建记录目录。

本机 Windows 与 Linux 的六项针对性用例通过。独立合成项目的三个真实容器已完成停止、移动、重建，以及静态资源、鉴权、代理、OpenAPI 和日历探针验证；演练容器已移除，未访问真实健康数据。

第二次尝试在 `verify-services` 的镜像/环境变量合并检查处失败并回退。发现原检查直接比较 `Config.Env` 列表，会把仅顺序不同误判为变量值改变。已将镜像和环境检查分开，环境按唯一名称比较完整值；重复名称仍拒绝。本机 Windows/Linux 八项针对性用例通过，真实值变化仍会回退。`verification.json` 只记录容器名称、是否同镜像、变量值是否一致、顺序是否改变和变化的变量名，不记录变量值。

## 已授权的历史归档清理

2026-10-17 18:55（北京时间）完成。用户要求清理无用历史文件后，删除 initial-install、password-change、rollback-configs、ui4/5/6/7 及两次已回退迁移记录，共 9 个目录、74 个文件、678263713 字节（约 647 MiB）。删除前确认没有容器绑定这些归档路径；删除后确认三个健康容器的 ID、启动时间与运行状态未变，Compose 配置校验值未变，运行数据目录全部存在。

`archive` 当前仅保留 `directory-migration-retry-1792227666562967051/`，包含成功迁移记录、原配置、当前生效 Compose 配置备份和清理记录 `cleanup-result.json`。前文目录树及迁移过程中的“全部保留”描述为清理前状态。健康数据库、凭据、日历及其运行目录未删除；未清理 Docker 镜像或操作其他项目。

清理工具位于 `deploy/directory-migration/cleanup_history.py`，只接受该次固定清单；清理完成后不应重复执行。
