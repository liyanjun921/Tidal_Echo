# Luné 免费、不绑卡部署评估

核对日期：2026-10-24。用户优先免费、尽量不绑银行卡，同时考虑 Render 与 Netlify，并要求保留原版 Latent 的完整能力。此评估没有创建资源、升级方案、接通真实模型或改变现有记忆实现。

## 当前结论

Netlify Free 适合承载手机网页、PWA 与经过适配的短请求接口。Render Free 可以运行 Python 服务，但当前完整 Luné + 本地 Latent **不能原样作为可靠的免费云端部署交付**：本地内存采样超出 512MB，且现有数据库、原生语料和状态仍要求持久文件系统。把两家组合起来不会自动解决这些问题。

这是当前代码与当前免费产品限制的结论，不代表经过改造的方案永远不可行。不能把“平台有免费套餐”“界面上线”或“接了云数据库”当作完整 Latent 已部署的证据。完整功能要求保持，未通过的能力不得在页面显示为已启用。

## 平台对照

| 项目 | Render Free | Netlify Free |
| --- | --- | --- |
| 手机网页 / HTTPS / PWA | 可以托管 | 可以托管；适合前端 |
| 原样运行目前的 Python 双进程与原生工作进程 | 支持 Python，但资源不足待优化 | 现有常驻服务不能直接作为标准 Functions 部署 |
| 可用内存 | 512MB，0.1 CPU | Functions 按平台运行时与时限执行，不是常驻服务器 |
| 本地 SQLite / 上传 / 原版 Markdown 和 sidecar 账本 | 重启、重部署或休眠会丢；免费服务不能挂持久盘 | 函数临时文件不能作为持久源 |
| 独立持久数据产品 | 免费 Postgres 30 天到期，不适合作长期记忆 | Database 和 Blobs 可用，但需要改造代码并核对账户方案与额度 |
| 全天后台落档、主动消息 | 空闲 15 分钟会休眠；休眠期间不能执行任务 | 定时 / 后台 Functions 有时限；不能直接保留常驻循环 |
| 实时通信 | 运行时支持 SSE / WebSocket；需处理冷启动和断线补发 | 流式 Function 最长 60 秒，不能原样承载无限 SSE |
| 不绑卡 | 可以存在未添加付款方式的免费账户；不能保证每个账户免额外验证 | 官方 Free 方案无需信用卡；具体账户仍可能有平台验证 |
| 超额度 | 无付款方式时可能暂停免费服务或构建 | Free 有硬额度上限，不会自动买额度；达到上限影响可用性 |

## 内存证据

原始摘要见 [free-hosting-memory-profile.json](free-hosting-memory-profile.json)。采样对象是完整 HTTP E2E 的 **Luné supervisor 和它的子进程**，包括两套 Python 应用、原版本地 BGE 向量工作进程及归档任务，不包含模型供应商 / MCP 合成服务和测试客户端。

采样区分 RSS 与按共享页分摊的 PSS；不能仅靠相加 RSS 判定实际占用。报告的 PSS 峰值也已超过 Render Free 的 512MB。发现 relay 和 api_loop 两个应用各保留一个原生工作进程，重复加载本地模型，是可研究的优化点。

这次是本地 Linux x86_64、小型合成语料、已缓存模型的测量，**不是** Render 容器 / cgroup 的 512MB 验收；页面缓存、容器开销、未来语料与未捕获瞬时峰值不能据此排除。没有推断 2GB 一定够用或保证某个付费规格。

复现时使用已安装项目依赖的 Python，设置独立安装的 `LUNE_LATENT_SOURCE` 和 `LUNE_PASSIVE_MODEL_CACHE` 后运行：

```sh
python scripts/profile_lune_memory.py --output /tmp/lune-memory-profile
```

脚本运行完整 HTTP E2E，使用合成模型 / 语音凭据，不需要真实模型费用；只输出进程类别和内存统计，不输出私人环境变量。报告不替代真实账户、iPhone 和正式平台测试。

## Netlify 免费额度不能按无限使用设计

新 Credit-based Free 方案每月共享 300 credits。生产发布每次 15 credits；数据库运行按 10 credits / compute-unit hour，Free 数据库最小与最大均为 1 compute unit，空闲 5 分钟休眠。网页流量、函数和数据库还共享其他计量。

因此，即使把全部 300 credits 都分配给数据库，理论上也只有 30 个最小规格活跃小时；实际要扣除发布、页面、函数和流量。每天活跃 2 小时、30 天的示例，仅数据库计算即约 600 credits，超过 Free 月额度。这是预算示例，不是聊天次数或每句话成本承诺。

不能用频繁轮询 / 定时唤醒数据库来实现全天在线；它会让数据库保持活跃并加快耗尽额度。数据库和 Blobs 的存储收费仍须按账户当前账单和公告核对，不能沿用文档中已过去的存储免费截止日期当作保证。旧账户可能是 Legacy 方案，不能擅自切换账户计划。

## 候选方案与通过条件

### A. Netlify 网页 + 用户已有电脑运行完整后端

用户现已确认有可一直开机的 Windows 电脑，优先选择本路线。保留目前原版 Latent、本地 BGE、SQLite 与文件目录，可免新增云服务器账单。电脑需要在使用时开机并提供经过鉴权的 HTTPS 入口；主动消息与后台任务仅在电脑运行期间执行。手机继续打开网页，私人连接需要手机 Tailscale 客户端。已提供 [Windows 启动入口与私人 HTTPS 接入](LUNE_WINDOWS.md)，首次 Windows 安装、镜像构建、HTTPS 与 iPhone 访问稳定性尚未验收；不把准备完成当作已部署。

### B. Netlify 网页 / 持久存储 + Render Free 按需计算

是需要验证的云端候选，不是现成免费组合。保留完整功能的必要工作至少包括：

1. 减少重复向量模型加载，实际证明完整聊天、管理与归档并发时低于 512MB 且有余量；不能靠停用 Passive Recall 或改成关键词检索冒充优化成功。
2. 消息、运行游标、配置与任务状态迁到事务数据库；附件和不可变档案版本放私人对象存储。保持现有房间隔离、更正、撤回、冷却与来源治理。
3. 原生文件系统工作区需要一致的加载 / 提交协议；成功回执前持久提交，处理实例中止、重试、版本冲突、任务中断、原生多文件更新。定时 ZIP 上传不能提供无丢失承诺。
4. 对象存储不作为正在写入的 SQLite 网络硬盘，不把多份本地副本直接覆盖成一个 blob。备份必须包括原生正文和全部 sidecar / persona / notes / threads / archive 状态。
5. Render 休眠后按请求恢复；处理前端等待、重复发送、断线补发。明确全天后台行为未获保障，未经验证不通过平台保活把它写成常驻服务。
6. 安装源 / 模型冷启动耗时、512MB 内存、持久恢复和 Netlify 月度用量都须在真实免费平台实测。向云向量服务发送语料必须由所有者显式选择，不能为省内存偷偷改路由。

### C. 全部迁成 Netlify Functions

需要迁移 Python 原生工具 / 本地模型运行方式、事务存储、短任务调度与流式连接；这比现有后台部署大得多。仅用 JavaScript 重写一组相似按钮或检索接口，不能视作“原版 Latent 全部功能”迁移成功。当前不将其列为最快可交付路径。

## 本轮结果与下一步边界

- 完整 HTTP 流程通过，覆盖原版 Passive Recall 的实际请求注入与冷却、10 工具、归档、自审 / 事实、导入、备份、人格文件流程、回填、续接检查点，以及同目录重启恢复。
- 完成当前实现的内存采样，发现 Render Free 无法直接承载的证据；新增可复现的采样脚本。
- 没有创建付费资源、绑定银行卡、修改现有生产站点或删减功能；没有宣称免费云端完整上线。
- 用户已确认使用自己的 Windows 电脑，优先 A。B 保留为需要工程验证的备选。若未来改为只接受手机 + 云端，仍需重新核对免费条件与完成适配、实测。

## 官方依据

- [Render Free：休眠、磁盘、数据库到期与额度](https://render.com/docs/free)
- [Render Compute Plans：Free 的 CPU / 内存](https://render.com/docs/compute-plans)
- [Netlify Free：无需信用卡](https://www.netlify.com/blog/introducing-netlify-free-plan/)
- [Netlify 当前套餐与计量](https://www.netlify.com/pricing/)
- [Netlify Credit-based plans](https://docs.netlify.com/manage/accounts-and-billing/billing/billing-for-credit-based-plans/credit-based-pricing-plans/)
- [Netlify Database 计费、休眠与限制](https://docs.netlify.com/build/data-and-storage/netlify-database/billing-and-usage/)
- [Netlify Functions 配置与执行时限](https://docs.netlify.com/build/functions/configuration/)
- [Netlify Blobs：持久性与并发限制](https://docs.netlify.com/build/data-and-storage/netlify-blobs/)
