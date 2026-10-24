# Luné V0.10 · Ombre-Brain 原版接入

本版在保留 Latent 的基础上接入所有者 fork 的 Ombre-Brain 3.6.14，固定源码 `115d831d979bf67efc7150f976e2cb34c333c935`。运行的是独立安装、未修改的原版 Python 服务和完整 Dashboard，不是仿写一个情绪记忆列表。此版只开发、验证和保存源码，不创建云端资源或推进正式部署。

## 已接入的产品能力

| 原版能力 | Luné 接线及本地验证 |
| --- | --- |
| `breath` / `breath_search` / `breath_advanced` | 开场浮现、每轮 automatic 混合检索、目录与精细筛选；原版 schema 直接交给模型。实际模型 HTTP 请求收到临时记忆背景。 |
| `hold` / `grow` | 一件事写入、长内容拆条、原文证据与来源范围；真实工具请求写入原版档案，随后可以检索。 |
| `trace` | 改情感坐标、元数据、正文局部修订、关系、归档恢复、消化与浮现标记；保留原版全部参数。 |
| `feel` | 留下感受并按原版规则检索；未命中不补造感受。 |
| `dream` | 原版近期材料、感受、承诺及 I 候选回顾与见证。它把材料交给模型消化，不等于宿主凭空生成一场梦。 |
| `pulse` | 原版数量、衰减及运行诊断。 |
| `plan` | 原版承诺、关联和状态；不擅自把建议当作完成。 |
| `anchor` / `release` | 原版坐标系设置和解除，保留硬配额。 |
| `letter_write` / `letter_read` / `letter_lock_update` | 原文信件与时间锁、永久锁、写信方权限；测试 AI 时间锁信不向人类管理页泄漏正文，AI 可读取自己的信并解锁。永久锁等其他分支沿用原版，未穷举各时区与边界日期。 |
| `I` | 自我认识候选、正式条目、替代和多日期 dream 见证；本地验证创建候选与读取，未伪造跨三日的真实人格沉淀。 |
| 可选 `You` / `Them` | 原版独立开关，动态从 16 个基础工具变成 17 / 18 个；开关后直接调用原版处理器。保留原版认识可见性，不填入示例人格。 |
| 情感坐标、遗忘衰减、融合检索 | 原版桶、衰减服务与向量队列随各空间服务运行；本地 BGE 512 维由现有 Latent 工作进程提供，避免 Ombre 再各自装载本地模型。 |
| 完整管理页 | 原版桶、搜索调试、网络、引擎、认识、信件、导入、配置、诊断等页面通过鉴权代理嵌入 Luné。只对投影做路径适配和灰白蓝配色，不修改原版源文件。 |
| 导入与备份 | 原版预检、上传、任务状态、导入结果；ZIP 清单/来源完整性、冲突选择与应用。真实测试结构化记忆导入完成、ZIP 恢复任务完成及正文再读，损坏 ZIP 明确拒绝。历史对话的模型提炼质量仍需真实连接验收。 |
| GitHub 同步、OAuth / Tunnel、Ollama、供应商设置、更新 | 原版实现和管理入口全部保留；需要所有者配置对应凭据、网络及运行端。没有代替用户启用同步、公网隧道或外部账户。详见下方边界。 |

基础 16 工具：`breath`、`breath_search`、`breath_advanced`、`hold`、`grow`、`trace`、`dream`、`feel`、`pulse`、`plan`、`anchor`、`release`、`letter_write`、`letter_read`、`letter_lock_update`、`I`。宿主为它们加 `ombre_` 前缀，防止和 Latent / 其他 MCP 重名；参数与原版语义保持。

## 房间、权限与自然接话

GPT 私聊、Claude 私聊、群聊中的 GPT 和群聊中的 Claude 使用四个独立 vault、配置、认识与锁身份。两位模型在群聊中都可以记住公开群聊内容，但不能直接读写对方的档案，更不能读取私聊。外部同步也按四份配置独立管理，不复用一套 GitHub 目标。

开场 `breath` 和每轮 `breath_search(mode="automatic", max_results=2)` 在真实模型请求前执行。Ombre 开场判定可独立于 Latent 的启用与健康状态工作。关掉某空间的自动浮现后，显式检索工具仍可用；关闭 Ombre 则停止向该空间模型提供其工具和背景。写入同时受 Luné 的模型写入开关及当前有效回合约束。失效回合和错误房间不能进入原版工具。

原版自动检索尊重 `digested` / `dont_surface`，主动检索仍可找回。测试中 dream 会使已消化材料不再自动递出，这是预期行为，不能绕过原版标记来营造“每轮都有回忆”。超大投影整块省略，不截成失真的半段；原生检索工具继续可用。

召回只进入本轮模型请求，不写进聊天原文。模型得到的说明是：先回应当前话语，旧事只作背景，可忽略弱关联，不逐条引用、不汇报检索；工具操作后撤下本轮旧投影，避免刚改正的旧内容继续注入。原有 `lune_memory` 的明确要求/逐字原话规则只约束该工具；Ombre 自主沉淀与 Latent 归档按各自原版协议，并必须基于真实互动。

这些证明了原版材料能够进入请求，不代表真实模型的长期自然联想、情绪分寸与人格成长已经验收。本轮不调用用户正式账号或付费聊天模型。

## 完整原版入口与运行依赖

网页路径：**记忆 → 检索、未完事项与引擎设置 → Ombre-Brain · 情绪与经历记忆 → 选择空间 → 打开完整管理页**。未连接时明确显示预览并停用真实操作，不制造运行数据。

四个原版进程只监听本机回环；外部只通过 Luné 的已鉴权管理代理进入。管理 Cookie 按空间签名、HttpOnly、限时，服务工作线程不缓存这些页面与 API。派生的原版服务凭据不会暴露 Luné 连接密码。模型整理由对应 GPT / Claude 连接完成，没有为 Claude 私聊改走 GPT，也没有在订阅不可用时偷偷回退 API。

原版外部 MCP / OAuth / Tunnel 是连接端能力。嵌入管理页的 `/ombre/<scope>/` URL 依赖所有者 Cookie，**不能直接作为 Claude.ai 等外部客户端的公共 MCP 地址**；外部客户端需在对应原版实例配置独立的权威 HTTPS 来源、鉴权和网络转发，再验收 OAuth。Ollama 的下载安装依赖网络、系统工具和原版进程可访问的安装目录，本轮没有下载大模型或启动公网连接。

同步、更新按钮调用的是原版实现；宿主固定在已验证版本。原版自更新会改变源码哈希，后续校验会报告不一致，不能声称未经验证的新版本与本宿主兼容。需要升级时应先备份、在开发环境重新验证该版本并更新宿主固定版本与校验清单，不应在私人长期运行数据上盲目更新。

因此，本版交付的是完整原版能力的宿主接线和管理入口；第三方账户、外部 OAuth、公网连接、系统安装和跨版本更新不是“未配置就已跑通”的功能。

## 后续运行配置

保留现有 Windows Docker 启动方案。Compose 已增加：

```text
LUNE_OMBRE_AUTO_SETUP=1
LUNE_OMBRE_SOURCE=/data/lune-private/ombre/source
LUNE_OMBRE_DIR=/data/lune-private/ombre
```

首次启动单独拉取固定源码并校验；原版 LICENSE / AUTHORS / NOTICE 留在安装目录。四个 vault 与配置保存在已有私人持久卷，源码不进入公开网页目录。宿主新增依赖见 `backend/ombre-requirements.txt`；Docker 构建同时安装现有聊天与原版依赖。当前不要求用户开始部署；Docker 镜像和 Windows / iPhone 真机仍需对应环境验证。

## 验证记录

本地 Python 回归共 **79 项通过**，包括 8 项 Ombre 边界测试：房间/角色隔离、凭据与 Cookie 边界、配置保留及环境隔离、页面路径适配、代理鉴权、失效回合与错误房间阻断、私有缓存排除、Ombre 独立开场。

HTTP 联调使用真实原版 Ombre、真实本地 BGE 向量和合成聊天/语音供应商：16 个原生工具、You/Them 动态开关、模型工具写入、每轮自动背景、四 vault 隔离、信件时间锁与解锁、ZIP 导出/恢复与损坏包拒绝、结构化导入均有断言。完整进程停止重启后再次核对聊天、Luné 记忆、Latent 档案与 Ombre 原文检索。脚本：

```sh
LUNE_LATENT_SOURCE=/path/to/latent-runtime LUNE_PASSIVE_MODEL_CACHE=/path/to/latent-model-cache LUNE_OMBRE_SOURCE=/path/to/ombre-brain python -m unittest discover -s tests -p 'test_*.py'
LUNE_LATENT_SOURCE=/path/to/latent-runtime LUNE_PASSIVE_MODEL_CACHE=/path/to/latent-model-cache LUNE_OMBRE_SOURCE=/path/to/ombre-brain python tests/run_e2e.py --http-only
```

浏览器人工检查了真实静态界面的记忆导航、并列 Latent/Ombre 入口、四空间选择及未连接禁用提示。此项不代替嵌入原版管理页的全功能浏览器或 iPhone 真机验收。原版全部分支与第三方服务未穷举，完整功能对照表不等于每个分支都已实测。
