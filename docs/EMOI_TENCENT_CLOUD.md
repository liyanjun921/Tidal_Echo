# Émoi · 腾讯云轻量服务器与 Garden / CyberBoss / Ombre Brain 集成验收

状态：**准备方案与单向事件入口已经编码，尚未在用户真实腾讯云实例部署或验证账号**。Émoi 开发分支已将内部模块、服务路由、数据库表和 Docker 命名统一为 `emoi_*` / `emoi`。历史 Luné 数据仅通过显式离线迁移接入；不会在启动时擅自覆盖原 vault。所有密码、模型登录和私人数据只留在服务器私有目录。

## 一、能部署，但不等于已在现有服务器运行

当前 `Dockerfile.emoi` 使用 Python 3.12、Node 24、FFmpeg 和服务端依赖；`compose.emoi.yaml` 将服务的 8080 端口只发布到宿主机回环，并挂载一个持久命名卷。`scripts/run_emoi.py` 负责 relay/API loop、影院及各个记忆进程。原项目 CI 已成功在 Linux Docker 中构建镜像、以新卷启动服务并通过基本 HTTP 验收；真实 ChatGPT/Claude 账号、手机 Safari、微信、Garden SSE、云端历史记忆和语音尚未验证。

用户已有腾讯云轻量服务器和其他云端网关时，**不要重新装系统、删旧容器、改既有网关、抢占 8080、替换真实 OB 目录或执行 `down -v`**。先只读清点：

```sh
uname -a
free -h
df -h
docker version
docker compose version
docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}'
sudo ss -ltnp
```

本机已有 CyberBoss、Garden/Desire Gateway 和 OB 时，要先核对它们各自端口和常驻方式；多进程及向量模型消耗的 RAM 必须在该实例实测。**4 GB 内存不保证可以同时承载所有服务、BGE、本地语音或视频转码。** 优先用外部云模型，不在轻量服务器本地运行大型推理模型；观察 `docker stats`、`free -h` 和 OOM 日志后才决定是否优化或升级配置。

腾讯云 Linux 轻量机可安装 Docker；建议 Docker Compose 直接在同一台机器启动 Émoi 服务，保留原有 XLC Gateway。中国内地节点使用域名对外提供网站需先满足 ICP 备案要求；香港及海外节点要求不同，以当地和腾讯云官方规定为准。

## 二、不覆盖既有服务的部署路线

以下只是假设 `8088` 当前空闲的示例；实际端口须先查证。请将 `example.com` 换为自己拥有的域名，所有密钥仅在服务器内生成与保存。

```sh
git clone https://github.com/liyanjun921/Tidal_Echo.git emoi
cd emoi
# PR 未合并前，可临时取开发分支；合并后直接使用 main
git checkout codex/emoi-internal-migration
cp emoi.env.example .env
chmod 600 .env
# 自行生成长随机 RELAY_SECRET，并在 .env 内设置
# RELAY_SECRET=（私有随机值）
# EMOI_PORT=8088
docker compose -p emoi -f compose.emoi.yaml config --quiet
docker compose -p emoi -f compose.emoi.yaml up -d --build
docker compose -p emoi -f compose.emoi.yaml ps
curl -fsS http://127.0.0.1:8088/readyz
```

配置需校验模型源代码/向量资源初始化是否完整，`/readyz` 正常也不能代替一条真实的 GPT/Claude 私聊与记忆写读测试。保持固定 Compose 项目名 `emoi`，防止以后改目录名时创建全新的卷。新默认数据库是 `/data/emoi.db`；不要把旧 `relay.db` 当成已迁移。绝不在旧的 Luné/OB 容器运行中盲目并发启动会写入同一组数据目录的新实例。

推荐 HTTPS 由现有网关或 Caddy/Nginx 提供；独立 Caddy 例子（**仅在 80/443 没有被已有代理占用时**）：

```caddyfile
chat.example.com {
    reverse_proxy 127.0.0.1:8088
}
```

仅对需要的 80/443 放行防火墙，不对公网开放 8088、3020、4182、内部 Ombre 端口或真实数据库。若不想公开入口，改用已授权的私人 VPN / Tailscale HTTPS，不要直接把内部端口暴露公网。反向代理应支持 SSE、不缓存带密钥的接口、视频 Range 与至少 4 MB 请求体；访问日志不记录 token 查询字符串。HTTPS PWA 需在手机 Safari 验证安装、持久登录、推送、后台重连。

## 二点五、旧版本数据迁移（仅已有 Luné 数据的机器）

如果服务器里已有历史 `relay.db` 和 `lune-private/`，**先停止原来写入该目录的进程并备份整个持久卷**。迁移工具只读取旧库和旧 vault，把新表名写入新的 `emoi.db`、新文件目录 `emoi-private/`，**不删除旧数据**。运行一次 dry-run 检查现状：

```sh
python scripts/emoi_migrate_storage.py --data-dir /data
```

确认数据库/原始文件已完整备份、所有旧写入端停止且磁盘空间足够后，才明确执行：

```sh
python scripts/emoi_migrate_storage.py --data-dir /data --apply
```

如果是 Docker 命名卷，先找到实际旧卷和挂载位置，不要以为更换 Compose 项目名会自动共享同一个卷。请在同时挂载旧数据的**隔离迁移容器**里执行，严禁在原容器仍写入时操作；迁移后逐项验证记录数、Ombre vault、记忆检索及重启持久化。存在新旧同名目标或半成品时脚本直接拒绝覆盖，不应通过删库绕过。

Émoi 新网页还提供 `web/legacy-storage.js`：只在当前浏览器内一次性复制旧 `lune-*` 键和已保存的壁纸/离线缓存到 `emoi-*` 名称，保留旧值作为回滚。微信、Garden、OB 跨端历史并不会因此自动同步。

## 三、Ombre Brain：代码已集成，现有真实记忆还没有迁入

Émoi 已通过 `EMOI_OMBRE_AUTO_SETUP=1` 在同一个 Compose 持久卷内安装 Ombre Brain，并由 `scripts/run_emoi.py` 启动四个隔离空间，接入 16 个原版工具、被动召回、管理页与 Folio。路径保留在 `/data/emoi-private/ombre`。这是**新实例/新 vault**，不是自动连接用户原有 PC/云端 OB 的历史数据。原有 OB 可能是另一个实例，不能因为两个实例都有 `breath_search` 就声称记忆相通。

两条可选方案：

- **迁移后以 Émoi 的云端四空间 OB 为唯一真源**：在现有 OB 停止写入或获取一致性快照后，用原版经过校验的备份/恢复功能迁移到 Émoi；按真实的 GPT/Claude/群聊归属拆分、确认每个桶的 ID、来源和检索结果，随后把其它客户端指向**同一权威 OB** 的受限 HTTPS MCP/OAuth 接口。绝不先清空旧 vault。
- **保留现有云端 OB 为真源**：需增加受认证的远程 OB 客户端适配，避免 Émoi 启动第二份独立写入器；**当前代码尚未提供该远程共享适配**，不能直接把本机的 `/ombre/<scope>/` 管理页冒充公共 MCP 地址。

完成条件：分别在 Émoi、微信侧 CyberBoss 和 Garden 所用模型检索同一枚非敏感测试记忆 ID，核对来源与原文一致；再从一个端写入后，另一个端读取到同一权威实例，而不是生成了相似的新桶。读取和写入权限应分开。

## 四、Garden：有单向事件接入脚本，但不代表能逛论坛

已有 `POST /relay/emoi/wren/{scope}/events`：Bearer 鉴权，`source=garden`，写入真实持久队列；用户空闲时由 Room 决策是否发消息、留手记或静默。Émoi 新增 `scripts/emoi_ingest_event.py`，可作为 `galatea-garden-wake-bridge` 的 **injector** 接受单行 `{"version":1,"type":"garden_wake","reason":"...","message":"..."}`，转换为 Garden 事件并 POST 到 Émoi。

仅在服务器的可信私有环境设置：

```sh
export EMOI_BASE_URL=http://127.0.0.1:8088
export EMOI_SCOPE=gpt
export EMOI_RELAY_SECRET=（Émoi 服务器的 RELAY_SECRET）
export GARDEN_INJECTOR_EXECUTABLE=/usr/bin/python3
export GARDEN_INJECTOR_ARGS_JSON='["/absolute/path/emoi/scripts/emoi_ingest_event.py"]'
# Garden 自己的 GARDEN_MACHINE_TOKEN 仍留在 bridge 内，不传给 injector。
```

先运行桥原版的 `node dist/cli.js check` 验证一次授权，再**人工** `node dist/cli.js run` 建立唯一一条 SSE。**严格保留 Garden bridge 的单次 SSE、故障退出、`Restart=no`、不得自动拉起或自动重连约束**；不要给它加 Docker `restart: always`、watchdog、cron 或无限循环。Garden v1 唤醒信封没有稳定 `event_id`，本入口会为每次 injector 调用生成新 ID；网络超时/桥自身一次有界重试可能带来重复事件，**不能宣称 exactly-once**。要实现更严格的去重，需由 Garden 上游提供真正稳定的事件标识并贯穿转发。

该接入只让 Émoi **收到 Garden 唤醒的引用**；没有自动装上 Garden MCP，也不能由一句消息声称已读取帖子、实际发帖或在原 Codex 线程继续玩游戏。需要进一步按授权接入 Garden 工具，并验证真正在目标运行时完成的动作及回执。

## 五、CyberBoss：先共享事件，再决定是否共享会话

CyberBoss 是独立的微信消息桥和 Codex/Claude Code runtime，Émoi 是基于 relay/API loop 的另一套房间模型运行时。**不能仅因都支持 MCP 就把它们视为同一个实时会话或同一个模型进程。**

`scripts/emoi_ingest_event.py` 也支持从 stdin 接收经过 CyberBoss/网关私有 adapter 正规化的事件。示例（仅为协议测试，不是 CyberBoss 已自带此 webhook）：

```json
{"source":"system","event_id":"cyberboss-message-123","type":"cyberboss.message.received","summary":"CyberBoss 收到一条经授权的用户消息事件","priority":60}
```

`source=system` 是因为当前 Émoi Room 的事件来源枚举中没有 `cyberboss`，`type` 可以用命名空间区别。CyberBoss 侧必须自行根据真实微信消息 ID/队列 ACK 建立 adapter，把稳定 `event_id` 和**最小必要**摘要交给本脚本。不要把微信全文、好友标识或任何私密字段默默镜像到 Émoi。接收到唤醒仅意味着队列入账；如要把 Émoi 的回复真正送回微信，仍需额外开发经授权的出站通道、去重、错误处理和真人对话回路。

若希望三端形成连续记忆，应先选定一个权威 OB，再按账号/空间权限给各运行时受限读取；聊天历史同步和记忆共享是两件不同的事。现阶段不迁移或替换现有 CyberBoss 微信登陆态。

## 六、上线前必须通过的检查

1. **服务器**：记录系统、RAM、硬盘、端口、Docker 状态；当前 CyberBoss、XLC Gateway、Garden、OB 不受影响。
2. **Émoi**：`/readyz` HTTP 200，HTTPS `/relay` 鉴权成功，电脑/手机 PWA 正常；重启后消息、附件、Room、四空间记忆保留。
3. **模型**：分别测试 GPT 和 Claude 真实接口，明确 API/订阅支持状况及用量；不可把 CI 的合成模型验收算成真实联通。
4. **Ombre**：备份/恢复演练、原版检索、写入、正确空间归属；明确唯一真源，跨端 ID 验证。
5. **Garden**：`check` 通过，一次 SSE 连接，合法事件确实入 Émoi 队列；异常退出不自动重连，记录真实原因；论坛 MCP 动作另行验收。
6. **CyberBoss**：实际微信入站事件有对应稳定 ID、Émoi 入账且去重；若要求微信回信则需单独的出站验收。
7. **安全**：密钥只在服务器；HTTP 内部端口不公网暴露；备份卷和凭据异地保存；`docker compose ... down` 不加 `-v`，不把敏感消息当系统提示执行。

目前完成的是**品牌改名、云端拓扑核对、Garden/CyberBoss 事件入口适配代码和实施文档**；真实腾讯云、微信、Garden 和现有 OB 的接入均依赖用户服务器实际配置，不能未经现场验证声称已经全部连通。
