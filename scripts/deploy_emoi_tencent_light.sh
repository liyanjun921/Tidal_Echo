#!/usr/bin/env bash
# Émoi Tencent Lighthouse one-step starter.
# Designed for a server that already hosts XLC Gateway / CyberBoss / OB.
# Only creates/upgrades the emoi Compose project; never changes other services.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PROJECT=emoi
PORT_DEFAULT=8088
BASE=compose.emoi.yaml
LIGHT=compose.emoi.light.yaml

echo "Émoi · 腾讯云轻量启动（现有服务不会修改）"
for cmd in python3 git curl ss; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "缺少基础命令：$cmd。停止，未修改服务器。"
    exit 2
  fi
done
if ! sudo docker compose version >/dev/null 2>&1; then
  echo "当前账号无法使用 Docker Compose。停止，未修改服务器。"
  exit 2
fi
if [[ ! -f "$BASE" || ! -f "$LIGHT" ]]; then
  echo "缺少 Émoi Compose 文件，请确认已经拉取仓库 main 分支。"
  exit 2
fi

# Never replace a secret for an existing install or attach unexpectedly to an old
# named volume. Refuse unless the owner has explicitly configured its env file.
if [[ ! -f .env ]]; then
  if sudo docker volume inspect emoi_emoi_data >/dev/null 2>&1 ||
     sudo docker ps -a --filter 'label=com.docker.compose.project=emoi' --format '{{.ID}}' | grep -q .; then
    echo "检测到已存在 Émoi 容器/数据卷，但没有 .env；请勿覆盖旧凭据或数据。"
    exit 2
  fi
  if ss -H -ltn "sport = :$PORT_DEFAULT" | grep -q .; then
    echo "8088 已被占用；停止，未创建 Émoi。"
    exit 2
  fi
  # Generate the secret in a private file, never print or commit it.
  umask 077
  python3 - <<'PY'
from pathlib import Path
import secrets
path = Path(".env")
if path.exists():
    raise SystemExit("私人 .env 已存在，拒绝覆盖")
path.write_text("RELAY_SECRET=" + secrets.token_hex(32) + "\nEMOI_PORT=8088\n", encoding="utf-8")
path.chmod(0o600)
print("Émoi 私人密钥已生成（不会打印）")
PY
else
  echo "发现原有 .env，保留原密钥和端口。"
fi

# Parse only the two required values; never source untrusted dotenv as shell code.
PORT="$(python3 - <<'PY'
from pathlib import Path
import re
values = {}
for row in Path(".env").read_text(encoding="utf-8").splitlines():
    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", row.strip())
    if m:
        values[m.group(1)] = m.group(2).strip().strip('"').strip("'")
port = values.get("EMOI_PORT", "8080")
secret = values.get("RELAY_SECRET", "")
if not re.fullmatch(r"[0-9]{2,5}", port) or not 1024 <= int(port) <= 65535:
    raise SystemExit("无效的 EMOI_PORT")
if len(secret) < 32:
    raise SystemExit("RELAY_SECRET 缺失或过短")
print(port)
PY
)"

if ss -H -ltn "sport = :$PORT" | grep -q .; then
  if ! sudo docker ps --filter 'label=com.docker.compose.project=emoi' --filter 'label=com.docker.compose.service=emoi' --format '{{.Names}}' | grep -q .; then
    echo "端口 $PORT 被其他服务占用；停止，避免冲突。"
    exit 2
  fi
fi

AVAIL_KB="$(df -Pk . | awk 'NR==2 {print $4}')"
if [[ "${AVAIL_KB:-0}" -lt 5242880 ]]; then
  echo "可用硬盘不足 5 GiB，停止，以免影响既有云服务。"
  exit 2
fi

echo "正在建立独立的 emoi 容器，使用本机端口 $PORT"
echo "轻量模式：不另装 Latent、Ombre、Folio、Xinchao；后续再接已有服务。"
COMPOSE_ARGS=(-f "$BASE" -f "$LIGHT")
if sudo docker network inspect xlc-gateway_default >/dev/null 2>&1; then
  if [[ ! -f compose.emoi.xlc.yaml ]]; then
    echo "现有 XLC 网络可用，但缺少 Émoi 网络配置。停止，避免不完整部署。"
    exit 2
  fi
  COMPOSE_ARGS+=(-f compose.emoi.xlc.yaml)
  echo "XLC_NETWORK=ATTACHED (emoi-chat:8080)，未更改既有 Caddy 路由。"
fi
sudo docker compose -p "$PROJECT" "${COMPOSE_ARGS[@]}" config --quiet
sudo docker compose -p "$PROJECT" "${COMPOSE_ARGS[@]}" up -d --build
sudo docker compose -p "$PROJECT" "${COMPOSE_ARGS[@]}" ps

ready=0
for attempt in $(seq 1 36); do
  code="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 4 "http://127.0.0.1:$PORT/readyz" || true)"
  if [[ "$code" == 200 ]]; then ready=1; break; fi
  sleep 5
done
if [[ "$ready" -eq 1 ]]; then
  echo "EMOI_READY=YES"
  echo "EMOI_LOCAL_URL=http://127.0.0.1:$PORT/"
else
  echo "EMOI_READY=NO"
  echo "容器已尝试启动，但未通过基础健康检查。不要重启或删除其他服务。"
  echo "诊断命令：sudo docker compose -p emoi -f compose.emoi.yaml -f compose.emoi.light.yaml -f compose.emoi.xlc.yaml ps"
fi
echo "Émoi 容器内存："
sudo docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep -E '^emoi-' || true

# Read-only: show the existing gateway's configuration mount locations,
# rather than changing a gateway whose current routes are unknown.
if sudo docker inspect xlc-gateway-gateway-1 >/dev/null 2>&1; then
  echo "GATEWAY=xlc-gateway-gateway-1"
  echo "现有网关挂载位置（只读）："
  sudo docker inspect --format '{{range .Mounts}}{{println .Source "=>" .Destination}}{{end}}' xlc-gateway-gateway-1 |
    grep -Ei 'caddy|gateway|config' | head -n 8 || true
  echo "GATEWAY_NETWORKS:"
  sudo docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' xlc-gateway-gateway-1
fi

echo "HTTPS=NOT_CONFIGURED_BY_THIS_SCRIPT"
echo "不含公网地址、不打印私人密钥；把本次输出发回来，我们再复用 XLC 网关接手机 HTTPS。"
[[ "$ready" -eq 1 ]]
