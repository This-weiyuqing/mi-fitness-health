# 本健康项目工作约定

- 默认简体中文，UTF-8无BOM，保护无关改动。
- 主代码目录是 D:\CodeProject\mi-fitness-health，后续修改首先保存在本仓库。
- 本仓库保留上游Git历史；当前本地部署修复保存在 nas-health 分支。本地提交不包含推送授权。
- 所有合成数据、性能、浏览器和Linux容器测试只在本机执行，不在生产NAS上测试。
- 修改NAS既有容器、删除数据、改变网络暴露范围前，说明具体内容并取得用户确认。
- 不读取或提交真实密码、Token、私钥、健康数据库、原始归档、健康导出或.env。
- 后续产品代码改动完成后执行 python scripts/sync_legacy_workspace.py，更新旧Codex工作区的兼容副本。脚本如报冲突，停止并核对，不覆盖用户另外的改动。
- 迁移后的有效测试在 tests/ 和 qa/；maintenance/legacy-tests/是留存的旧环境测试脚本，路径尚未迁移，不作为当前验收入口。
