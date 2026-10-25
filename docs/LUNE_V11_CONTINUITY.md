# Luné V0.11 · 空闲续接与独立日记

本版依据用户提供的《xiaoke-cat-README》补齐会话连续性：常驻 Claude 会话、先落档再重铸、聊天优先的后台任务、有证据的未完线头，以及各自封存的 Duet 日记。采用文档中描述的设计，宿主代码独立实现；没有取得或声称运行小可猫的私有源码。Latent 继续使用此前校验的原版源码，Ombre 也继续使用独立原版实例。本轮只开发和验证，没有正式部署。

## 这次补齐的行为

| 场景 | 当前行为 |
| --- | --- |
| 正在聊天时后台落档 | 自动任务须空闲至少 30 秒才开始；运行中每约 0.2 秒检查真实回复状态，新回合到来即取消后台等待，保留原游标。手动重任务也不抢占待回复回合。宿主取消不等于供应商已撤销所有远程计算或用量。 |
| 好久没聊，回来接话 | 默认空闲 30 分钟后检查本房间新对话，最多保留 3 条未完线头。每条必须有消息编号与逐字原话，无法匹配的材料不保存；没有线头则持久记录 PASS，无新内容不反复生成。 |
| 线头进入对话 | 只在该快照后的第一条人类消息前作为可忽略的历史背景递出。新话题与当前澄清优先，不写进聊天原文，不跨私聊或群聊角色。群聊分别使用两位模型各自连接。 |
| Duet 各自写 | 用户创建一轮时固定本房间已发生对话的截止编号；双方各自写，模型只得到截止前的对话和自身说明，不得到对方草稿、之前日记或另一房间。需点“请对方独立写日记”，没有新增每天定时写作。 |
| Duet 封锁 | 用户正文封存后不可改；双方都写好且时限到期才一起开放。在此之前，读接口连作者自己的正文也不返回。支持不设时间锁、小时/天/周/月和自定义分钟。 |
| Duet 失败与重启 | 没素材的 PASS、生成失败或中断不假报完成；失败/中断可显式重试。重启后未完成任务标记中断，不暗中重放。编辑草稿在面板刷新间保留于当前页面内存，未封存草稿不保证刷新网页后恢复。 |
| 共同开放通知 | SQLite 为每轮、每位接收者建立唯一通知。用户读通知与模型收到通知各自确认；模型回复成功后仅确认本轮实际拿到的通知，新解锁的不会被顺带消费。失败重试可重新递送，无法跨进程崩溃保证端到端“恰好一次”。 |

入口为 **记忆 → 检索、未完事项与引擎设置 → 会话续接 · 未完线头**，以及侧边栏 **Duet · 各自写下，再一起打开**。没有连接后台时显示真实的未连接状态，停用生成和保存。

Duet 的封锁是应用访问规则，正文以明文保存在私人 SQLite 中；拥有数据库/服务器管理权限的人仍能直接读取。它不等同于端到端加密或 Ombre 的信件锁。现有 Journal 与 Ombre 信件保持各自数据与语义。

## Claude Code 常驻桥接

`examples/lune_claude.py` 使用官方 `claude -p` 的 stream-json 输入输出，同一私聊/群聊角色串行复用一个常驻进程。启动前检查 `claude auth status` 的官方 Claude 身份，清除继承环境中的 API 凭据及云供应商路由；失败明确停止，不回退到已保存的 API Key。此检查不构成额度、套餐权益或实际账单保证。

首轮从 Luné 原文历史建立会话；以后发送当前轮与当前背景。完整人格通过私人 system-prompt 文件传入，改变人格/模型/工具集时重新投影历史，避免继续使用旧提示。关闭内建工具、hooks 和外来 MCP，只加载当前回合允许的宿主 MCP；本机派生凭据、房间与有效 run 再次校验，空闲进程没有写工具的有效绑定。临时日记/线头生成另起无工具、不恢复常驻历史的进程。

不透明 thinking 保留在官方会话文件中，不显示为网页可读思考。官方会话会保留历史上曾收到的背景；宿主能更新本轮投影，但无法把已写入官方进程历史的旧背景逐轮抹除。Luné 原文数据库不混入这些背景。尚未测量真实 CLI 的缓存命中率或真实账单。

### 自动重铸的提交条件

每分钟检查最近真实 assistant usage 中的 input、cache creation、cache read 总量；默认超过 150000 tokens、保留约 50000 tokens，且房间已空闲 30 秒才尝试。先让宿主完成原版落档，再调用已校验 Latent 的原版 `forge_session.py`。原版归档/检查点成功后才能生成保留 thinking 与 parent 链的新会话。原始官方 JSONL 文件不删除。

宿主找到唯一对应会话文件、重铸成功、用户仍空闲，并收到新进程匹配新 session ID 的 init 就绪事件，才关闭旧进程并保存新 ID。任一步失败保留旧会话，超时/取消清理临时进程。若真实 CLI 版本只有输入后才发 init，该版本将延后切换，而不会为了续接丢掉旧进程；这项兼容性仍需真实版本验收。

### 可选运行条件

桥接默认关闭。以后要启用时，需在**运行 api_loop 的同一环境、同一系统用户**安装并登录官方 CLI，确认该环境的 `claude auth status` 成功，然后给服务进程设置：

```dotenv
LUNE_CLAUDE_ENABLED=1
# 可选；默认在 RELAY_DB 同级的 lune-private/claude-code
LUNE_CLAUDE_DIR=/data/lune-private/claude-code
LUNE_CLAUDE_FORGE_THRESHOLD=150000
LUNE_CLAUDE_FORGE_RETAIN=50000
```

`LUNE_CLAUDE_COMMAND` 仅为服务器管理员配置的 JSON argv，默认从 PATH 查找 `claude`；网页不接收命令或官方账号令牌。状态接口只有已成功完成回合的常驻进程才标 ready，安装/开关状态分别呈现。网页中的订阅总览仍提示账号待验收。

现有 Windows Docker 镜像没有自动安装 Claude CLI，Compose 也没有默认启用此桥接；仅修改 `.env` 不足以让容器获得 CLI 或 Windows 的官方登录。须另行准备容器内运行端与官方配置的私人持久目录，再实际验收。当前不要求用户开始安装或部署。

## Latent / Ombre 保持各自策略

Latent 的使用权重、原版档案/游标和不按时间自动衰减策略保持不变。Ombre 的情感坐标与自身时间衰减继续由四份独立原版 vault 管理。没有把两种评分合并，也没有靠固定闲聊模板补造记忆、人格或未完事项。

新增表与聊天共用私人 SQLite。完整备份须含 SQLite、附件、配置、原版档案及官方 CLI 的私人会话/登录目录；原版 Latent ZIP 不包含整站数据库。旧聊天 JSON 导出也不包含本版封存日记与通知，不能用它单独迁移 Duet。

## 验证与边界

Python 回归 **91 项通过**。新增断言覆盖逐字来源与 PASS、聊天抢占、作者也无法提前读、跨房间隔离、封存不可改、创建时快照、独立生成、通知唯一/重启/精确确认、Claude 进程复用/失败停止与凭据隔离。重铸测试实际运行固定原版 Forge，用合成官方 JSONL 和宿主检查点，核对先落档后 checkpoint、失败不换旧进程、成功就绪才换、thinking/signature/parent 链与原文件保留。

HTTP 联调运行真实原版 Latent、真实本地 BGE、真实原版 Ombre，聊天与 Claude CLI 使用合成供应商/协议进程。覆盖日记独立生成、锁后不可读、解锁与下一轮模型请求、通知去重、无新线头不重复生成、Claude 同房间连续两轮，以及完整停机重启后聊天、Duet、Latent/Ombre 的持久恢复。测试命令：

```sh
LUNE_LATENT_SOURCE=/path/to/latent LUNE_PASSIVE_MODEL_CACHE=/path/to/models LUNE_OMBRE_SOURCE=/path/to/ombre python -m unittest discover -s tests -p 'test_*.py'
LUNE_LATENT_SOURCE=/path/to/latent LUNE_PASSIVE_MODEL_CACHE=/path/to/models LUNE_OMBRE_SOURCE=/path/to/ombre LUNE_CLAUDE_ENABLED=1 LUNE_CLAUDE_COMMAND='["/path/to/python","/path/to/repo/tests/claude_cli_fixture.py"]' python tests/run_e2e.py --http-only
```

浏览器检查静态界面入口、自定义锁时长及未连接时禁用操作。本版没有调用正式账号、安装真实 Claude CLI、构建 Docker、运行 Windows/iPhone 真机或进行生产部署。真实官方 CLI 的权限/流式/中断/恢复、套餐额度、长对话召回质量、自然接话分寸与日记风格仍需单独验收，机制通过不等于这些质量已经通过。

官方接口参考（核对 2026-10-25）：[CLI reference](https://code.claude.com/docs/en/cli-reference)、[Streaming vs single mode](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode)。
