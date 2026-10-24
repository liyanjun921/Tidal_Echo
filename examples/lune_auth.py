"""Official Sign in with ChatGPT, protected profiles and rotating refresh tokens.

No API keys, browser cookies or ChatGPT private endpoints are used here.
OAuth callbacks are loopback-only, per the public OSS registration contract.
"""
import base64
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
JWKS = ISSUER + "/.well-known/jwks.json"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
_process_lock = threading.RLock()
_keys = {"until": 0, "keys": []}
_attempts = {}


class PlanError(Exception):
    def __init__(self, status, message, code="plan_error"):
        self.status, self.message, self.code = status, message, code
        super().__init__(message)


def path_default():
    config = Path(os.environ.get("LOOP_CONFIG", str(Path(__file__).parent / "api_loop.config.json")))
    return Path(os.environ.get("CHATGPT_PLAN_FILE", str(config.parent / "lune-private" / "chatgpt-plan.json")))


def verify_identity(token, client_id, nonce=None):
    """Verify signature, fixed issuer, audience, expiry and authorization nonce."""
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        if alg not in {"RS256", "ES256"} or not header.get("kid"):
            raise ValueError()
        if time.time() >= _keys["until"] or not any(k.get("kid") == header["kid"] for k in _keys["keys"]):
            with httpx.Client(timeout=20, trust_env=True) as client:
                response = client.get(JWKS)
                response.raise_for_status()
                keys = response.json()["keys"]
            _keys.update(keys=keys[:30], until=time.time() + 300)
        jwk = next(k for k in _keys["keys"] if k.get("kid") == header["kid"])
        key = jwt.PyJWK.from_dict(jwk, algorithm=alg).key
        claims = jwt.decode(token, key, algorithms=[alg], issuer=ISSUER, audience=client_id, leeway=5, options={"require": ["iss", "aud", "sub", "exp", "iat"]})
        if not isinstance(claims["sub"], str) or not claims["sub"] or nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise ValueError()
        return claims
    except Exception:
        raise PlanError(401, "ChatGPT 登录身份校验未通过，请重新授权", "identity_invalid") from None


def token_request(body):
    try:
        with httpx.Client(timeout=30, trust_env=True) as client:
            response = client.post(TOKEN, data=body)
        if response.status_code >= 300:
            code = response.json().get("error", "")
            raise PlanError(401 if code == "invalid_grant" else 503, "ChatGPT 授权已失效，请重新登录" if code == "invalid_grant" else "ChatGPT 授权服务暂不可用，请稍后重试", "reauth_required" if code == "invalid_grant" else "token_unavailable")
        return response.json()
    except PlanError:
        raise
    except Exception:
        raise PlanError(503, "暂时无法连接 ChatGPT 授权服务", "token_unavailable") from None


class PlanStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else path_default()

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # OS lock serializes rotating refresh tokens across CLI and loop workers.
        with _process_lock, open(self.path.with_suffix(".lock"), "a+b") as handle:
            try:
                import fcntl
            except ImportError:  # Windows login helper: one process, local RLock.
                fcntl = None
            if fcntl:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def read(self):
        if not self.path.exists():
            return {"format": "lune-chatgpt-plan-v1", "host_id": "", "active": "", "accounts": {}}
        try:
            return json.loads(self.path.read_text())
        except Exception:
            raise PlanError(503, "订阅连接资料无法读取，请检查私人配置备份", "store_invalid") from None

    def write(self, value):
        temp = self.path.with_name(self.path.name + "." + secrets.token_hex(8) + ".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
            os.chmod(self.path, 0o600)
        finally:
            temp.unlink(missing_ok=True)

    def status(self):
        with self.locked():
            data = self.read()
        accounts = [{"id": key, "email": row.get("email", ""), "label": row.get("label") or row.get("email") or key[:10], "sharing": PLAN_SCOPE in row.get("scopes", []) and bool(row.get("access_token")), "needs_login": not bool(row.get("access_token")), "expires_at": row.get("expires_at", 0)} for key, row in data["accounts"].items()]
        active = next((a for a in accounts if a["id"] == data["active"]), None)
        return {"accounts": accounts, "active": data["active"], "ready": bool(active and active["sharing"]), "usage_url": "https://chatgpt.com/#settings/Usage", "last_attempt": dict(_attempts.get(str(self.path), {}))}

    def select(self, account_id):
        with self.locked():
            data = self.read()
            if account_id not in data["accounts"]:
                raise PlanError(404, "请选择已连接的 ChatGPT 账户")
            data["active"] = account_id
            self.write(data)
        return self.status()

    def begin(self, redirect_uri, account_id=None):
        uri = urlsplit(redirect_uri)
        if uri.scheme != "http" or uri.hostname != "127.0.0.1" or uri.path != "/auth/callback" or not uri.port or uri.query or uri.fragment:
            raise PlanError(422, "订阅授权必须使用本机 127.0.0.1 回调")
        with self.locked():
            data = self.read()
            if not data["host_id"]:
                data["host_id"] = "urn:uuid:" + str(uuid.uuid4())
                self.write(data)
            old = data["accounts"].get(account_id) if account_id else None
            if account_id and not old:
                raise PlanError(404, "该 ChatGPT 账户不存在")
        state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        client_id = old["client_id"] if old else "dynamic_agent_client"
        query = {"client_id": client_id, "ext_agent_host_id": data["host_id"], "response_type": "code", "redirect_uri": redirect_uri, "scope": SCOPES, "resource": RESOURCE, "state": state, "nonce": nonce, "code_challenge_method": "S256", "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}
        if old:
            if old.get("id_token"):
                query["id_token_hint"] = old["id_token"]
            if old.get("email"):
                query["login_hint"] = old["email"]
        else:
            query["agent_name_hint"] = "Luné / OURSPACE"
        return {"url": AUTHORIZE + "?" + urlencode(query), "state": state, "nonce": nonce, "verifier": verifier, "redirect_uri": redirect_uri, "client_id": client_id, "account_id": account_id, "subject": old.get("subject") if old else None, "created": time.time(), "used": False}

    def finish(self, pending, params):
        if pending["used"] or time.time() - pending["created"] > 600 or not hmac.compare_digest(str(params.get("state", "")), pending["state"]):
            raise PlanError(400, "登录回调已过期或校验不匹配", "state_invalid")
        pending["used"] = True
        if params.get("error"):
            raise PlanError(403, "已取消 ChatGPT 授权", "access_denied")
        client_id = params.get("client_id") or pending["client_id"]
        if not isinstance(client_id, str) or client_id == "dynamic_agent_client" or pending["client_id"] != "dynamic_agent_client" and client_id != pending["client_id"] or not params.get("code"):
            raise PlanError(400, "ChatGPT 客户端注册未完成", "client_invalid")
        tokens = token_request({"grant_type": "authorization_code", "client_id": client_id, "code": params["code"], "code_verifier": pending["verifier"], "redirect_uri": pending["redirect_uri"], "resource": RESOURCE})
        identity = verify_identity(tokens.get("id_token", ""), client_id, pending["nonce"])
        if pending["subject"] and identity["sub"] != pending["subject"]:
            raise PlanError(401, "返回的账户与选定账户不一致", "account_mismatch")
        return self.save_session(client_id, identity, tokens)

    def save_session(self, client_id, identity, tokens):
        if tokens.get("token_type", "Bearer").lower() != "bearer" or not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]:
            raise PlanError(401, "ChatGPT 未返回有效授权", "token_invalid")
        expires = tokens.get("expires_in", 3600)
        if not isinstance(expires, (float, int)) or not math.isfinite(expires) or not 0 < expires <= 86400:
            raise PlanError(401, "ChatGPT 授权时效无效", "token_invalid")
        key = hashlib.sha256((client_id + "|" + identity["iss"] + "|" + identity["sub"]).encode()).hexdigest()[:24]
        row = {"client_id": client_id, "issuer": identity["iss"], "subject": identity["sub"], "email": identity.get("email", ""), "label": identity.get("email", "") + " · " + client_id[-6:], "access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token", ""), "id_token": tokens.get("id_token", ""), "scopes": str(tokens.get("scope", "")).split(), "expires_at": time.time() + expires, "saved_at": time.time()}
        with self.locked():
            data = self.read()
            if not data["host_id"]:
                data["host_id"] = "urn:uuid:" + str(uuid.uuid4())
            data["accounts"][key] = row
            data["active"] = key
            self.write(data)
        return self.status()

    def import_session(self, body):
        if not isinstance(body, dict) or body.get("format") != "lune-chatgpt-session-v1":
            raise PlanError(422, "请选择连接助手生成的订阅连接文件")
        row = body.get("session", {})
        if not isinstance(row, dict) or not isinstance(row.get("client_id"), str) or row["client_id"] == "dynamic_agent_client":
            raise PlanError(422, "订阅连接文件不完整")
        for key in ("access_token", "refresh_token", "id_token"):
            if not isinstance(row.get(key), str) or not row[key] or len(row[key]) > 20000:
                raise PlanError(422, "订阅连接文件不完整")
        scopes = row.get("scopes", [])
        expiry = row.get("expires_at", 0)
        if not isinstance(scopes, list) or any(not isinstance(s, str) for s in scopes) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= time.time():
            raise PlanError(422, "订阅连接文件已到期或权限格式不正确，请重新运行连接助手")
        identity = verify_identity(row["id_token"], row["client_id"])
        if identity["sub"] != row.get("subject") or identity["iss"] != row.get("issuer"):
            raise PlanError(401, "订阅连接文件的身份不匹配")
        return self.save_session(row["client_id"], identity, {**row, "scope": " ".join(scopes), "expires_in": min(3600, expiry - time.time())})

    def access(self):
        with self.locked():
            data = self.read()
            row = data["accounts"].get(data["active"])
            if not row or not row.get("access_token"):
                raise PlanError(401, "ChatGPT 订阅尚未连接，请先完成官方登录", "login_required")
            if PLAN_SCOPE not in row.get("scopes", []):
                raise PlanError(403, "已登录，但没有授权使用 ChatGPT 套餐，请重新授权", "sharing_disabled")
            if row.get("expires_at", 0) <= time.time() + 60:
                if not row.get("refresh_token"):
                    raise PlanError(401, "ChatGPT 授权到期，请重新登录", "reauth_required")
                try:
                    tokens = token_request({"grant_type": "refresh_token", "client_id": row["client_id"], "refresh_token": row["refresh_token"], "resource": RESOURCE})
                except PlanError as e:
                    if e.code == "reauth_required":
                        for key in ("access_token", "refresh_token", "id_token"):
                            row[key] = ""
                        self.write(data)
                    raise
                if not tokens.get("access_token"):
                    raise PlanError(503, "ChatGPT 授权刷新未完成", "token_invalid")
                expires = tokens.get("expires_in", 3600)
                if not isinstance(expires, (int, float)) or not math.isfinite(expires) or not 0 < expires <= 86400 or tokens.get("token_type", "Bearer").lower() != "bearer":
                    raise PlanError(503, "ChatGPT 授权刷新格式不正确", "token_invalid")
                if tokens.get("id_token"):
                    identity = verify_identity(tokens["id_token"], row["client_id"])
                    if identity["sub"] != row["subject"]:
                        raise PlanError(401, "刷新的登录身份不匹配", "account_mismatch")
                row.update(access_token=tokens["access_token"], refresh_token=tokens.get("refresh_token", row["refresh_token"]), id_token=tokens.get("id_token", row["id_token"]), scopes=str(tokens["scope"]).split() if "scope" in tokens else row["scopes"], expires_at=time.time() + expires)
                self.write(data)
                if PLAN_SCOPE not in row["scopes"]:
                    raise PlanError(403, "ChatGPT 套餐使用权限已取消", "sharing_disabled")
            return {"access_token": row["access_token"], "account_id": data["active"]}

    def sign_out(self, account_id):
        confirmed = False
        with self.locked():
            data = self.read()
            row = data["accounts"].get(account_id)
            if not row:
                raise PlanError(404, "该订阅账户不存在")
            try:
                with httpx.Client(timeout=15, trust_env=True) as client:
                    discovery = client.get(ISSUER + "/.well-known/openid-configuration").json()
                    endpoint = discovery.get("revocation_endpoint", "")
                    uri = urlsplit(endpoint)
                    if uri.scheme == "https" and uri.hostname == "auth.openai.com" and not uri.username and not uri.query:
                        response = client.post(endpoint, data={"token": row.get("refresh_token", ""), "token_type_hint": "refresh_token", "client_id": row["client_id"]})
                        confirmed = response.status_code == 200
            except Exception:
                pass
            for key in ("access_token", "refresh_token", "id_token"):
                row[key] = ""
            self.write(data)
        return {"ok": True, "revoked": confirmed, "message": "已退出订阅连接" if confirmed else "已清除本机授权；远程撤销未确认，可在 ChatGPT 设置中断开此应用"}


def start_login(store, account_id=None, port=0):
    """Start a bounded loopback listener. Never log callbacks or authorization URLs."""
    attempt = {"state": "pending", "message": "等待在运行服务的电脑上完成登录"}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.headers.get("Host") != "127.0.0.1:" + str(server.server_port) or urlsplit(self.path).path != "/auth/callback":
                self.send_error(404)
                return
            values = parse_qs(urlsplit(self.path).query)
            params = {key: value[0] for key, value in values.items() if len(value) == 1}
            try:
                store.finish(pending, params)
                attempt.update(state="completed", message="订阅登录已完成，请返回 Luné 刷新状态")
                status = 200
            except PlanError as e:
                status = e.status
                if e.code != "state_invalid":
                    attempt.update(state="failed", message=e.message)
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(("<!doctype html><meta charset=utf-8><title>Luné</title><p>" + ("登录已完成，可以关闭此页并返回 Luné。" if status == 200 else "登录未完成，请返回 Luné 重新尝试。") + "</p>").encode())

    previous = _attempts.get(str(store.path), {})
    if previous.get("state") == "pending":
        raise PlanError(409, "已有登录正在等待，请完成或等待它过期")
    server = ThreadingHTTPServer(("127.0.0.1", port), Callback)
    server.timeout = 1
    try:
        pending = store.begin(f"http://127.0.0.1:{server.server_port}/auth/callback", account_id)
    except Exception:
        server.server_close()
        raise
    _attempts[str(store.path)] = attempt
    def listen():
        try:
            while attempt["state"] == "pending" and time.time() - pending["created"] < 600:
                server.handle_request()
            if attempt["state"] == "pending":
                attempt.update(state="expired", message="登录已过期，请重新开始")
        finally:
            server.server_close()
    threading.Thread(target=listen, daemon=True).start()
    return {"authorization_url": pending["url"], "expires_in": 600, "loopback_host": "127.0.0.1", "message": "请在运行服务的同一台电脑上打开链接；iPhone 连接远程服务器时应使用电脑连接助手"}
