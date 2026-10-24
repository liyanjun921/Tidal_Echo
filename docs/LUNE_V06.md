# Luné V0.6 · 订阅连接

GPT 新增 `chatgpt_plan` 模式，Claude 新增 `claude_subscription` 预留模式。原有 API / 中转站配置保留，模式独立；订阅模式不会因缺少授权、额度不足或供应商错误而自动调用保存的 API Key。

## ChatGPT 已实现部分

- 官方 OSS OAuth + PKCE：动态注册、稳定主机 ID、一次性 state/nonce、ID token 签名/issuer/audience/时效校验，返回账户身份必须匹配选定注册。
- 多账户/工作区注册分开保存、选定账户、重新授权、序列化刷新旋转令牌、退出连接和远程撤销结果提示。
- 用同一账户的授权读取可用模型目录；不硬编码“订阅一定可用”的模型，不根据目录假报请求成功。
- Responses 流式适配：`store:false`、`stream:true`、逐轮传入原文历史和图片；说明转换为 instructions，本机 MCP/生活页工具放入 namespace；工具结果及推理延续所需的输出项在本轮继续传回。只有完成事件才算成功，断流和用量错误独立处理。
- 手机设置：API / 订阅切换、账户状态、读取模型、保存、测试、连接助手下载、私人连接文件导入、退出与用量入口。
- 私人令牌只保存在运行端文件；不进入网页存储、聊天 JSON 备份或 Git。模型附件工具也拒绝发送订阅连接文件。

实际账户授权、模型权限与套餐用量仍待用户在正式服务上验证。本次没有登录真实账户，也没有请求真实模型。

## 首次连接

当前官方 OSS 流程要求 `http://127.0.0.1:<port>/auth/callback`。因此在 iPhone 上打开远程服务器时，不能把这个地址当成服务器回调。

本机运行服务时：在同一台电脑上通过本地地址打开 Luné，连接服务后，设置 GPT 为“ChatGPT 订阅额度”，打开“查看订阅连接”，点 Continue with ChatGPT，再点出现的官方授权链接。授权后刷新状态和可用模型，选模型并保存。

远程私人服务器时：下载连接助手，电脑需 Python 3.10+ 和浏览器。Windows 解压后双击 `start-windows.cmd`；它在独立虚拟环境安装 `httpx` 与 `PyJWT[crypto]`，再运行官方登录。其他系统：

```sh
python -m pip install -r requirements.txt
python chatgpt_login.py --export ~/.lune/lune-chatgpt-connection.json
```

登录成功后，把生成的文件仅导入自己的 HTTPS Luné 服务器。助手导出后清除电脑端活动令牌，服务器接管后续刷新；不要把连接文件发给聊天、仓库、第三方中转站或他人。导入需校验身份和时效，过期则重新运行助手。完成后仍可在 iPhone 使用前端，无需让手机运行 Python。

已在服务器本地完成授权的部署也可直接运行仓库里的助手，设置 `--store` 为服务器的私人连接路径，不使用 `--export`：

```sh
python scripts/chatgpt_login.py --store /data/lune-private/chatgpt-plan.json
```

这条命令仍需同机浏览器或正确配置的本地回调转发，纯远程无浏览器终端应采用前述电脑助手。私人目录默认位于 `LOOP_CONFIG` 同级的 `lune-private/`；可用 `CHATGPT_PLAN_FILE` 显式指定文件。备份该目录时按凭据保护；聊天导出不包含它。首次登录需用户亲自审阅 OpenAI 的授权和套餐权限，不应把“已添加代码”视为“账户已经接通”。

## Claude 预留接口

设置值：`connection_mode=claude_subscription`；状态接口：`GET /relay/app/loop/subscriptions` 中的 `claude`；预留 transport：`claude_code_interactive`。当前 `ready:false`。选中该模式会保存配置，但生成或测试返回清楚的未连接提示，API 请求次数为零。

方向是用户自己的未修改 Claude Code 交互进程，tmux 负责常驻，官方 hooks 负责结构化事件，Luné 负责手机界面与原文保存。参考了用户提供的终端接前端教程的运行架构，未复制其源码、配置其机器或采集任何 Claude 登录凭据。

后续桥接必须独立处理：每房间会话隔离、消息粘贴、回合 ID、流式帧排序去重、回合结束/失败、取消确认、工具权限和进程重启恢复。预期接入合同如下，尚未声称实现或验证 Claude 运行时：

| 动作 | 预留语义 |
| --- | --- |
| status | runtime/version/room session/ready/busy；不能仅凭进程存在就宣称已登录 |
| turn | run_id、room、用户原文、允许范围内的记忆/附件；每房间串行 |
| events | reply_delta、reply_completed、tool/permission、failed；带回合和帧编号 |
| stop | 请求中断并确认官方进程已停止当前回合；未确认则告知用户 |

Claude 登录必须在官方 Claude Code 流程完成，Luné 不提供第三方 Claude.ai 登录或订阅令牌表单。是否及如何使用官方进程需遵守当时 Anthropic 的适用规则；教程中“始终走订阅”的表述不构成本项目的计费保证。

## 验证

36 项 Python 测试通过，其中新增 13 项覆盖真实签名的合成 ID token、PKCE/state/nonce/回调防重放、返回注册身份、无套餐权限、跨线程刷新、导入与主机 ID、退出撤销失败、Responses 历史/图片/工具协议、终态/用量错误、账户模型目录、取消、API 不回退和助手 ZIP 无凭据。

既有隔离 HTTP 联调继续验证私聊、群聊、附件、MCP、持久待办与双服务朗读。订阅推理使用 HTTP MockTransport 与合成身份测试，不能替代真实订阅账户验收。浏览器检查设置切换、订阅说明与预览禁止真实授权。

```sh
python -m unittest tests.test_lune tests.test_speech tests.test_subscription -v
python tests/run_e2e.py --http-only
```

## 官方依据（核对日期 2026-10-24）

- https://developers.openai.com/siwc/token-sharing-open-source/sign-in
- https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms
- https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
- https://code.claude.com/docs/en/legal-and-compliance
