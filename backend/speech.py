"""Owner-only, server-held speech settings and ElevenLabs MP3 adapter."""
import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

from fastapi import HTTPException, Request


def defaults():
    return {"provider": os.environ.get("LUNE_TTS_PROVIDER", "minimax"), "providers": {
        "minimax": {"key": os.environ.get("MINIMAX_API_KEY", ""), "voice_id": os.environ.get("MINIMAX_VOICE_ZH", ""), "model": os.environ.get("MINIMAX_MODEL", "speech-02-hd"), "base_url": os.environ.get("MINIMAX_API_BASE", "https://api.minimaxi.com"), "group_id": os.environ.get("MINIMAX_GROUP_ID", "")},
        "elevenlabs": {"key": os.environ.get("ELEVENLABS_API_KEY", ""), "voice_id": os.environ.get("ELEVENLABS_VOICE_ID", ""), "model": os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2"), "base_url": os.environ.get("ELEVENLABS_API_BASE", "https://api.elevenlabs.io")},
    }}


def public(config, version):
    return {"provider": config["provider"], "version": version, "providers": {name: {**{k: v for k, v in p.items() if k != "key"}, "key_set": bool(p["key"]), "ready": bool(p["key"] and p["voice_id"] and p["model"])} for name, p in config["providers"].items()}}


def validate_base(value):
    try:
        u = urllib.parse.urlsplit(value)
        # Plain HTTP is only for isolated development fixtures.
        if not u.hostname or u.username or u.password or u.query or u.fragment or not (u.scheme == "https" or u.scheme == "http" and u.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError()
        u.port
    except ValueError:
        raise HTTPException(422, "语音 API 地址应为 HTTPS 基础地址，不含密钥、查询参数或片段")
    return value.rstrip("/")


def elevenlabs_mp3(text, config):
    if not config["key"] or not config["voice_id"]:
        raise HTTPException(503, "ElevenLabs 尚未配置 API Key 和音色 ID")
    base = validate_base(config["base_url"])
    if base.endswith("/v1"):
        base = base[:-3]
    voice = urllib.parse.quote(config["voice_id"], safe="")
    req = urllib.request.Request(base + "/v1/text-to-speech/" + voice + "?output_format=mp3_44100_128", data=json.dumps({"text": text, "model_id": config["model"]}, ensure_ascii=False).encode(), headers={"xi-api-key": config["key"], "Content-Type": "application/json", "Accept": "audio/mpeg"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
            audio = response.read(12 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        message = {401: "密钥无效或权限不足", 403: "账户或音色访问被拒绝", 404: "音色或接口不存在", 422: "音色、模型或参数无效", 429: "额度不足或请求过于频繁"}.get(exc.code, "供应商返回错误")
        raise HTTPException(502, f"ElevenLabs：{message}（HTTP {exc.code}）") from None
    except Exception:
        raise HTTPException(502, "ElevenLabs 连接失败，请检查服务器网络与 API 地址") from None
    if not audio or len(audio) > 12 * 1024 * 1024 or content_type not in {"audio/mpeg", "audio/mp3", "application/octet-stream"}:
        raise HTTPException(502, "ElevenLabs 未返回有效的 MP3 音频")
    return audio


def register(app, relay):
    path = relay["DB_PATH"]

    def init():
        with sqlite3.connect(path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS lune_speech (id INTEGER PRIMARY KEY CHECK(id=1),config TEXT NOT NULL,version INTEGER NOT NULL)")

    def load(c):
        row = c.execute("SELECT config,version FROM lune_speech WHERE id=1").fetchone()
        config = defaults()
        if row:
            saved = json.loads(row[0])
            config["provider"] = saved["provider"]
            for name in config["providers"]:
                config["providers"][name].update(saved["providers"].get(name, {}))
        return config, row[1] if row else 0

    @app.get("/lune/speech")
    async def settings(request: Request):
        relay["check_auth"](request)
        with sqlite3.connect(path) as c:
            config, version = load(c)
        return public(config, version)

    @app.patch("/lune/speech")
    async def update(request: Request):
        relay["check_auth"](request)
        body = await request.json()
        if not isinstance(body, dict) or body.get("provider") not in {"minimax", "elevenlabs"} or not isinstance(body.get("providers", {}), dict):
            raise HTTPException(422, "语音设置格式不正确")
        with sqlite3.connect(path) as c:
            c.execute("BEGIN IMMEDIATE")
            config, version = load(c)
            if type(body.get("version")) is not int or body["version"] != version:
                raise HTTPException(409, "语音设置已经变化，请重新打开设置后保存")
            config["provider"] = body["provider"]
            for name, values in body.get("providers", {}).items():
                if name not in config["providers"] or not isinstance(values, dict):
                    raise HTTPException(422, "语音供应商不正确")
                dest = config["providers"][name]
                for key, value in values.items():
                    if key not in dest or not isinstance(value, str) or len(value) > (4096 if key == "key" else 300) or any(ord(ch) < 32 for ch in value):
                        raise HTTPException(422, "语音设置字段不正确")
                    value = value.strip()
                    if key == "key" and not value:
                        continue  # Blank secret fields keep the saved server key.
                    if key == "base_url":
                        value = validate_base(value)
                    if (key == "model" or key == "voice_id" and name == "elevenlabs") and value and not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
                        raise HTTPException(422, "音色和模型应填写 ID，不是名称或网址")
                    dest[key] = value
            c.execute("INSERT INTO lune_speech VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config,version=excluded.version", (json.dumps(config, ensure_ascii=False), version + 1))
        return public(config, version + 1)

    def synthesize(body):
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            raise HTTPException(422, "请提供朗读文字")
        text = body["text"].strip()
        if not text or len(text) > 900:
            raise HTTPException(422, "单次朗读需要 1–900 字符，请分段朗读")
        with sqlite3.connect(path) as c:
            config, _ = load(c)
        provider = body.get("provider", config["provider"])
        if provider not in {"minimax", "elevenlabs"}:
            raise HTTPException(422, "请选择 MiniMax 或 ElevenLabs")
        # No automatic fallback: never charge a second provider without selection.
        cfg = config["providers"][provider]
        return elevenlabs_mp3(text, cfg) if provider == "elevenlabs" else relay["minimax_tts_mp3"](text, cfg)

    return {"init": init, "synthesize": synthesize}
