# Luné / OURSPACE V0.5

本版按用户确认的方向重做：Echo 和 fang-claude 的代码组织、功能及 UI 是参考主体；V0.3 只保留灰白蓝、水光背景与液态玻璃材质。旧首页、常驻侧栏和底部导航不再作为主界面。

## 来源与实现

| 来源 | 核对版本 | 本版采用方式 |
| --- | --- | --- |
| Tidal Echo，用户 fork `liyanjun921/Tidal_Echo` | 上游基线 `860e5de364de292093dba5571ee6427cdbda060e` | 复用 FastAPI relay、SQLite、SSE、附件、API loop、MCP、MiniMax、通知与 PWA 底座；保留 AGPL-3.0 和 NOTICE。原网页保留在 `web/tidal-original/`。 |
| fang-claude / dwell，用户 fork `liyanjun921/fang-claude` | `1ad2d6af73ee02ba823c85b974fd23e4d7584f4b` | 阅读前端、README 与功能文档，独立实现抽屉、分层弹页、双行输入区及生活页模型。该仓库采用 PolyForm Noncommercial 1.0.0；本版未复制其 HTML、CSS、JS 或 SVG，也未将其源码改标 AGPL。 |
| 用户 Luné V0.3 | 2026-10-23 交接 | 保留配色、背景素材、玻璃材质及旧本机数据兼容读取。 |

## 实际状态

| 部分 | 已实现 | 仍待接入或验收 |
| --- | --- | --- |
| 聊天 | Echo 宽度主屏；左抽屉、右菜单；双行输入；GPT / Claude / 群聊；流式回复、工具卡、安全富文本、SQL 原文搜索、停止及离线核对重试 | 真机 Safari 键盘、真实模型中转站与网络中断 |
| 设置 | 两个模型独立接口、模型 ID、密钥与可空说明；历史/图片/工具预算；MCP 状态、Authorization、重连/移除 | 特定第三方 MCP 服务、供应商用量 |
| 记忆 | 服务端版本检查、原文出处、共享/私聊/群聊范围；编辑与备份 | 跨设备在同一已部署服务器上验收；自动记忆提取未启用 |
| 待办 / 日历 | 我的与模型清单分开；完成状态、日期时间排序；月历圆点、当天详情、心情、重要日子、每年重复 | 系统闹钟、外部日历同步未接入 |
| 日记 / 悄悄话 | 时间线、便签墙、用户/AI 日记；按范围保存悄悄话，下轮对话投影，不单独触发回复 | 夜间心跳与自动日记调度未启用 |
| 共读 | TXT / Markdown（1 MB 内），书架、阅读进度、段落/引文批注、带回聊天；书籍改范围或删除时批注同步处理 | EPUB / PDF 排版阅读器未实现；聊天附件 PDF 提取沿用后端 |
| 日报 / 健康 | 手动记录、编辑、持久保存；模型按明确请求保存日报 | 定时新闻抓取、Apple Health 未接入 |
| 模型生活页工具 | `lune_workspace` 按当前房间限制读写，停止后拒绝写入；列表最多 10 条，正文超过 4000 字符标记截断 | 不声称后台自动行动；长书不能仅凭列表假装读完 |
| 朗读 / 推送 / PWA | 复用 MiniMax、Web Push 和 SW；新版缓存包含富文本文件 | 真实语音账户、HTTPS 主屏通知、锁屏送达和 iPhone 安装 |
| 数据 | 本机 localStorage / 壁纸 IndexedDB；连接后 SQLite；版本冲突保护；JSON 备份含生活页、批注与书籍 ID 重映射 | JSON 不包含附件二进制，完整备份还需 uploads 和私人配置 |

## 验证

本次通过 18 项 Python 回归测试，覆盖鉴权、记忆投影、原文分页、发送去重/取消、群聊顺序、密钥脱敏、生活页版本冲突、范围限制、书籍批注联动、备份重映射与失败回滚、悄悄话隔离及历史搜索。所有新 JavaScript 语法检查及 Python 编译检查通过。

真实 HTTP 联调以隔离 SQLite、合成 OpenAI/Anthropic 服务与测试 MCP 运行：私聊 → 群聊 → 文本附件 → MCP → 模型工具创建持久待办 → 导出确认。没有使用真实供应商密钥或产生模型费用。

浏览器由 Work 的浏览器工具检查：桌面聊天/抽屉、切房间、待办新建/勾选/刷新保存、共读返回聊天、日历和设置；390px 和 320px iframe 用于响应式布局检查，不等同于 iPhone Safari 真机测试。`tests/browser.cjs` 已随新选择器更新，本轮未运行独立 Playwright 浏览器；HTTP 联调独立通过。

```sh
python -m unittest tests.test_lune -v
python tests/run_e2e.py --http-only
# 在支持独立 Playwright 的普通开发环境可运行旧全流程浏览器入口：
python tests/run_e2e.py
```

私人预览使用单独的示例数据种子，并禁止模型配置提交及 API 请求；其内容有“界面示例”标记。生活页本机编辑可用，不能将示例回复视为真实模型执行记录。
