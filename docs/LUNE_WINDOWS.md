# Windows 电脑运行，iPhone 聊天

这条路线使用自己的 Windows 电脑运行现有完整后端和 Latent，本地 BGE 保持启用，记忆保存在 Docker 的私人持久数据卷。电脑还直接提供聊天网页，通过 Tailscale Serve 的私人 HTTPS 地址在 iPhone 打开。已有 Netlify / Sites 界面预览可以保留；正式聊天不经过 Netlify 代理，减少跨域、流式超时与云端额度消耗。

个人用途的 Docker Desktop 和 Tailscale Personal 均有免费使用方式，本流程不创建云服务器、购买域名或要求填写银行卡。首次安装软件、系统提示和个人账号登录由本人完成；模型订阅、API 和语音服务仍按各自账户计费。

## 第一次只做这些

1. 在 Windows 安装 [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)，采用 WSL 2 / Linux containers。按安装器要求启用 WSL、虚拟化或重启，然后打开 Docker Desktop，等它显示引擎正在运行。Docker 官方要求符合支持周期的 Windows / WSL 版本，电脑至少 8GB 内存。若出现系统版本、WSL 或虚拟化报错，保留原提示后再处理，不反复重装。
2. 在电脑安装 [Tailscale for Windows](https://tailscale.com/download/windows)，iPhone 安装 [Tailscale](https://tailscale.com/download/ios)。两边登录同一个个人账号（可以用个人 GitHub / Apple 等支持的登录入口），使用 Personal 免费方案。连接 iPhone 时会有系统 VPN 配置确认。
3. 下载本开发分支 ZIP，**全部解压**到自己的固定目录，比如用户文档中的 `Lune` 文件夹。保留整个项目；不要在压缩包内部运行，也不要放到公开网页目录。正常双击 **`Lune-Start.cmd`**。第一次会构建镜像、独立安装固定原版 Latent 和下载公开模型，耗时取决于网络；以后会复用数据和模型缓存。
4. 成功后电脑打开聊天页和一份私人连接信息。页面里的连接密码填这份信息中的 `Connection password`，API 路径保持 `/relay`。连接信息也可随时双击 **`Lune-Access.cmd`** 再看。
5. 双击 **`Lune-Phone.cmd`**。Windows 可能要求管理员确认，这是 Tailscale Serve 在 Windows 的要求。若首次要求启用 HTTPS，按 Tailscale 显示的链接在其官方页面确认，再双击一次。它只设置私人网络访问，不启用公网 Funnel；如果这台电脑原先有其他 Serve / Funnel 配置，会保留原配置并停止自动设置。
6. iPhone 保持 Tailscale 已连接，用 Safari 打开连接信息中的 `https://...ts.net/` 地址，填写连接密码。在 Safari 分享菜单选择「添加到主屏幕」，以后从图标打开。

首次构建完成只表示程序就绪；要在设置里连接真实模型，才能验证实际 AI 对话。原版 Passive Recall 的运行检查、导入、备份和其他入口仍在记忆面板。GPT 订阅连接见 [V0.6 文档](LUNE_V06.md)，Claude Code 桥接及其独立运行要求见 [V0.11 文档](LUNE_V11_CONTINUITY.md)。Docker 镜像尚未安装 Claude CLI，也不会自动读取 Windows 的登录；不能因电脑已启动就标为全部账号已连通。

## 平时怎么用

- Windows 电脑开着并联网，Docker Desktop、Tailscale 在运行，iPhone 的 Tailscale 已连接，即可从 Wi-Fi 或移动网络访问私人聊天地址。网络质量仍需在本人设备实际验证。
- 电脑关闭、睡眠或断网时服务不可用。接电时可在 Windows 电源设置中选择合适的睡眠策略；启动器不擅自更改系统电源设置。
- 在 Docker Desktop 设置中开启「登录时启动」后，原来运行的容器通过 `unless-stopped` 在引擎恢复时自动启动；Tailscale Serve 使用 `--bg` 保存设置。Windows 尚未登录、磁盘故障或软件启动失败时不能保证自动恢复。
- 双击 **`Lune-Stop.cmd`** 暂停后台，保留数据库、模型和档案。主动停止后不会靠重启策略擅自恢复；下次双击 Start。
- 更新时保留 `.env` 和 `.lune-local`，把新源码覆盖到同一目录后双击 Start。固定 Compose 项目名 `lune-local` 避免目录改名后意外创建新数据卷；不要同时运行多个使用这个项目名的实例。

## 数据在哪里

持久卷名为 `lune-local_lune_data`，挂到容器 `/data`。SQLite、附件、模型设置、原版语料及 sidecar、人格、线程、便条、冷却、归档账本和模型缓存都在该卷。**删除项目文件夹不等于备份记忆**；不要在 Docker Desktop 删除此卷，也不要使用 `down -v`、volume prune 或恢复出厂设置清理它。

项目根目录 `.env` 保存连接密码；`.lune-local/access.txt` 保存可读的地址和密码。这些已从 Git 和 Docker 构建上下文排除。只在自己的电脑保存，不上传公开仓库或公开站点。运行 PowerShell 的 ExecutionPolicy Bypass 仅用于这一次脚本进程，不修改机器的永久策略。

原版 ZIP 备份只覆盖原生档案，完整恢复还需要 SQLite、附件、配置和密钥，见 [部署备份说明](LUNE_DEPLOY.md)。Tailscale 控制连接不提供记忆备份。正式日用前应完成一次完整私人卷备份与恢复演练。

## 本轮验证边界

- 新增 Windows 四个双击入口、密码初始化、就绪等待、稳定数据卷项目名、私人手机地址保存、Tailscale 已有配置保护。
- Linux PowerShell 7.6.8 的语法解析与合成配置执行测试覆盖密码不轮换、冲突不覆盖、端口拒绝注入、路径空格、私人连接信息、外部命令错误状态，以及拒绝公网 Funnel / 外来路由。代码按 Windows PowerShell 5.1 写法准备，5.1 真机执行仍待验证。
- 现有完整后端已通过 Linux 本地 HTTP、原版 Passive Recall、原生任务及重启持久恢复测试。
- 当前开发环境没有 Windows、Docker 引擎和已登录的 Tailscale，**未执行 Windows 安装、Docker 镜像构建、真实 Serve、iPhone Safari 或真实订阅账号验收**。首次在用户电脑启动时继续逐项验证。

## 官方参考

- [Docker Windows 安装和系统要求](https://docs.docker.com/desktop/setup/install/windows-install/)
- [Docker Desktop 个人用途免费](https://docs.docker.com/subscription-billing/desktop-license/)
- [Tailscale Personal 免费方案](https://tailscale.com/pricing)
- [Tailscale Serve 私人 HTTPS](https://tailscale.com/docs/features/tailscale-serve)
- [Windows 管理员终端与 Serve 示例](https://tailscale.com/docs/reference/examples/serve)
- [Serve 参数及后台持久运行](https://tailscale.com/docs/reference/tailscale-cli/serve)
