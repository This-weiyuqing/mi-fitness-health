#!/bin/sh
set -eu
umask 077
[ "$(id -u)" = 0 ] || { echo '请通过 sudo 执行。'; exit 1; }
package=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
target=/vol2/1000/Soft/mi-fitness-health
cd "$package"
sha256sum -c health-ui7.tar.sha256
python3 - "$target/compose.override.yml" "$package/expected-current.sha256" <<'PY'
import hashlib,sys
from pathlib import Path
assert hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()==Path(sys.argv[2]).read_text().strip(), '现有配置已变化，停止避免覆盖'
PY
before=$(docker inspect --format '{{.Id}}' mi-fitness-health-backend-1 mi-fitness-health-worker-1)
[ ! -L "$target/calendar" ] || { echo "日历目录不能是符号链接"; exit 1; }
mkdir -p "$target/calendar"
chown 1000:1001 "$target/calendar"
chmod 700 "$target/calendar"
docker load -i "$package/health-ui7.tar"
cd "$target"
docker compose --project-name mi-fitness-health --env-file .env -f compose.yml -f "$package/compose.override.yml" config --quiet
old="$target/compose.override.pre-ui7-$(date +%Y%m%d-%H%M%S).yml"
cp compose.override.yml "$old"
complete=0
recover() {
  if [ "$complete" = 0 ]; then
    cp "$old" "$target/compose.override.yml"
    chown 1000:1001 "$target/compose.override.yml"
    chmod 600 "$target/compose.override.yml"
    docker compose --project-name mi-fitness-health up -d --no-deps --no-build --pull never web || true
    echo '新版未通过验证，已恢复原网页配置并尝试回退。'
  fi
}
trap recover EXIT
cp "$package/compose.override.yml" compose.override.yml
chown 1000:1001 compose.override.yml
chmod 600 compose.override.yml
docker compose --project-name mi-fitness-health up -d --no-deps --no-build --pull never --wait --wait-timeout 60 web
python3 "$package/check-web.py"
after=$(docker inspect --format '{{.Id}}' mi-fitness-health-backend-1 mi-fitness-health-worker-1)
[ "$before" = "$after" ] || { echo '后端或同步容器标识发生变化，停止验收。'; exit 1; }
complete=1
trap - EXIT
printf '\n网页更新完成。后端和 worker 未重建，登录密码及数据目录未修改。\n'
