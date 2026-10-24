# Luné 部署与 iPhone 使用

本版把网页和 relay 合并为一个同站服务，内部 api_loop 只监听服务器本机。用户在 iPhone Safari 打开 HTTPS 地址即可使用，不需要在 iPhone 安装 Node、运行脚本或使用 Replit。

## 服务器入口

支持 Python 3.12 或 Docker 的持久服务器。纯静态网页托管只能展示 UI，无法独立运行本版 SQLite、模型中转和 MCP。

推荐数据目录 `/data`，必须是持久卷。最少设置：

```dotenv
RELAY_SECRET=请替换为随机生成的长连接密钥
PORT=8080
RELAY_DB=/data/relay.db
RELAY_UPLOAD_DIR=/data/uploads
LOOP_CONFIG=/data/api_loop.config.json
LOOP_CACHE_DIR=/data/loop_cache
RELAY_BRAIN_FILE=/data/brain_target
RELAY_AI_NAME=Luné
RELAY_APP_PATH=/
```

容器构建文件是 `Dockerfile.lune`。运行时挂载持久目录到 `/data`，注入以上变量，仅将 8080 接到支持 SSE 的 HTTPS 反向代理；不对外开放内部 3020 端口。代理转发 `/relay/app/stream` 时关闭缓冲，空闲超时至少 10 分钟。访问日志不要记录查询字符串，因为 EventSource 的连接密钥会放在 token 参数中。

开发环境可用 Python：

```sh
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r examples/requirements.txt
# 将所需环境变量注入进程；不要把实际密钥写进仓库
.venv/bin/python scripts/run_lune.py
```

进程入口 `scripts/run_lune.py` 会启动网页/relay 和内部 api_loop，并在任意一方退出时结束另一方。单实例、单 worker 运行；SQLite 和内存任务表不支持直接横向扩容。Docker 配置文件已提供，但本次环境没有 Docker 引擎，因此镜像构建尚未实测；相同 Python 双进程启动方式已完成浏览器联调。

### 容器部署配置

已提供 `compose.lune.yaml` 和 `lune.env.example`。运行端准备私人 `.env` 中的连接密钥后，执行 `docker compose -f compose.lune.yaml up -d --build`。网页端不需要装 Docker 或 Node。容器将 SQLite、上传、模型设置、Latent 源码、向量缓存、冷却状态及完整档案放在同一个 `/data` 持久卷内，仅在服务器回环地址发布 8080；HTTPS 反代接入该端口。普通更新保留此卷。

上线健康检查使用 `/readyz`：实际核对 SQLite、内部 api_loop 和自动安装模式下的 Latent 本地资源，成功返回 200；依赖未就绪返回 503，响应不包含私人配置。它不代替真实账号对话测试。首次安装会下载公开源码、模型及 tokenizer，容器健康检查留出初始宽限期；最终耗时取决于运行端网络。

Render 路线尚未创建资源。其持久磁盘需要付费服务，不能将无持久盘的免费服务作为这版私人记忆库的正式保存位置。使用 Render 前须确认工作区、服务方案、磁盘和费用；当前部署配置本身不会创建或计费任何云端资源。规格依据为 Render 当前的 [持久磁盘文档](https://render.com/docs/disks)。已有支持 Docker 的服务器也可使用同一份 Compose 配置。

本轮部署准备验证：71 项 Python 测试通过；真实本地 HTTP 联调包含 `/readyz`，并完整停止、重启双进程后核对消息、保存的记忆及原版档案仍可读取和检索。Compose 已通过 YAML 结构、引用文件和持久目录检查；当前环境没有 Docker 引擎，尚未执行镜像构建或 Compose 启动，也没有创建正式公网后端。

## 手机配置

Latent 完整功能接线见 [V0.9 功能表与验证](LUNE_V09.md)。在服务器设置 `LUNE_LATENT_AUTO_SETUP=1` 后首次启动会独立安装固定源码并准备本地向量模型与 tokenizer，不把这些资源打进镜像；需要 Git 及首次下载网络，并将资源目录放在持久私人卷。新增完整原版工具、后台落档、人格初始化、导入与山屋数据管理；后台使用当前选定模型，私聊不跨模型整理。资源不足不会伪造成功，静态预览也不运行 Python 记忆服务。

使用 ChatGPT 订阅代替 API Key 时，先按 [V0.6 订阅连接](LUNE_V06.md) 在电脑完成官方登录并连接到自己的服务器，再从手机选择订阅模型。Claude 订阅目前仅预留官方交互式 CLI 桥接，尚不能直接聊天；选中预留模式不会调用已保存的 API Key。

1. Safari 打开自己的 HTTPS 地址，点设置，API 地址保留 `/relay`，输入服务器连接密钥。
2. 分别展开 GPT、Claude 设置，填写自己的 API Base URL、固定模型 ID、API Key 和接口格式。OpenAI 兼容一般填包含 `/v1` 的基础地址；不要填完整 `/chat/completions`。Anthropic 可填服务基础地址或以 `/v1` 结尾的基础地址。中转站格式以其接口说明为准。
3. 保存，再选择“测试已保存配置”。测试会请求一次模型，可能产生少量用量。密钥框清空表示已交给服务端，不表示保存失败。
4. 从 Safari 分享菜单选择“添加到主屏幕”；从主屏幕打开，检查键盘、附件和返回操作。
5. 在各自私聊开始对话；群聊默认各回一次，支持 `@GPT` / `@Claude`。记忆页可新建，用户消息旁可保存原文出处。

## 可选服务

朗读支持 MiniMax 与 ElevenLabs。连接正式服务器后，在「设置 → 朗读设置」选择服务、填写 API Key、音色 ID 和模型 ID，再保存；密钥输入框会清空，留空保留服务器密钥。点「试听已保存配置」会提交固定的测试短句，可能产生语音用量。两个服务的配置分别保存，切换后下一次朗读生效；失败不会自动向另一家发送文字。

也可用环境变量提供初始值：MiniMax 使用 `MINIMAX_API_KEY`、`MINIMAX_MODEL`、`MINIMAX_VOICE_ZH`、`MINIMAX_API_BASE`、`MINIMAX_GROUP_ID`；ElevenLabs 使用 `ELEVENLABS_API_KEY`、`ELEVENLABS_VOICE_ID`、`ELEVENLABS_MODEL`、`ELEVENLABS_API_BASE`，默认模型为 `eleven_multilingual_v2`，API 基础地址为 `https://api.elevenlabs.io`。`LUNE_TTS_PROVIDER` 默认 `minimax`，可设为 `elevenlabs`。音色必须是自己账户可使用的音色 ID。

手机保存的覆盖配置位于私人 SQLite 的 `lune_speech` 表，GET 接口只返回是否已配置密钥，不返回密钥本身；不要公开数据库。消息旁点「朗读」，播放器提供播放/暂停和停止；单次最多 900 字符。若 iPhone 阻止自动播放，点播放器的播放键。服务器请求已用合成服务验证，真实账户与 iPhone 音频仍待实测。

Web Push 需要一对 VAPID 密钥，公钥填 `VAPID_PUBLIC_KEY`，私钥 PEM 内容或文件路径填 `VAPID_PRIVATE_PEM`，并填写自己的 `VAPID_SUBJECT`。在 HTTPS 主屏幕应用内点“开启消息通知”，允许通知，再点测试，最后锁屏验证实际送达。未配置时会明确提示，不能把按钮存在当作通知已接通。

MCP 设置支持 HTTP 服务及可选 Authorization 请求头，界面可查看连接状态、重连和移除。需要 stdio 或复杂请求头时，使用保留的上游设置界面 `/tidal-original/`，或在私有 `api_loop.config.json` 配置 `mcp_servers`；API loop 继承上游 HTTP/stdio、headers/env 和重连能力。仅连接自己授权的服务；模型会得到所启用工具的调用权限。

## 更新与备份

完整备份至少包含 `/data/relay.db`（使用 SQLite 在线备份或停止服务后拷贝）、`/data/uploads/`、`/data/api_loop.config.json` 以及 VAPID 私钥。JSON 导出适合查看/迁移文本，不能替代完整恢复备份。

更新网页应递增 `web/sw.js` 中的 CACHE 版本。发布前检查没有携带真实 `.env`、配置、数据库、上传内容或私钥；仓库和 Docker 上下文已有对应忽略规则。

待实机验收：iPhone Safari/主屏幕应用键盘和安全区、真实供应商流式中断、识图、MiniMax、通知锁屏送达、第三方 MCP 鉴权及持久卷重启恢复。
