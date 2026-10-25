# Luné 一起看电影

基于用户 fork `liyanjun921/open-watch-cinema` 的 `6154eec6ef8f8d2a1831169b2f54952ccab71bea`，保留 MIT 许可证及原源码。影院进程沿原设计只监听 `127.0.0.1`；Luné 通过现有 Bearer 密钥代理请求、分片导入与 Range 播放，手机只访问自己的 HTTPS Luné 入口。原版源文件的唯一兼容修改是观影消息 `nonce` 去重，避免模型投递重试造成双条消息。

## 使用

侧边栏「一起看电影」里导入自己的 MP4、M4V、WebM、MOV 或 MKV，或将影片放入运行端的 `LUNE_CINEMA_DATA/media` 后点「重新扫描」。先试播画面和声音，再点「标记就绪」与「开启新场次」。影片、SQLite、提取字幕和 AI 包保存在运行端的私人持久目录；网页本机选的 SRT/VTT 只显示在当前设备，不自动交给 AI。

想让 GPT 或 Claude 共看，先点影片卡片的「准备 AI 观影」，选择影院已发现的对白字幕轨（也可以只准备视觉资料），等待处理完成，再在活动房间勾选要邀请的模型。后台按原版游标读取已播放的对白、用户消息、运动事件和选中的 storyboard；拿到实际 JPEG 才会把画面传给支持视觉的模型。每个模型保存独立游标，按需回应或保持沉默；模型回复落在原版房间消息流，并按影片时间展示。关房后可从「往日场次」只读回放消息与弹幕。修复播放采用原版的症状选择与 FFmpeg 处理，成功后仍要重新试播。

一场只有一个活动房间。当前版本是一位观众与多个 AI 的共看，没有多设备观众同步播放；同一人从另一设备打开页面，播放位置不会自动强制追随。观影房间与影片不进入普通聊天 JSON 导出，完整备份须包括 `LUNE_CINEMA_DATA`。影片不上传到外部片库；导入时由浏览器通过自己鉴权的 Luné 服务传送到自己的运行端，模型调用会收到经过播放头门禁的文字和所选画面。请只导入自己有权保存和播放的影片。

## 运行条件

`Dockerfile.lune` 内含 Node 24、FFmpeg、Python 3 和 OpenCV headless，用户的手机或电脑网页不必安装 Node。`scripts/run_lune.py` 启动原版 Node 服务，默认本机 4182 端口，不向公网开放；`LUNE_CINEMA_PORT` 可以调整内部端口。影片和房间默认放在 `RELAY_DB` 所在目录的 `cinema/`（容器内一般是 `/data/cinema`），也可指定 `LUNE_CINEMA_DATA`。部署时只开放原有 Luné HTTPS 入口；视频 Range 请求与分片上传都经过原有密钥鉴权，反代须允许至少 4 MB 请求体，并关闭包含 token 的 URL 查询字符串访问日志。

原项目的本地 MCP 服务与 `mcp/SKILL.md` 保留在 vendored 源码中。Luné 的共看后台直接用原版 `ai-tick`／`ai-frame` 接到已经配置的房间模型；普通聊天工具列表不会自动添加有结束房间权限的 MCP 工具。视觉模型不支持图片时，可以只依赖对白；视觉包没有 storyboard 时不会声称模型实际看到了画面。

## 验证

`tests/cinema_flow.py` 在隔离目录启动原版 Node 服务，生成短片，检查鉴权、分片、Range、消息去重、观影包、模型访客游标和归档只读。`tests/cinema_http_flow.py` 通过整个 supervisor 和合成模型服务验证真实端到端共看。原项目测试保留；其中 OpenCV 测试需先安装 `observer/requirements.txt`。
