#!/usr/bin/env bash
# Émoi HTTPS on existing XLC gateway, with backup and rollback. Never restarts other services.
set -Eeuo pipefail
CADDYFILE=/home/ubuntu/xlc-cloud/gateway/Caddyfile
GATEWAY=xlc-gateway-gateway-1
EMOI=emoi-emoi-1
fail() { printf 'EMOI_HTTPS=FAILED\n原因：%s\n' "$1"; exit 1; }

[[ -f "$CADDYFILE" ]] || fail "找不到现有 Caddyfile。"
sudo docker inspect "$GATEWAY" >/dev/null 2>&1 || fail "现有 XLC 网关容器未找到。"
sudo docker inspect "$EMOI" >/dev/null 2>&1 || fail "Émoi 容器未找到。"
for name in "$GATEWAY" "$EMOI"; do
  sudo docker inspect --format '{{json .NetworkSettings.Networks}}' "$name" |
    grep -q '"xlc-gateway_default"' ||
    fail "$name 未在 xlc-gateway_default 网络内。"
done
curl -fsS --max-time 6 http://127.0.0.1:8088/readyz | grep -q '"ok":true' ||
  fail "Émoi 本机健康检查未通过。"

OLD_HOST="$(sudo grep -oE 'xlc-[0-9]{1,3}(-[0-9]{1,3}){3}\.sslip\.io' "$CADDYFILE" | head -n 1 || true)"
[[ -n "$OLD_HOST" ]] || fail "未找到现有的 XLC sslip.io 地址。"
HOST="$(printf '%s' "$OLD_HOST" | sed 's/^xlc-/emoi-/')"
[[ "$HOST" =~ ^emoi-[0-9]{1,3}(-[0-9]{1,3}){3}\.sslip\.io$ ]] ||
  fail "新地址校验失败。"
echo "Émoi 地址：https://$HOST/"

if sudo grep -Fq "$HOST {" "$CADDYFILE"; then
  echo "检测到现有同名路由，未重复写入。"
else
  BACKUP="$CADDYFILE.before-emoi-$(date +%Y%m%d-%H%M%S).bak"
  sudo cp -p "$CADDYFILE" "$BACKUP" || fail "备份 Caddyfile 失败。"
  printf '\n# Émoi private chat frontend\n%s {\n    reverse_proxy emoi-chat:8080\n}\n' "$HOST" |
    sudo tee -a "$CADDYFILE" >/dev/null || fail "Caddyfile 写入失败。"
  echo "CADDY_BACKUP=$BACKUP"
  if ! sudo docker exec "$GATEWAY" caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null; then
    sudo cp -p "$BACKUP" "$CADDYFILE"
    fail "Caddy 语法检查失败，已恢复旧配置。"
  fi
  if ! sudo docker exec "$GATEWAY" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile; then
    sudo cp -p "$BACKUP" "$CADDYFILE"
    fail "热加载失败，已恢复旧配置；网关未重启。"
  fi
  echo "CADDY_RELOAD=OK"
fi

ok=0
for attempt in 1 2 3 4 5 6; do
  status="$(curl --noproxy '*' --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --max-time 12 --resolve "$HOST:443:127.0.0.1" "https://$HOST/readyz" 2>/dev/null || true)"
  if [[ "$status" == 200 ]]; then ok=1; break; fi
  echo "HTTPS 验证中（第 $attempt 次，状态 $status）"
  sleep 4
done
if [[ "$ok" -eq 1 ]]; then
  echo "EMOI_HTTPS=OK"
  echo "EMOI_URL=https://$HOST/"
else
  echo "EMOI_HTTPS=PENDING"
  echo "EMOI_URL_CANDIDATE=https://$HOST/"
  echo "路由已尝试添加，但证书或网络尚未通过检查；不要重装。"
fi
