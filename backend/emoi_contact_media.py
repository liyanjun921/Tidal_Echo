"""Owner-managed voice and image connections for Émoi contacts."""
import base64
import binascii
import json
import re
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request

try:
    from .emoi_contacts import clean_text, connect
    from .speech import elevenlabs_mp3, validate_base
except ImportError:
    from emoi_contacts import clean_text, connect
    from speech import elevenlabs_mp3, validate_base


def register(app, relay):
    path = relay["DB_PATH"]

    def init():
        with connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS emoi_contact_media (id TEXT PRIMARY KEY, config TEXT NOT NULL)")

    def get(db, ident):
        row = db.execute("SELECT config FROM emoi_contact_media WHERE id=?", (ident,)).fetchone()
        if not row:
            raise HTTPException(404, "这条媒体连接已不存在")
        return json.loads(row["config"])

    def public(db):
        output = []
        for row in db.execute("SELECT * FROM emoi_contact_media ORDER BY rowid"):
            config = json.loads(row["config"])
            output.append({"id": row["id"], "key_set": bool(config.pop("key")), **config})
        return {"connections": output}

    @app.get("/emoi/v2/media-connections")
    async def list_connections(request: Request):
        relay["check_auth"](request)
        with connect(path) as db:
            return public(db)

    @app.post("/emoi/v2/media-connections")
    async def save_connection(request: Request):
        relay["check_auth"](request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "媒体连接格式无效")
        provider = body.get("provider")
        if provider not in ("images", "minimax", "elevenlabs"):
            raise HTTPException(422, "不支持此媒体接口")
        ident = body.get("id")
        name = clean_text(body.get("name"), 80, True)
        model = clean_text(body.get("model"), 256, True)
        base = validate_base(clean_text(body.get("base_url"), 750, True))
        if any(c.isspace() or c == chr(92) for c in base):
            raise HTTPException(422, "API 地址格式无效")
        key = clean_text(body.get("key", ""), 4096)
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            old = get(db, ident) if ident else {}
            if not key and base == old.get("base_url") and provider == old.get("provider"):
                key = old["key"]
            if not key or not key.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in key):
                raise HTTPException(422, "请提供有效 API Key")
            config = {"provider": provider, "name": name, "model": model, "base_url": base, "key": key}
            if provider != "images":
                config["voice_id"] = clean_text(body.get("voice_id"), 256, True)
                if provider == "minimax":
                    config["group_id"] = clean_text(body.get("group_id", ""), 256)
            db.execute("INSERT INTO emoi_contact_media VALUES (?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config",
                       (ident or uuid4().hex, json.dumps(config, ensure_ascii=False)))
            return public(db)

    @app.delete("/emoi/v2/media-connections/{ident}")
    async def remove_connection(ident: str, request: Request):
        relay["check_auth"](request)
        with connect(path) as db:
            db.execute("DELETE FROM emoi_contact_media WHERE id=?", (ident,))
            return public(db)

    def voice(ident, text):
        with connect(path) as db:
            config = get(db, ident)
        if config["provider"] == "minimax":
            return relay["minimax_tts_mp3"](text, config)
        if config["provider"] == "elevenlabs":
            return elevenlabs_mp3(text, config)
        raise HTTPException(422, "此连接不支持语音合成")

    async def image(ident, prompt, reference=None):
        with connect(path) as db:
            config = get(db, ident)
        if config["provider"] != "images":
            raise HTTPException(422, "此连接不支持生图")
        base = config["base_url"]
        headers = {"Authorization": "Bearer " + config["key"]}
        fields = {"model": config["model"], "prompt": prompt, "n": 1}
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            if reference:
                stored = reference["url"].rsplit("/", 1)[-1]
                if not re.fullmatch(r"att-[A-Za-z0-9_-]{14}\.(?:png|jpg|jpeg|webp)", stored):
                    raise HTTPException(422, "锁脸参考图格式无效")
                with (relay["UPLOAD_DIR"] / stored).open("rb") as file:
                    response = await client.post(base + "/images/edits", headers=headers, data=fields,
                                                 files={"image": (stored, file, reference["mime"])})
            else:
                response = await client.post(base + "/images/generations", headers=headers, json=fields)
            response.raise_for_status()
            body = response.json()
            rows = body.get("data") if isinstance(body, dict) else None
            encoded = rows[0].get("b64_json", "") if isinstance(rows, list) and rows and isinstance(rows[0], dict) else ""
            try:
                if not isinstance(encoded, str) or not 0 < len(encoded) <= 16 * 1024 * 1024:
                    raise ValueError
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                raise HTTPException(502, "生图接口需返回 b64_json 图像") from None
            if data.startswith(b"\x89PNG\r\n\x1a\n"):
                mime, name = "image/png", "reply.png"
            elif data.startswith(b"\xff\xd8\xff"):
                mime, name = "image/jpeg", "reply.jpg"
            elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
                mime, name = "image/webp", "reply.webp"
            else:
                raise HTTPException(502, "生图接口未返回可用图片")
            return relay["save_upload_bytes"](data, name, mime)

    return {"init": init, "voice": voice, "image": image}
