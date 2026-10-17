# 离线增量镜像；发布清单另固定基础镜像digest，不联网安装依赖。
FROM local/mi-fitness-nas:20261017-audit3
USER root
COPY src/mi_fitness_mcp/ /src/src/mi_fitness_mcp/
RUN python -c "import shutil,sysconfig; shutil.copytree('/src/src/mi_fitness_mcp',sysconfig.get_paths()['purelib']+'/mi_fitness_mcp',dirs_exist_ok=True)"
USER 1000:1001
