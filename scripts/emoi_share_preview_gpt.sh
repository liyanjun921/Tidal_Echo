#!/usr/bin/env bash
# Reuse the official ChatGPT plan store with shared refresh-token file locks.
# Preview and official room databases remain separate.
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# Avoid hidden path fallbacks: the overlay must be next to this script\u0027s parent.
[[ -f "$ROOT/compose.emoi.yaml" ]] || { printf "Émoi 脚本目录定位失败：%s\n" "$ROOT" >&2; exit 1; }
PROJECT='emoi-phone-preview'
PREVIEW='emoi-phone-preview-emoi-1'
OFFICIAL='emoi-emoi-1'
OVERLAY='compose.emoi.preview.yaml'
MARKER='# EMOI_SHARED_CHATGPT_PLAN_V1'
BACKUPS="$HOME/.emoi-preview-link-backups"
mkdir -p "$BACKUPS"
BACKUP="$BACKUPS/compose.emoi.preview.$(date -u +%Y%m%dT%H%M%SZ).yaml"

status() { printf '\n[Émoi] %s\n' "$*"; }
fail() { printf '\nÉmoi GPT 连接失败：%s\n预览版与正式版的数据库未删除。\n' "$*" >&2; return 1; }

for command in docker python3 curl; do command -v "$command" >/dev/null 2>&1 || { fail "服务器缺少 $command"; exit 1; }; done
for file in compose.emoi.yaml compose.emoi.light.yaml "$OVERLAY" .env; do [[ -f "$file" ]] || { fail "缺少 $file"; exit 1; }; done
sudo docker inspect "$PREVIEW" >/dev/null 2>&1 || { fail "未找到运行中的预览容器"; exit 1; }
sudo docker inspect "$OFFICIAL" >/dev/null 2>&1 || { fail "未找到运行中的正式容器"; exit 1; }

status '核对正式版 GPT 授权与模型设置（不输出凭据）'
model_settings="$(sudo docker exec -i "$OFFICIAL" python - <<'PY'
import json, os
from pathlib import Path
p=Path(os.environ['LOOP_CONFIG'])
cfg=json.loads(p.read_text(encoding='utf-8'))
gpt=cfg.get('agents',{}).get('gpt',{})
if gpt.get('connection_mode') != 'chatgpt_plan' or not gpt.get('subscription_model'):
    raise SystemExit('正式版尚未设置 ChatGPT 订阅模型；停止')
print(json.dumps({'connection_mode':'chatgpt_plan','subscription_model':gpt['subscription_model']},ensure_ascii=False))
PY
)" || { fail '正式版 GPT 配置检查未通过'; exit 1; }
[[ -n "$model_settings" ]] || { fail '正式版模型配置为空'; exit 1; }

OFFICIAL_DATA="$(sudo docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$OFFICIAL")"
[[ -n "$OFFICIAL_DATA" && "$OFFICIAL_DATA" == /* ]] || { fail '未找到正式版 /data 持久卷'; exit 1; }
AUTH_DIR="$OFFICIAL_DATA/emoi-private"
sudo test -f "$AUTH_DIR/chatgpt-plan.json" || { fail '正式版授权文件不存在'; exit 1; }

status '给预览版挂载同一份 ChatGPT 授权（并行续期共享文件锁）'
if ! grep -Fq "$MARKER" "$OVERLAY"; then
    cp -p -- "$OVERLAY" "$BACKUP"
    AUTH_DIR="$AUTH_DIR" MARKER="$MARKER" OVERLAY="$OVERLAY" python3 - <<'PY'
import json, os
from pathlib import Path
p=Path(os.environ['OVERLAY'])
s=p.read_text(encoding='utf-8')
needle='    mem_limit: 1024m\n'
if s.count(needle)!=1 or '    volumes:' in s or '    environment:' in s:
    raise SystemExit('预览 Compose 结构不同，已停止，避免覆盖已有挂载')
block=(os.environ['MARKER']+'\n'
       '    environment:\n'
       '      CHATGPT_PLAN_FILE: /shared-gpt-auth/chatgpt-plan.json\n'
       '    volumes:\n'
       '      - type: bind\n'
       '        source: '+json.dumps(os.environ['AUTH_DIR'])+'\n'
       '        target: /shared-gpt-auth\n')
p.write_text(s.replace(needle,needle+block),encoding='utf-8')
PY
else
    grep -Fq "source: $(AUTH_DIR="$AUTH_DIR" python3 -c 'import json,os;print(json.dumps(os.environ["AUTH_DIR"]))')" "$OVERLAY" || { fail '发现不同的授权挂载，不自动覆盖'; exit 1; }
fi

compose() { sudo docker compose -p "$PROJECT" -f compose.emoi.yaml -f compose.emoi.light.yaml -f "$OVERLAY" "$@"; }
compose config --quiet || { fail '预览 Compose 语法检查失败；备份在 $HOME/.emoi-preview-link-backups'; exit 1; }

status '应用预览容器配置（不构建镜像、不更新正式版）'
compose up -d --no-build emoi || { fail '预览容器启动失败，备份文件已保留'; exit 1; }

status '同步 GPT 模型选择，保留预览版的其他设置'
printf '%s' "$model_settings" | sudo docker exec -i "$PREVIEW" python -c '
import json,os,sys,tempfile
from pathlib import Path
p=Path(os.environ["LOOP_CONFIG"])
p.parent.mkdir(parents=True,exist_ok=True)
cfg=json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
model=json.load(sys.stdin)
if model.get("connection_mode")!="chatgpt_plan" or not model.get("subscription_model"):
    raise SystemExit("invalid GPT route")
cfg.setdefault("agents",{}).setdefault("gpt",{}).update(model)
if p.is_file():
    import shutil
    shutil.copy2(p,p.with_suffix(".before-shared-gpt.bak"))
fd,tmp=tempfile.mkstemp(prefix=p.name+".",suffix=".tmp",dir=p.parent)
try:
    with os.fdopen(fd,"w",encoding="utf-8") as out:
        json.dump(cfg,out,ensure_ascii=False,indent=2)
        out.flush();os.fsync(out.fileno())
    os.chmod(tmp,0o600)
    os.replace(tmp,p)
finally:
    if os.path.exists(tmp):os.unlink(tmp)
' || { fail '写入预览 GPT 路由失败'; exit 1; }

status '验证容器、共享授权以及一次真实 GPT 联系人回复'
ready=0
for _ in $(seq 1 50); do
  code="$(curl --noproxy '*' -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8089/readyz || true)"
  if [[ "$code" == 200 ]]; then ready=1; break; fi
  sleep 2
done
[[ "$ready" -eq 1 ]] || { fail '预览服务器未通过 /readyz'; exit 1; }

sudo docker exec -i "$PREVIEW" python - <<'PY'
import json,os,sys,urllib.request,urllib.error
sys.path.insert(0,'/app/examples')
from emoi_auth import PlanStore
status=PlanStore().status()
if not status.get('ready'):
    print('E2E_FAIL: 共享授权未就绪')
    raise SystemExit(1)
print('AUTH_SHARED_OK')
req=urllib.request.Request(
    'http://127.0.0.1:3020/loop/contact-reply',
    data=json.dumps({'route':'gpt','contact_id':'emoi-private-check',
        'name':'连接验收','history':[{'author':'human','text':'仅回复：OK'}]}).encode('utf-8'),
    headers={'Content-Type':'application/json'},method='POST')
try:
    with urllib.request.urlopen(req,timeout=125) as r:
        payload=json.load(r)
        if r.status==200 and isinstance(payload.get('text'),str) and payload['text'].strip():
            print('CONTACT_GPT_REPLY_OK')
        else:
            print('E2E_FAIL: 模型返回空文本');raise SystemExit(1)
except urllib.error.HTTPError as e:
    print('E2E_FAIL_HTTP',e.code,e.read(300).decode('utf-8',errors='replace'))
    raise SystemExit(1)
except Exception as e:
    print('E2E_FAIL',type(e).__name__)
    raise SystemExit(1)
PY

status '已完成：预览版 GPT 联系人真实回复测试通过；正式版未重启，两个聊天数据库独立。'
status '后续更新小手机预览版时，仍然使用原来的三份 Compose 文件即可。'
