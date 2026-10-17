FROM local/mi-fitness-nas:20261017-audit3
USER root
COPY overlay/ /src/src/mi_fitness_mcp/
RUN python -c "import shutil,sysconfig; shutil.copytree('/src/src/mi_fitness_mcp',sysconfig.get_paths()['purelib']+'/mi_fitness_mcp',dirs_exist_ok=True)"
USER 1000:1001
