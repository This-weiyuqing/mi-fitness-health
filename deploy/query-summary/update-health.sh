#!/bin/sh
set -eu
umask 077
[ "$(id -u)" = 0 ] || { echo '请通过sudo在交互终端执行。'; exit 1; }
package=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
target=/vol2/1000/Soft/mi-fitness-health
cd "$package"
sha256sum -c manifest.sha256
python3 - "$target/compose.override.yml" "$package/expected-current.sha256" <<'PY'
import hashlib,sys
from pathlib import Path
assert hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()==Path(sys.argv[2]).read_text().strip(), '现有覆盖配置已变化，停止避免覆盖'
PY
[ -d "$target/calendar" ] && [ ! -L "$target/calendar" ] || { echo '日历挂载目录缺失或异常，停止。'; exit 1; }
cd "$target"
compose() { docker compose --project-name mi-fitness-health --env-file .env -f compose.yml -f compose.override.yml "$@"; }
snapshot() { docker ps -aq --filter label=com.docker.compose.project=mi-fitness-health | sort | while read -r id; do docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}} {{.Id}} {{.Image}}' "$id"; done | grep -v -E '^(backend|web) ' | sort; }
before=$(snapshot)
[ "$(docker inspect --format '{{.Config.Image}}' mi-fitness-health-worker-1)" = local/mi-fitness-nas:20261017-audit3 ] || { echo 'worker版本已变化，停止。'; exit 1; }
backup="$target/compose.override.pre-summary8-$(date +%Y%m%d-%H%M%S).yml"
cp compose.override.yml "$backup"
docker inspect --format '{{.Config.Image}} {{.Image}}' mi-fitness-health-backend-1 mi-fitness-health-web-1 > "$backup.images"
# 不清理旧镜像；覆盖配置和镜像ID均保留以便回退。
docker load -i "$package/health-summary8.tar"
expected=$(cat "$package/image-id.txt")
config_id=$(cat "$package/image-config-id.txt")
actual=$(docker image inspect --format '{{.Id}}' local/mi-fitness-nas:20261017-summary8)
[ "$actual" = "$expected" ] || [ "$actual" = "$config_id" ] || { echo '导入镜像ID不符。'; exit 1; }
docker compose --project-name mi-fitness-health --env-file .env -f compose.yml -f "$package/compose.override.yml" config --quiet
complete=0
recover() {
  if [ "$complete" = 0 ]; then
    cp "$backup" "$target/compose.override.yml"
    chown 1000:1001 "$target/compose.override.yml"
    chmod 600 "$target/compose.override.yml"
    compose up -d --no-deps --no-build --pull never backend web || true
    echo "更新未通过，已恢复原配置并尝试回退backend/web。备份：$backup"
  fi
}
trap recover EXIT
cp "$package/compose.override.yml" compose.override.yml
chown 1000:1001 compose.override.yml
chmod 600 compose.override.yml
compose up -d --no-deps --no-build --pull never --wait --wait-timeout 90 backend web
python3 "$package/check-ready.py" "$expected" "$config_id"
[ "$before" = "$(snapshot)" ] || { echo 'worker或其他健康服务发生变化，停止验收。'; exit 1; }
complete=1
trap - EXIT
printf '\nbackend/web更新完成；worker及其他健康服务未重建，原覆盖配置和旧镜像已保留。\n'
