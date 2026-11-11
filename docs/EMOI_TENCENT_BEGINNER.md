# Émoi · 腾讯云轻量服务器部署｜新手照做版

> 更新至 2026-11-11 的 `main` 主分支。适用于 **已经有一台 Linux 腾讯云轻量服务器**、希望手机和电脑使用同一套私人 Émoi 的情况。Émoi 包括 PWA、relay、聊天、API loop、记忆和可选功能；**不是只部署一个静态网页**。代码 CI 容器通过，不等于目标服务器已经部署。
>
> 原来的 CyberBoss、Garden Bridge、Desire 和 Ombre Brain 应当保持原样，先验收 Émoi 自己能启动。不要重装系统、不要删除其他容器、不要抢占既有 80/443、**不要执行 `docker compose down -v`**。

## 最短路径：已有腾讯云 + XLC Gateway 的用户从这里开始

**适合已确认 Docker 正常、8088 空闲、服务器还有约 2 GB 可用 RAM 的现有机器。** 以下只建 Émoi 项目，不动 CyberBoss、电话、已有 OB、Desire、80/443 网关；轻量覆盖层关闭重复下载/安装四个本地记忆／心潮引擎。后续若要共用现有 OB，需要单独开发或配置有凭证的远程共享，不可宣称自动相通。

一次粘贴（Ubuntu SSH 终端）：

```bash
cd ~
if [ ! -d emoi-web/.git ]; then git clone --depth 1 --branch main https://github.com/liyanjun921/Tidal_Echo.git emoi-web; fi
cd emoi-web && git pull --ff-only && bash scripts/deploy_emoi_tencent_light.sh
```

脚本会检查 Docker/端口/磁盘/数据卷，随机生成只存在于机器上的 `.env` 密钥，配置固定的 `emoi` Compose 项目，启动轻量独立容器，自动轮询 `/readyz`，只读报告现有 XLC 网关配置挂载位置。如检测到已经存在的 `xlc-gateway_default` Docker 网络，自动通过独立 Compose 覆盖文件将 Émoi 加入网络并提供 `emoi-chat:8080` 内部服务名，不会修改现有 Caddy 路由。它**不开放公网、不更改网关、不迁移原 OB**；显示 `EMOI_READY=YES` 只代表本地基础网页/API 健康，不代表已能从手机访问或模型登录成功。

如果下一步要手机正式使用，需要在**既有** XLC Gateway 上新增一条 HTTPS 路由，把专用域名反代到 Émoi。此操作必须查看现有 Caddy 路由后才能安全进行，不能盲目新增占用 80/443 的网关。等路由完毕后，在手机 Safari 打开 HTTPS 网址、连接私人密钥并添加到主屏幕。

**注意：已进入轻量模式时，后续更新也要保持两个 Compose 文件：**

```bash
cd ~/emoi-web
git pull --ff-only
bash scripts/deploy_emoi_tencent_light.sh
```
这样脚本会自动保留已存在的 `.env` 和数据卷，且能继续加入现有 XLC 网络。不要只执行两份 Compose 文件而意外移除共享网关网络。

下面是更详细的人工分步教程，供检查/排错使用；新用户不需要重复运行两种部署方法。

## 0 · 登录腾讯云并只读检查（这一步不会改服务器）

腾讯云控制台 → 轻量应用服务器 → 找到已有实例 → 登录 / WebShell。假设是 Ubuntu/Debian Linux；如果是 Windows Server 或其他操作系统，不能照搬。

在服务器终端运行：

```bash
cat /etc/os-release | head -n 5
free -h
df -h
docker --version
docker compose version
sudo docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}'
sudo ss -ltnp
command -v git
command -v caddy
command -v nginx
```

检查**现有容器、反向代理、内存、硬盘和端口**。如果 `docker` 不存在，按 [腾讯云 Docker 官方教程](https://cloud.tencent.com/document/product/1207/45596) 和 [Docker Ubuntu 官方教程](https://docs.docker.com/engine/install/ubuntu/) 安装 Docker Engine + Compose 插件；**不要直接对已有服务器运行来源不明的一键安装脚本**。如果 `git` 不存在，在确认系统为 Ubuntu/Debian 后 `sudo apt-get update && sudo apt-get install -y git`。Docker 安装可能影响已有服务，先看上述检查结果。

## 1 · 克隆 Émoi 正式版

只有确认目标目录尚不存在、硬盘足够、`8088` 未被占用、没有既有 `emoi` 同名容器及卷后再做：

```bash
cd ~
git clone --depth 1 --branch main https://github.com/liyanjun921/Tidal_Echo.git emoi-web
cd emoi-web
```

此时 **没有启动任何新服务**。不需要将家里 Windows 上的记忆目录或私人密钥上传 GitHub。

## 2 · 创建私人连接密钥和端口

`8088` **只是演示**，先用 `sudo ss -ltnp` 确认它没被占用。以下用 Python 在服务器本机随机生成一次性长密钥，不在终端输出，也不进入 GitHub：

```bash
cd ~/emoi-web
umask 077
python3 - <<'PY'
from pathlib import Path
import secrets
path = Path(".env")
if path.exists():
    raise SystemExit("发现 .env，停止：不要覆盖已有密钥")
path.write_text("RELAY_SECRET=" + secrets.token_hex(32) + "\nEMOI_PORT=8088\n")
path.chmod(0o600)
print("已生成私有 .env；请勿将其内容发送给他人")
PY
```

**连接密钥的位置**：`~/emoi-web/.env` 的 `RELAY_SECRET` 值。日后在自己的 HTTPS Émoi 设置里填写它。它能访问你们的私人记录，**不要截图、粘贴到聊天、提交仓库或发给部署助手**。

现有配置在 `compose.emoi.yaml`，容器内部服务为 `8080`，宿主机绑定 `127.0.0.1:8088`，不会把数据库或内网服务直接暴露给公网。

## 3 · 正式启动（不会自动改已有 CyberBoss 等配置）

```bash
cd ~/emoi-web
sudo docker compose -p emoi -f compose.emoi.yaml config --quiet
sudo docker compose -p emoi -f compose.emoi.yaml up -d --build
sudo docker compose -p emoi -f compose.emoi.yaml ps
curl -i http://127.0.0.1:8088/readyz
```

`/readyz` 返回 HTTP 200 和 `{"ok":true}` 才算后端基础健康检查通过；首次启动会尝试下载固定版本的 Latent、Ombre、Folio、心潮源码、BGE 向量模型和 tokenizer，取决于网络与剩余资源，**不是每台 4GB 主机都能同时跑全部后台模块**。刚启动的 `503` 可能是初始化未完成，也可能是失败，需要读日志判断，不能直接说已成功。

只读检查日志与资源：

```bash
sudo docker compose -p emoi -f compose.emoi.yaml logs --tail=70 emoi
sudo docker stats --no-stream
free -h
```

不要把包含 token、私密文本或云 IP 的原始日志公开贴出。若端口、内存、目录或容器名称与现有服务冲突，**停止当前部署流程**，不要停删其他服务来腾位置。

## 4 · 电脑先预览新版 Émoi（不需要域名）

在 **自己 Windows 电脑的 PowerShell** 运行（替换为你的实际 SSH 用户和公网 IP，终端里的服务器命令不要混着执行）：

```powershell
ssh -L 18088:127.0.0.1:8088 ubuntu@你的腾讯云公网IP
```

保持该 SSH 窗口连接，然后在**同一台 Windows 电脑浏览器**打开：

```text
http://localhost:18088
```

这条临时 SSH 隧道仅供自己的电脑验收 UI；它不等于手机远程访问地址。若 SSH 用户不是 `ubuntu`、认证方式不同，请以腾讯云实例实际设置为准。

## 5 · 手机稳定访问（必须有 HTTPS，优先复用已存在的网关）

Émoi 还没有自动给用户买域名、签 SSL 证书或配置腾讯云防火墙。要让 iPhone 在任意网络打开，建议任选以下其一：

**A. 已有自己的 HTTPS 域名／已有 Nginx、Caddy、XLC Gateway**：在**现有**反向代理中新增一个域名（例如自己拥有的 `chat.example.com`）并将网站**整个路径**反代到 `http://127.0.0.1:8088`。不要改写其他站点的配置；保留 WebSocket/SSE 所需的流式代理、视频 Range 请求、长连接超时、上传大小，禁止代理缓存敏感 API。若 Caddy 专门负责该域名，最小配置块是：

```caddyfile
chat.example.com {
    reverse_proxy 127.0.0.1:8088
}
```

域名 DNS 必须指向服务器、80/443 端口由 HTTPS 服务使用。若目标轻量机位于**中国内地**，请先核对 ICP 备案规则，不能绕过备案发布公网网站。[腾讯云 ICP 指南](https://cloud.tencent.com/document/product/1207/45756)。若 `80/443` 已被已有网关使用，不要再安装一套会抢占端口的 Caddy。

**B. 只自己访问、不想公开公网网站／暂时没域名**：可考虑私人 VPN / Tailscale Serve，通过 tailnet 的 HTTPS 地址访问。需要在服务器和手机上分别安装并授权 Tailscale；按其[官方 Serve 教程](https://tailscale.com/docs/features/tailscale-serve)配置 `http://127.0.0.1:8088`，不要使用公开 Funnel 模式。其自带 HTTPS 证书和访问控制，但手机需正确连接对应 tailnet；是否可用取决于服务器及手机的实际网络。不要在已有 Tailscale Serve 上盲目覆盖现有映射。

**不推荐**直接开放 `8088` 或通过 `http://公网IP:8088` 使用私人聊天，当前 Compose 本身也没有对外发布该端口。

## 6 · iPhone 添加 Émoi 到主屏幕

1. iPhone Safari 打开自己配置好的 **HTTPS URL**，验证网站出现 Émoi 而不是旧 Luné。
2. 右上角图片图标 → 为当前聊天单独换壁纸；记忆、共读等功能页可分别换。上传图片仅存到当前设备浏览器。
3. 点击菜单 → 设置／连接与模型设置，填写**自己的** `RELAY_SECRET`，确认出现连接成功。
4. 在模型设置里为 GPT 或 Claude 配置实际可用的模型 API，测试发送及回复。ChatGPT 订阅授权需要额外的官方 OAuth 连接助手，不能把 ChatGPT Plus 订阅当作自动可用的 API Key；[Émoi 订阅登录教程](EMOI_V06.md)。Claude 订阅接口仍有保留／前提条件，未声明已实机连通。
5. 在 Safari 的分享菜单选择 **添加到主屏幕**，以独立 PWA 打开；再次检查壁纸、消息、收发、附件和后台恢复。通知需另行授权、配置并在 iOS 真机验证。

## 7 · 关于 Ombre Brain、Garden、CyberBoss

**Émoi 默认 Docker 会启动一个新的四空间 Ombre vault**；它不是以前 Windows 或腾讯云上的那份 OB。两份记忆**不会自动互通**。在旧 OB 做一致性备份并确定单一权威实例之前，不要盲目复制、删除或合并存储目录。

Garden：现有 `scripts/emoi_ingest_event.py` 能将规范唤醒事件写入 Émoi，但真正的 SSE 连接与论坛权限需在 Garden Bridge 端单独验收；保留原版 `Restart=no` 和**不自动重连**约束。CyberBoss：现有脚本可接收规范化事件，但微信双向回复通道还需开发/实际验收。详细见 [云端集成验收文档](EMOI_TENCENT_CLOUD.md)。

## 8 · 更新、关闭与备份

部署目录固定在 `~/emoi-web`，Compose 项目固定为 `emoi`；更新前先备份数据卷和 `.env`，检查远端变更与数据迁移指南，再使用：

```bash
cd ~/emoi-web
git pull --ff-only
sudo docker compose -p emoi -f compose.emoi.yaml up -d --build
```

关闭或重启**仅 Émoi**（不会触及别的 Compose 项目）：

```bash
sudo docker compose -p emoi -f compose.emoi.yaml stop
sudo docker compose -p emoi -f compose.emoi.yaml start
```

**绝不执行** `docker compose down -v`、`docker volume prune` 或在缺少快照时手动删 `emoi_emoi_data`。数据卷默认持有聊天、附件、四空间记忆、模型缓存及影院素材。仅备份 `emoi.db` 不等于完整备份；完整卷、`.env`、外部网关和已有 OB 的密钥／数据需分开保护，且备份应离开服务器保存。

**当前最安全的开始方式：先做第 0 步，把系统版本、Docker、内存、磁盘和端口占用结果（隐藏 IP／令牌）拿来确认，再决定新服务到底用哪个空闲端口。**
