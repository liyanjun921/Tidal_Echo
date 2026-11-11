#!/usr/bin/env bash
# Staging-only Émoi small-phone preview for existing Tencent XLC Gateway.
# Never checks out the live Émoi Git tree or touches emoi_emoi_data.
# Separate project emoi-phone-preview, local TCP 8089, volume, HTTPS hostname.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIVE=/home/ubuntu/emoi-web
CADDYFILE=/home/ubuntu/xlc-cloud/gateway/Caddyfile
GATEWAY=xlc-gateway-gateway-1
PREVIEW_PROJECT=emoi-phone-preview
PREVIEW_PORT=8089
cd "$ROOT"

fail(){ printf '\nPHONE_PREVIEW=FAILED\n原因：%s\n' "$1" >&2; exit 1; }
echo 'Émoi · 小手机独立体验版'

[[ "$(readlink -f "$ROOT")" != "$(readlink -f "$LIVE")" ]] ||
  fail '当前目录是正式 Émoi，拒绝在正式目录部署预览。'
[[ -f "$LIVE/.env" && -f "$LIVE/compose.emoi.yaml" ]] ||
  fail '未找到原来正常运行的 Émoi 安装目录 /home/ubuntu/emoi-web。'
[[ -f "$CADDYFILE" ]] || fail '没有找到已有的 XLC Caddy 配置。'
[[ -f compose.emoi.yaml && -f compose.emoi.light.yaml &&
   -f compose.emoi.preview.yaml && -f web/emoi-phone.js ]] ||
   fail '预览仓库不完整，请确认使用了 design/emoi-dual-mode-phone-v1 分支。'

for command in sudo docker git python3 curl ss; do
  command -v "$command" >/dev/null 2>&1 || fail "缺少命令：$command"
done
sudo docker compose version >/dev/null 2>&1 || fail 'Docker Compose 不可用。'
sudo docker network inspect xlc-gateway_default >/dev/null 2>&1 ||
  fail '现有网关 Docker 网络不可用。'
sudo docker inspect "$GATEWAY" >/dev/null 2>&1 || fail 'XLC HTTPS 网关未运行。'
sudo docker inspect emoi-emoi-1 >/dev/null 2>&1 || fail '正式 Émoi 未运行，停止以防扩大问题。'
curl --noproxy '*' -fsS --max-time 7 http://127.0.0.1:8088/readyz >/dev/null ||
  fail '正式 Émoi 当前未通过健康检查，暂不新增体验服务。'

free_kb="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
available_kb="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
[[ "$free_kb" -ge 3145728 ]] || fail '硬盘可用空间不足 3 GiB。'
[[ "$available_kb" -ge 655360 ]] || fail '可用内存不足 640 MiB，先保住原服务。'

if ss -H -ltn "sport = :$PREVIEW_PORT" | grep -q .; then
  if ! sudo docker ps --filter "label=com.docker.compose.project=$PREVIEW_PROJECT" \
    --filter 'label=com.docker.compose.service=emoi' --format '{{.ID}}' | grep -q .; then
    fail '8089 已被其他程序占用；没有更改原有端口。'
  fi
fi

# Reuse the existing private relay secret for convenience, but never print it.
# Preview has its OWN SQLite/volume; no live data is shared.
if [[ ! -f .env ]]; then
  umask 077
  cp "$LIVE/.env" "$ROOT/.env" || fail '无法创建仅供体验版使用的私人环境文件。'
fi
python3 - <<'PY'
from pathlib import Path
import os
p=Path(".env")
rows=p.read_text(encoding="utf-8").splitlines()
secret=[line.split("=",1)[1].strip().strip("'\"") for line in rows
        if line.startswith("RELAY_SECRET=")]
if len(secret)!=1 or len(secret[0]) < 32:
    raise SystemExit("缺少有效的 RELAY_SECRET：没有改动云端服务。")
rows=[line for line in rows if not line.startswith("EMOI_PORT=")]
rows.append("EMOI_PORT=8089")
p.write_text("\n".join(rows)+"\n",encoding="utf-8")
os.chmod(p,0o600)
print("PRIVATE_ENV=READY（沿用私人密钥；不显示密钥）")
PY

compose(){
  sudo docker compose -p "$PREVIEW_PROJECT" \
    -f compose.emoi.yaml -f compose.emoi.light.yaml \
    -f compose.emoi.preview.yaml "$@"
}

echo '预览单独构建：不更新或重启正式 emoi-emoi-1。'
compose config --quiet || fail '预览容器配置未通过检查。'
compose up -d --build emoi || fail '体验容器构建或启动失败；正式容器不受影响。'

ready=0
for attempt in $(seq 1 45); do
  status="$(curl --noproxy '*' --silent --output /dev/null \
    --write-out '%{http_code}' --max-time 4 \
    "http://127.0.0.1:$PREVIEW_PORT/readyz" || true)"
  if [[ "$status" == 200 ]]; then ready=1; break; fi
  sleep 3
done
if [[ "$ready" -ne 1 ]]; then
  echo '预览容器尚未通过健康检查（正式服务未动）。'
  compose ps
  fail '本地 /readyz 不是 200；不要修改 Caddy 路由。'
fi
echo 'PHONE_PREVIEW_LOCAL=OK'
echo 'PHONE_PREVIEW_DATA=ISOLATED'

old_host="$(sudo grep -oE 'xlc-[0-9]{1,3}(-[0-9]{1,3}){3}\.sslip\.io' "$CADDYFILE" | head -n1 || true)"
[[ -n "$old_host" ]] || fail '没找到旧 XLC sslip.io 域名，无法确定新地址。'
host="$(printf '%s' "$old_host" | sed 's/^xlc-/emoi-test-/')"
[[ "$host" =~ ^emoi-test-[0-9]{1,3}(-[0-9]{1,3}){3}\.sslip\.io$ ]] ||
  fail '解析出不合法的体验版域名。'

# Prevent silently attaching an existing unrelated route.
if sudo grep -Fqx "$host {" "$CADDYFILE"; then
  if ! sudo grep -Fq 'reverse_proxy emoi-phone-preview:8080' "$CADDYFILE"; then
    fail '发现同名 HTTPS 地址，但它不是本脚本的路由；未改动网关。'
  fi
  echo 'CADDY_PREVIEW_ROUTE=EXISTS'
elif sudo grep -Fq "$host" "$CADDYFILE"; then
  fail 'HTTPS 配置出现相似的预览域名，停止避免重复。'
else
  backup="$CADDYFILE.before-phone-preview-$(date +%Y%m%d-%H%M%S).bak"
  sudo cp -p "$CADDYFILE" "$backup" || fail '网关原配置备份失败。'
  printf '\n# Émoi phone preview: separate project, separate data volume\n%s {\n    reverse_proxy emoi-phone-preview:8080\n}\n' "$host" |
    sudo tee -a "$CADDYFILE" >/dev/null ||
    { sudo cp -p "$backup" "$CADDYFILE"; fail '写入 HTTPS 路由失败，已还原文件。'; }
  if ! sudo docker exec "$GATEWAY" caddy adapt \
    --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
    sudo cp -p "$backup" "$CADDYFILE"
    fail '网关配置语法检测失败，已还原原文件。'
  fi
  if ! sudo docker exec "$GATEWAY" caddy reload \
    --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null; then
    sudo cp -p "$backup" "$CADDYFILE"
    sudo docker exec "$GATEWAY" caddy reload \
      --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 || true
    fail '网关热加载失败，已尝试恢复旧配置。'
  fi
  echo 'CADDY_PREVIEW_ROUTE=ADDED'
fi

# Verify TLS at the actual Caddy SNI, never use -k to hide cert failures.
https_ok=0
for attempt in $(seq 1 8); do
  code="$(curl --noproxy '*' --silent --output /dev/null \
    --write-out '%{http_code}' --max-time 14 \
    --resolve "$host:443:127.0.0.1" "https://$host/readyz" || true)"
  if [[ "$code" == 200 ]]; then https_ok=1; break; fi
  sleep 4
done
curl --noproxy '*' -fsS --max-time 7 http://127.0.0.1:8088/readyz >/dev/null ||
  echo '注意：正式 Émoi 健康状态出现异常，请通知我，不要重复部署。'

if [[ "$https_ok" == 1 ]]; then
  echo 'PHONE_PREVIEW_HTTPS=OK'
  echo "PHONE_PREVIEW_URL=https://$host/"
  echo '请在手机浏览器打开。正式网址及原有数据没有被替换。'
else
  echo 'PHONE_PREVIEW_HTTPS=PENDING'
  echo "PHONE_PREVIEW_CANDIDATE=https://$host/"
  echo 'HTTPS 证书或网关访问尚未通过验证；不用重装，发送本次输出即可。'
fi
