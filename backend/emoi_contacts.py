"""Émoi v2 multi-AI identity registry and safely separated conversations.

Every route requires the existing relay owner bearer authentication.
Creates additive tables; legacy gpt/claude/group messages are untouched.
Replies use explicit model bindings and the history of this conversation only.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from uuid import UUID, uuid4

import httpx
from fastapi import Response, BackgroundTasks, HTTPException, Request

try:
    from . import emoi_autonomy as autonomy, emoi_worldbooks as worldbooks, emoi_stickers as stickers
except ImportError:
    import emoi_worldbooks as worldbooks
    import emoi_stickers as stickers
    import emoi_autonomy as autonomy

MAX_CONTACTS = 120
MAX_MEMBERS = 20
MEDIA_TYPES = {
    "image": {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
              "gif": "image/gif", "webp": "image/webp", "avif": "image/avif"},
    "voice": {"m4a": "audio/mp4", "mp4": "audio/mp4", "webm": "audio/webm",
              "ogg": "audio/ogg", "wav": "audio/wav"},
}
MEDIA_TYPES["sticker"] = MEDIA_TYPES["image"]
MEDIA_LABELS = {"image": "图片", "sticker": "表情包", "voice": "语音消息", "location": "位置"}
MODEL_ROUTES = {"default", "gpt", "claude", "chatgpt-plan", "claude-code"}
API_CONNECTION_ROUTE = re.compile(r"api:[0-9a-f]{32}")
PICTURE_FIELDS = ("avatar", "character", "voice_background", "video_background", "face_reference")
UUID_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}$")


def now():
    return datetime.now(timezone.utc).isoformat()


def valid_id(value):
    if not isinstance(value, str) or not UUID_PATTERN.fullmatch(value):
        raise HTTPException(status_code=422, detail="invalid id")
    try:
        return str(UUID(value))
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid UUID") from None


def clean_text(value, limit, required=False):
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="text required")
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise HTTPException(status_code=422, detail="invalid text length")
    return value


def connect(path):
    db = sqlite3.connect(path, timeout=12)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init(path):
    with connect(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS emoi_v2_contacts (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
          model_route TEXT NOT NULL DEFAULT '', avatar_kind TEXT NOT NULL DEFAULT 'initial',
          memory_namespace TEXT NOT NULL UNIQUE, desire_namespace TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS emoi_v2_conversations (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('direct','group')),
          title TEXT NOT NULL, memory_namespace TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS emoi_v2_members (
          conversation_id TEXT NOT NULL REFERENCES emoi_v2_conversations(id) ON DELETE CASCADE,
          contact_id TEXT NOT NULL REFERENCES emoi_v2_contacts(id),
          PRIMARY KEY(conversation_id, contact_id)
        );
        CREATE TABLE IF NOT EXISTS emoi_v2_messages (
          id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES emoi_v2_conversations(id),
          author TEXT NOT NULL CHECK(author IN ('human','contact')),
          contact_id TEXT REFERENCES emoi_v2_contacts(id),
          text TEXT NOT NULL, nonce TEXT NOT NULL, delivery TEXT NOT NULL DEFAULT 'stored_not_delivered',
          created_at TEXT NOT NULL, attachment TEXT,
          UNIQUE(conversation_id,nonce)
        );
        CREATE TABLE IF NOT EXISTS emoi_v2_moments (
          id TEXT PRIMARY KEY, text TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_emoi_v2_messages_conv ON emoi_v2_messages(conversation_id,created_at);
        """)
        if "attachment" not in {column[1] for column in db.execute("PRAGMA table_info(emoi_v2_messages)")}:
            db.execute("ALTER TABLE emoi_v2_messages ADD COLUMN attachment TEXT")
        for table in ("emoi_v2_contacts", "emoi_v2_conversations"):
            if "profile" not in {column[1] for column in db.execute(f"PRAGMA table_info({table})")}:
                db.execute(f"ALTER TABLE {table} ADD COLUMN profile TEXT NOT NULL DEFAULT '{{}}'")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS emoi_photo_albums(id TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS emoi_album_photos(
                id TEXT PRIMARY KEY, album_id TEXT NOT NULL REFERENCES emoi_photo_albums(id),
                attachment TEXT NOT NULL, contact_id TEXT, created_at TEXT NOT NULL
            );
        """)
        if "favorite" not in {column[1] for column in db.execute("PRAGMA table_info(emoi_album_photos)")}:
            db.execute("ALTER TABLE emoi_album_photos ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
        for table, columns in {
            "emoi_v2_messages": (("call_state", "TEXT"), ("followup_score", "INTEGER"),),
            "emoi_v2_moments": (("contact_id", "TEXT"), ("attachment", "TEXT"), ("wake_event", "TEXT")),
        }.items():
            existing = {column[1] for column in db.execute(f"PRAGMA table_info({table})")}
            for column, schema in columns:
                if column not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {schema}")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS emoi_moment_wake ON emoi_v2_moments(wake_event)")
        worldbooks.init(db)
        autonomy.init(db)
        db.execute("UPDATE emoi_v2_messages SET delivery='interrupted' WHERE delivery='replying'")


def wake_target(db, scope):
    targets = db.execute("""
        SELECT c.id, c.name, c.profile, v.id AS conversation_id
        FROM emoi_v2_contacts c JOIN emoi_v2_members m ON m.contact_id=c.id
        JOIN emoi_v2_conversations v ON v.id=m.conversation_id
        WHERE c.archived=0 AND v.archived=0 AND v.kind='direct'
          AND json_extract(c.profile,'$.proactive_enabled')=1
          AND json_extract(c.profile,'$.desire_scope')=?
        LIMIT 2
    """, (scope,)).fetchall()
    return targets[0] if len(targets) == 1 else None


def store_wake_message(db, scope, event, text, stamp, delivery=None):
    """Publish a permitted Wren decision in the contact's own conversation or feed."""
    contact = wake_target(db, scope)
    if contact is None:
        return None
    delivery = delivery if delivery and delivery.get("contact_id") == contact["id"] else {}
    return store_contact_action(db, contact, event, text, stamp, delivery, prefix="wren:")


def store_contact_action(db, contact, event, text, stamp, delivery, prefix=""):
    attachment = delivery.get("attachment")
    payload = json.dumps(attachment) if attachment else None
    ident = str(uuid4())
    mode = delivery.get("mode", "text")
    if mode == "moment":
        inserted = db.execute("""
            INSERT OR IGNORE INTO emoi_v2_moments(id,text,created_at,contact_id,attachment,wake_event)
            VALUES(?,?,?,?,?,?)
        """, (ident, text, stamp, contact["id"], payload, event)).rowcount
        summary = "发了一条朋友圈"
    else:
        inserted = db.execute("""
            INSERT OR IGNORE INTO emoi_v2_messages
              (id,conversation_id,author,contact_id,text,nonce,delivery,created_at,attachment)
            VALUES(?,?,'contact',?,?,?,'generated',?,?)
        """, (ident, contact["conversation_id"], contact["id"], text, prefix + event, stamp, payload)).rowcount
        summary = "发来一条新消息"
        if mode in ("voice_invite", "video_invite"):
            summary = "邀请你" + ("语音通话" if mode == "voice_invite" else "视频通话")
    return {"title": contact["name"], "body": summary, "url": "/", "id": ident} if inserted else None


def register(app, relay):
    path = relay["DB_PATH"]
    worldbooks.register(app, relay, connect, valid_id, clean_text)
    stickers.register(app, relay["check_auth"])

    def auth(request):
        relay["check_auth"](request)

    def contact(db, cid, active=True):
        row = db.execute("SELECT * FROM emoi_v2_contacts WHERE id=?", (valid_id(cid),)).fetchone()
        if row is None or (active and row["archived"]):
            raise HTTPException(status_code=404, detail="contact not found")
        return row

    def conversation(db, cid):
        row = db.execute("SELECT * FROM emoi_v2_conversations WHERE id=? AND archived=0", (valid_id(cid),)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return row

    def view_contact(db, row):
        profile = json.loads(row["profile"])
        profile["worldbook_ids"] = worldbooks.bindings(db, row["id"])
        return {
            "id": row["id"], "name": row["name"], "notes": row["notes"],
            "model_route": row["model_route"], "memory_namespace": row["memory_namespace"],
            "desire_namespace": row["desire_namespace"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "connected": False,
            "memory_connected": False, "desire_connected": False, "profile": profile,
        }

    def view_message(row):
        result = dict(row)
        result["attachment"] = json.loads(result["attachment"]) if result["attachment"] else None
        return result

    def message_attachment(value):
        if value is None:
            return None
        if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
            raise HTTPException(422, "无效的聊天附件")
        kind = value["kind"]
        if kind == "location":
            lat, lon = value.get("latitude"), value.get("longitude")
            if (type(lat) not in (int, float) or type(lon) not in (int, float)
                    or not -90 <= lat <= 90 or not -180 <= lon <= 180):
                raise HTTPException(422, "位置坐标无效")
            return {"kind": kind, "latitude": round(lat, 6), "longitude": round(lon, 6)}
        stored = value.get("id")
        match = re.fullmatch(r"att-[A-Za-z0-9_-]{14}\.([a-z0-9]+)", stored) if isinstance(stored, str) else None
        mime = MEDIA_TYPES.get(kind, {}).get(match[1]) if match else None
        path = relay.get("UPLOAD_DIR")
        if not mime or path is None or not (path / stored).is_file():
            raise HTTPException(422, "聊天附件不存在或格式不支持")
        attachment = {"kind": kind, "url": "/uploads/" + stored, "mime": mime,
                "size": (path / stored).stat().st_size, "name": MEDIA_LABELS[kind]}
        duration = value.get("duration")
        if kind == "voice" and type(duration) in (int, float) and 0 <= duration <= 120:
            attachment["duration"] = round(duration, 2)
        return attachment

    def get_rule(db, contact_id):
        row = db.execute("SELECT settings FROM emoi_message_rules WHERE contact_id=?", (contact_id,)).fetchone()
        if row:
            return {**autonomy.DEFAULTS, **json.loads(row["settings"])}
        person = db.execute("SELECT profile FROM emoi_v2_contacts WHERE id=?", (contact_id,)).fetchone()
        return {**autonomy.DEFAULTS, "calls": bool(person and json.loads(person["profile"]).get("proactive_enabled"))}

    def pending_call(db, contact_id):
        return db.execute("""
            SELECT 1 FROM emoi_v2_messages WHERE contact_id=? AND call_state IS NULL
             AND json_extract(attachment,'$.kind')='call_invite'
             AND julianday(created_at)>julianday('now','-90 seconds')
        """, (contact_id,)).fetchone()

    async def notify_action(payload):
        if relay.get("push_to_all"):
            try:
                await relay["push_to_all"](payload)
            except Exception:
                logging.getLogger(__name__).warning("Émoi notification failed")

    async def action_attachment(profile, reply, text, catalog, can_call=False, voice_reply=False):
        mode = reply.get("call")
        if can_call and mode in ("voice", "video"):
            return {"kind": "call_invite", "mode": mode}
        sticker = reply.get("sticker")
        if sticker and any(entry["id"] == sticker for entry in catalog):
            with connect(path) as db:
                row = db.execute("SELECT attachment FROM emoi_shared_stickers WHERE id=?", (sticker,)).fetchone()
            if row:
                return json.loads(row["attachment"])
        media = relay.get("contact_media_runtime") or {}
        try:
            if reply.get("image_prompt") and profile.get("image_connection") and media:
                return await media["image"](profile["image_connection"], reply["image_prompt"], profile.get("face_reference"))
            if len(text) <= 900 and (voice_reply or reply.get("voice_reply") is True):
                if profile.get("voice_connection") and media:
                    data = await asyncio.to_thread(media["voice"], profile["voice_connection"], text)
                elif voice_reply and relay.get("speech_runtime"):
                    data = await asyncio.to_thread(relay["speech_runtime"]["synthesize"], {"text": text})
                else:
                    return None
                attachment = relay["save_upload_bytes"](data, "reply.mp3", "audio/mpeg")
                attachment.update(kind="voice", transcript=text)
                return attachment
        except (HTTPException, OSError, httpx.HTTPError, ValueError):
            return None
        return None

    @app.get("/emoi/v2/stickers/shared")
    async def shared_stickers(request: Request, response: Response):
        auth(request)
        with connect(path) as db:
            rows = db.execute("SELECT * FROM emoi_shared_stickers ORDER BY pack,name,id").fetchall()
        response.headers["Cache-Control"] = "no-store"
        return {"ids": [row["id"] for row in rows],
                "items": [{**dict(row), "attachment": json.loads(row["attachment"])} for row in rows]}

    @app.post("/emoi/v2/stickers/shared")
    async def share_sticker(request: Request):
        auth(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "无效的表情包")
        ident = clean_text(body.get("id"), 64, True)
        if not re.fullmatch("[a-f0-9]{64}", ident):
            raise HTTPException(422, "无效的表情包编号")
        name = clean_text(body.get("name"), 120, True)
        pack = clean_text(body.get("pack"), 120, True)
        attachment = message_attachment({"kind": "sticker", "id": body.get("upload")})
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute("SELECT 1 FROM emoi_shared_stickers WHERE id=?", (ident,)).fetchone()
            if not exists and db.execute("SELECT COUNT(*) FROM emoi_shared_stickers").fetchone()[0] >= 5000:
                raise HTTPException(409, "服务器表情包已达到 5000 张")
            db.execute("INSERT OR IGNORE INTO emoi_shared_stickers VALUES(?,?,?,?)",
                       (ident, name, pack, json.dumps(attachment)))
        return {"ok": True}

    @app.delete("/emoi/v2/stickers/shared/{sticker_id}")
    async def unshare_sticker(sticker_id: str, request: Request):
        auth(request)
        with connect(path) as db:
            db.execute("DELETE FROM emoi_shared_stickers WHERE id=?", (sticker_id,))
        return {"ok": True}

    def direct_recipient(db, contact_id):
        person = contact(db, contact_id)
        row = db.execute("""
            SELECT v.id FROM emoi_v2_conversations v JOIN emoi_v2_members m ON v.id=m.conversation_id
            WHERE m.contact_id=? AND v.kind='direct' AND v.archived=0
        """, (person["id"],)).fetchone()
        if not row:
            raise HTTPException(404, "联系人会话不可用")
        return {**dict(person), "conversation_id": row["id"]}

    @app.get("/emoi/v2/contacts/{contact_id}/message-rules")
    async def read_message_rules(contact_id: str, request: Request):
        auth(request)
        with connect(path) as db:
            person = direct_recipient(db, contact_id)
            row = db.execute("SELECT * FROM emoi_message_rules WHERE contact_id=?", (person["id"],)).fetchone()
            count = autonomy.timeline(db, person["conversation_id"], row["saved"])[3] if row else 0
            return {"settings": get_rule(db, person["id"]), "count": count,
                    "next_moment": row["next_moment"] if row and json.loads(row["settings"])["moments"] else None}

    @app.put("/emoi/v2/contacts/{contact_id}/message-rules")
    async def write_message_rules(contact_id: str, request: Request):
        auth(request)
        config = autonomy.settings(await request.json())
        stamp = time.time()
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            person = direct_recipient(db, contact_id)
            old = db.execute("SELECT * FROM emoi_message_rules WHERE contact_id=?", (person["id"],)).fetchone()
            previous = json.loads(old["settings"]) if old else {}
            next_post = old["next_moment"] if old and all(previous.get(k) == config[k] for k in
                         ("moments", "min_hours", "max_hours")) else autonomy.next_moment(config, stamp)
            db.execute("""
                INSERT INTO emoi_message_rules(contact_id,settings,saved,next_moment) VALUES(?,?,?,?)
                ON CONFLICT(contact_id) DO UPDATE SET settings=excluded.settings,
                  next_moment=excluded.next_moment, retry=0
            """, (person["id"], json.dumps(config), stamp, next_post))
        return {"settings": config}

    async def generate_action(person, config, trigger, *, manual=False, moment_text="", photo_mode=None):
        cid = person["conversation_id"]
        profile = json.loads(person["profile"])
        with connect(path) as db:
            rows = db.execute("""
                SELECT m.author,m.contact_id,m.text,m.created_at,c.name
                FROM emoi_v2_messages m LEFT JOIN emoi_v2_contacts c ON c.id=m.contact_id
                WHERE m.conversation_id=? ORDER BY m.rowid DESC LIMIT 30
            """, (cid,)).fetchall()
            history = [dict(row) for row in reversed(rows)] if trigger != "reaction" else []
            recent = "\n".join(entry["text"][:3000] for entry in history[-8:])
            catalog = autonomy.catalog(db, recent) if trigger not in ("moment", "reaction") else []
            book_context = worldbooks.context(db, recent, person["id"])
        can_call = config["calls"] and trigger not in ("moment", "reaction")
        photo_mode = photo_mode or config.get("moment_photo", "auto")
        if trigger == "moment" and photo_mode == "image" and not profile.get("image_connection"):
            raise HTTPException(422, "请先为该角色绑定图片生成接口")
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            response = await client.post(relay["loop_base_url"]() + "/loop/contact-reply", json={
                "route": person["model_route"], "contact_id": person["id"], "name": person["name"],
                "notes": person["notes"], "history": history, "profile": profile,
                "local_time": datetime.now(ZoneInfo(config["zone"])).isoformat(timespec="minutes"),
                "worldbooks": book_context, "stickers": catalog, "can_call": can_call,
                "initiative": trigger, "checkin": config["checkin"], "manual": manual,
                "moment_text": moment_text, "moment_photo": photo_mode,
            })
            response.raise_for_status()
            reply = response.json()
        if reply.get("skip"):
            return None
        text = clean_text(reply.get("text"), 1000 if trigger in ("moment", "reaction") else 10000, True)
        if trigger == "reaction":
            return text, {}
        if trigger == "moment":
            reply = {"image_prompt": reply.get("image_prompt")} if photo_mode != "text" else {}
        attachment = await action_attachment(profile, reply, text, catalog, can_call)
        if trigger == "moment" and photo_mode == "image" and not attachment:
            raise HTTPException(502, "本次未能生成配图，请检查图片接口或选择纯文字")
        mode = "moment" if trigger == "moment" else (
            attachment["mode"] + "_invite" if attachment and attachment["kind"] == "call_invite" else "text"
        )
        return text, {"mode": mode, "attachment": attachment}

    @app.post("/emoi/v2/contacts/{contact_id}/message-rules/run")
    async def run_message_rule(contact_id: str, request: Request):
        auth(request)
        body = await request.json()
        mode = body.get("mode") if isinstance(body, dict) else None
        if mode not in ("voice", "video", "moment"):
            raise HTTPException(422, "无效的操作")
        with connect(path) as db:
            person = direct_recipient(db, contact_id)
            config = get_rule(db, person["id"])
        if mode == "moment":
            photo_mode = body.get("photo")
            if photo_mode is not None and photo_mode not in ("auto", "text", "image"):
                raise HTTPException(422, "无效的配图选项")
            if not relay.get("loop_base_url"):
                raise HTTPException(503, "模型服务尚未连接")
            try:
                result = await generate_action(person, config, "moment", manual=True, photo_mode=photo_mode)
            except httpx.HTTPStatusError as error:
                raise HTTPException(502, f"绑定的模型未能发帖（HTTP {error.response.status_code}）") from None
            except (httpx.RequestError, ValueError):
                raise HTTPException(502, "模型服务暂不可用") from None
            if result is None:
                raise HTTPException(502, "角色没有生成动态")
            text, delivery = result
        else:
            text = "语音来电测试" if mode == "voice" else "视频来电测试"
            delivery = {"mode": mode + "_invite", "attachment": {"kind": "call_invite", "mode": mode}}
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            person = direct_recipient(db, contact_id)
            if mode != "moment" and pending_call(db, person["id"]):
                raise HTTPException(409, "已有待接听的来电")
            event = "manual:" + uuid4().hex
            item = store_contact_action(db, person, event, text, now(), delivery)
        if item and config["push"]:
            await notify_action(item)
        return {"id": item["id"]}

    async def schedule_one():
        stamp = time.time()
        selected = None
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("""
                SELECT r.* FROM emoi_message_rules r JOIN emoi_v2_contacts c ON c.id=r.contact_id
                 WHERE c.archived=0 AND c.model_route<>'' AND r.lease<=? AND r.retry<=?
                 ORDER BY r.retry,r.contact_id
            """, (stamp, stamp)):
                config = {**autonomy.DEFAULTS, **json.loads(row["settings"])}
                if not any(config[k] for k in ("idle", "followup", "moments")):
                    continue
                try:
                    person = direct_recipient(db, row["contact_id"])
                except HTTPException:
                    continue
                decision = autonomy.due(db, row, person["conversation_id"], config, stamp)
                if decision:
                    lease = stamp + 300
                    db.execute("UPDATE emoi_message_rules SET lease=? WHERE contact_id=?", (lease, person["id"]))
                    selected = row, person, config, decision
                    break
        if selected is None:
            return
        row, person, config, (trigger, cursor) = selected
        key = person["id"]
        payload = None
        try:
            result = await asyncio.wait_for(generate_action(person, config, trigger), timeout=175)
            with connect(path) as db:
                db.execute("BEGIN IMMEDIATE")
                latest = db.execute("SELECT * FROM emoi_message_rules WHERE contact_id=?", (key,)).fetchone()
                current = direct_recipient(db, key)
                finished = time.time()
                if latest["lease"] == lease and row["settings"] == latest["settings"] and (
                    current["updated_at"] == person["updated_at"] and
                    autonomy.due(db, latest, person["conversation_id"], config, finished) == (trigger, cursor)
                ):
                    if result:
                        text, delivery = result
                        if delivery["mode"].endswith("_invite") and pending_call(db, key):
                            delivery = {}
                        payload = store_contact_action(db, person, trigger + ":" + uuid4().hex, text, now(), delivery)
                    if trigger == "moment":
                        db.execute("UPDATE emoi_message_rules SET next_moment=? WHERE contact_id=?",
                                   (autonomy.next_moment(config, finished), key))
        finally:
            with connect(path) as db:
                db.execute("UPDATE emoi_message_rules SET lease=0,retry=? WHERE contact_id=? AND lease=?",
                           (time.time() + (10 if payload else 120), key, lease))
        if payload and config["push"]:
            await notify_action(payload)

    async def react_one():
        stamp = time.time()
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("""
                SELECT a.*,m.text,c.archived FROM emoi_moment_reactions a
                JOIN emoi_v2_moments m ON m.id=a.moment_id
                JOIN emoi_v2_contacts c ON c.id=a.contact_id
                WHERE a.done=0 AND a.due<=? ORDER BY a.due
            """, (stamp,))
            for job in rows:
                config = get_rule(db, job["contact_id"])
                if job["archived"] or not config["reactions"]:
                    db.execute("DELETE FROM emoi_moment_reactions WHERE moment_id=? AND contact_id=?",
                               (job["moment_id"], job["contact_id"]))
                elif not autonomy.is_quiet(config, stamp):
                    person = direct_recipient(db, job["contact_id"])
                    db.execute("UPDATE emoi_moment_reactions SET due=? WHERE moment_id=? AND contact_id=?",
                               (stamp + 300, job["moment_id"], person["id"]))
                    break
            else:
                return
        comment = ""
        if job["wants_comment"]:
            try:
                result = await asyncio.wait_for(generate_action(
                    person, config, "reaction", moment_text=job["text"]), timeout=100)
                if result:
                    comment = result[0]
            except (HTTPException, httpx.HTTPError, TimeoutError, ValueError, OSError):
                pass
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            if get_rule(db, person["id"])["reactions"]:
                db.execute("""
                    UPDATE emoi_moment_reactions SET comment=?,done=1
                    WHERE moment_id=? AND contact_id=? AND due=? AND done=0
                """, (comment, job["moment_id"], person["id"], stamp + 300))

    async def watch():
        while True:
            if relay.get("loop_base_url"):
                try:
                    await schedule_one()
                    await react_one()
                except (HTTPException, httpx.HTTPError, TimeoutError, ValueError, OSError, sqlite3.Error):
                    logging.getLogger(__name__).warning("Émoi scheduled contact action failed")
            await asyncio.sleep(5)

    def saved_picture(value):
        if value in (None, ""):
            return None
        if not isinstance(value, str):
            raise HTTPException(422, "图片附件无效")
        return message_attachment({"kind": "image", "id": value})

    def update_profile(body, previous, *, group=False):
        edits = body.get("profile", {})
        if not isinstance(edits, dict):
            raise HTTPException(422, "档案设置格式无效")
        for field in ("avatar",) if group else PICTURE_FIELDS:
            if field in edits:
                previous[field] = saved_picture(edits[field])
        if not group:
            for field, limit in (("instructions", 12000), ("worldbook", 24000), ("voice_connection", 60), ("image_connection", 60), ("ob_server", 32)):
                if field in edits:
                    previous[field] = clean_text(edits[field], limit)
            if "desire_scope" in edits:
                if edits["desire_scope"] not in ("", "gpt", "claude"):
                    raise HTTPException(422, "欲望空间无效")
                previous["desire_scope"] = edits["desire_scope"]
            if "proactive_enabled" in edits:
                if type(edits["proactive_enabled"]) is not bool:
                    raise HTTPException(422, "主动消息开关无效")
                previous["proactive_enabled"] = edits["proactive_enabled"]
        return json.dumps(previous, ensure_ascii=False)

    def bind_worldbooks(db, contact_id, body):
        edits = body.get("profile", {})
        if "worldbook_ids" in edits:
            worldbooks.bind(db, contact_id, edits["worldbook_ids"], valid_id)

    def check_wake_binding(db, ident, profile):
        bound = json.loads(profile)
        if bound.get("proactive_enabled") and bound.get("desire_scope") and db.execute("""
            SELECT 1 FROM emoi_v2_contacts WHERE archived=0 AND id<>?
              AND json_extract(profile,'$.proactive_enabled')=1 AND json_extract(profile,'$.desire_scope')=?
        """, (ident, bound["desire_scope"])).fetchone():
            raise HTTPException(409, "这个欲望空间已绑定到另一位联系人")

    @app.get("/emoi/v2/albums")
    async def list_albums(request: Request):
        auth(request)
        with connect(path) as db:
            albums = [dict(row) for row in db.execute("SELECT * FROM emoi_photo_albums ORDER BY rowid")]
            photos = [dict(row) for row in db.execute("SELECT * FROM emoi_album_photos ORDER BY rowid DESC")]
        for photo in photos:
            photo["attachment"] = json.loads(photo["attachment"])
        return {"albums": albums, "photos": photos}

    @app.post("/emoi/v2/albums")
    async def create_album(request: Request):
        auth(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "相册格式无效")
        name = clean_text(body.get("name"), 80, True)
        with connect(path) as db:
            ident = str(uuid4())
            db.execute("INSERT INTO emoi_photo_albums VALUES(?,?)", (ident, name))
        return {"id": ident, "name": name}

    @app.post("/emoi/v2/albums/{album_id}/photos")
    async def add_photo(album_id: str, request: Request):
        auth(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "照片格式无效")
        attachment = saved_picture(body.get("id"))
        if not attachment:
            raise HTTPException(422, "请选择图片")
        person = body.get("contact_id")
        with connect(path) as db:
            if not db.execute("SELECT 1 FROM emoi_photo_albums WHERE id=?", (valid_id(album_id),)).fetchone():
                raise HTTPException(404, "相册不存在")
            if person:
                person = contact(db, person)["id"]
            ident = str(uuid4())
            db.execute("INSERT INTO emoi_album_photos(id,album_id,attachment,contact_id,created_at) VALUES(?,?,?,?,?)",
                       (ident, album_id, json.dumps(attachment), person or None, now()))
        return {"id": ident}

    @app.patch("/emoi/v2/albums/photos/{photo_id}")
    async def update_photo(photo_id: str, request: Request):
        auth(request)
        body = await request.json()
        if not isinstance(body, dict) or type(body.get("favorite")) is not bool:
            raise HTTPException(422, "收藏设置无效")
        with connect(path) as db:
            changed = db.execute("UPDATE emoi_album_photos SET favorite=? WHERE id=?",
                                 (body["favorite"], valid_id(photo_id))).rowcount
            if not changed:
                raise HTTPException(404, "照片不存在")
        return {"favorite": body["favorite"]}

    @app.post("/emoi/v2/albums/suggest-person")
    async def suggest_person(request: Request):
        auth(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "照片格式无效")
        picture = saved_picture(body.get("id"))
        binding = body.get("model_route")
        if not picture or not isinstance(binding, str) or not API_CONNECTION_ROUTE.fullmatch(binding):
            raise HTTPException(422, "请选择照片与支持视觉的自定义 API")
        with connect(path) as db:
            refs = []
            for row in db.execute("SELECT id, profile FROM emoi_v2_contacts WHERE archived=0 ORDER BY rowid"):
                photo = json.loads(row["profile"]).get("face_reference")
                if photo:
                    refs.append({"id": row["id"], "photo": photo})
        if not refs or len(refs) > 8:
            raise HTTPException(422, "请给 1–8 位候选联系人上传脸部参考图")
        if picture["size"] + sum(entry["photo"]["size"] for entry in refs) > 20 * 1024 * 1024:
            raise HTTPException(422, "照片和参考图合计不能超过 20 MB")
        try:
            async with httpx.AsyncClient(timeout=28, trust_env=False) as client:
                response = await client.post(relay["loop_base_url"]() + "/loop/album-suggest-person",
                    json={"binding": binding, "picture": picture, "references": refs})
                response.raise_for_status()
                result = response.json().get("contact_id")
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "视觉模型暂未返回人物建议，请确认接口支持图片输入") from None
        return {"contact_id": result if any(entry["id"] == result for entry in refs) else None}

    def model_members(db, cid):
        return db.execute("""
          SELECT c.* FROM emoi_v2_members m JOIN emoi_v2_contacts c ON c.id=m.contact_id
          WHERE m.conversation_id=? AND c.archived=0 ORDER BY m.rowid
        """, (cid,)).fetchall()

    def reply_targets(db, cid):
        return [member for member in model_members(db, cid) if member["model_route"] in MODEL_ROUTES or API_CONNECTION_ROUTE.fullmatch(member["model_route"])]

    async def generate_replies(cid, message_id, recipients, voice_reply=False, call_mode=""):
        completed = 0
        try:
            url = relay["loop_base_url"]() + "/loop/contact-reply"
            async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
                for recipient in recipients:
                    with connect(path) as db:
                        active = {m["id"]: m for m in reply_targets(db, cid)}
                        if not db.execute("SELECT 1 FROM emoi_v2_conversations WHERE id=? AND archived=0", (cid,)).fetchone():
                            break
                        current = active.get(recipient["id"])
                        if not current or current["model_route"] != recipient["model_route"]:
                            continue
                        rows = db.execute("""
                          SELECT m.id, m.author, m.contact_id, m.text, m.created_at, m.attachment, c.name
                          FROM emoi_v2_messages m LEFT JOIN emoi_v2_contacts c ON c.id=m.contact_id
                          WHERE m.conversation_id=? ORDER BY m.rowid DESC LIMIT 40
                        """, (cid,)).fetchall()
                    history = [dict(row) for row in reversed(rows)]
                    for entry in history:
                        attachment = entry.pop("attachment")
                        if attachment and entry["id"] == message_id:
                            entry["attachment"] = json.loads(attachment)
                    profile = json.loads(current["profile"])
                    # Shared-memory spaces are private to the bound contact.
                    with connect(path) as db:
                        direct = conversation(db, cid)["kind"] == "direct"
                        recent = "\n".join(entry["text"][:3000] for entry in history[-8:])
                        book_context = worldbooks.context(db, recent, current["id"])
                        catalog = autonomy.catalog(db, recent) if not call_mode else []
                        rule = get_rule(db, current["id"])
                    can_call = direct and not call_mode and rule["calls"]
                    local_time = datetime.now(ZoneInfo(rule["zone"])).isoformat(timespec="minutes")
                    try:
                        response = await client.post(url, json={
                            "route": current["model_route"], "contact_id": current["id"],
                            "name": current["name"], "notes": current["notes"], "history": history,
                            "call_mode": call_mode, "worldbooks": book_context, "local_time": local_time,
                            "stickers": catalog, "can_call": can_call, "score_followup": rule["followup"] and not call_mode,
                            "profile": {**profile, "ob_server": profile.get("ob_server", "") if direct else ""},
                        })
                        response.raise_for_status()
                        reply = response.json()
                        text = clean_text(reply.get("text"), 10000, True)
                    except (httpx.HTTPError, ValueError, HTTPException):
                        continue
                    attachment = await action_attachment(profile, reply, text, catalog, False, voice_reply)
                    call = reply.get("call") if can_call and reply.get("call") in ("voice", "video") else None
                    call_id = None
                    score = reply.get("followup_score") if rule["followup"] and not call_mode else None
                    if type(score) is not int or not 0 <= score <= 100:
                        score = None
                    reply_id = str(uuid4())
                    with connect(path) as db:
                        db.execute("BEGIN IMMEDIATE")
                        still_member = db.execute("""
                          SELECT 1 FROM emoi_v2_members m
                          JOIN emoi_v2_contacts c ON c.id=m.contact_id
                          JOIN emoi_v2_conversations v ON v.id=m.conversation_id
                          WHERE v.id=? AND c.id=? AND c.archived=0 AND v.archived=0
                        """, (cid, current["id"])).fetchone()
                        if not still_member:
                            continue
                        if call and get_rule(db, current["id"])["calls"] and not pending_call(db, current["id"]):
                            call_attachment = {"kind": "call_invite", "mode": call}
                            if attachment:
                                result = store_contact_action(
                                    db, {**dict(current), "conversation_id": cid},
                                    "call:" + message_id + ":" + current["id"],
                                    "视频来电" if call == "video" else "语音来电", now(),
                                    {"mode": call + "_invite", "attachment": call_attachment},
                                )
                                call_id = result["id"] if result else None
                            else:
                                attachment = call_attachment
                                call_id = reply_id
                        db.execute("""
                          INSERT INTO emoi_v2_messages(id,conversation_id,author,contact_id,text,nonce,delivery,created_at,attachment,followup_score)
                          VALUES(?,?,'contact',?,?,?,'generated',?,?,?)
                        """, (reply_id, cid, current["id"], text, "reply:"+message_id+":"+current["id"], now(),
                              json.dumps(attachment, ensure_ascii=False) if attachment else None, score))
                        completed += 1
                    if call_id and rule["push"]:
                        await notify_action({"title": current["name"], "body": "应用内来电", "url": "/", "id": call_id})
                    if direct and profile.get("ob_server"):
                        with connect(path) as db:
                            turn = db.execute("SELECT * FROM emoi_v2_messages WHERE id IN (?,?) ORDER BY rowid",
                                              (message_id, reply_id)).fetchall()
                        try:
                            await client.post(relay["loop_base_url"]() + "/loop/contact-archive",
                                              json={"server": profile["ob_server"], "conversation_id": cid,
                                                    "messages": [{"message_id": row["id"],
                                                                  "role": "user" if row["author"] == "human" else "assistant",
                                                                  "text": row["text"], "created_at": row["created_at"]}
                                                                 for row in turn]}, timeout=8)
                        except httpx.HTTPError:
                            pass
        finally:
            state = "replied" if completed == len(recipients) else "partial" if completed else "model_failed"
            with connect(path) as db:
                db.execute("UPDATE emoi_v2_messages SET delivery=? WHERE id=?", (state, message_id))

    def view_conversation(db, row):
        members=[m[0] for m in db.execute(
            "SELECT contact_id FROM emoi_v2_members WHERE conversation_id=? ORDER BY rowid",(row["id"],))]
        latest = db.execute("""
          SELECT text,created_at FROM emoi_v2_messages WHERE conversation_id=?
          ORDER BY created_at DESC,id DESC LIMIT 1
        """, (row["id"],)).fetchone()
        return {
            "id":row["id"],"kind":row["kind"],"title":row["title"],"latest":dict(latest) if latest else None,
            "members":members,"memory_namespace":row["memory_namespace"],
            "created_at":row["created_at"],"connected":False,"profile":json.loads(row["profile"]),
        }

    @app.get("/emoi/v2/contacts")
    async def v2_list_contacts(request: Request):
        auth(request)
        with connect(path) as db:
            rows=db.execute("SELECT * FROM emoi_v2_contacts WHERE archived=0 ORDER BY created_at").fetchall()
            return {"contacts":[view_contact(db, row) for row in rows]}

    @app.post("/emoi/v2/contacts")
    async def v2_create_contact(request: Request):
        auth(request)
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(422,"invalid contact")
        cid=valid_id(body.get("id") or str(uuid4()))
        name=clean_text(body.get("name"),60,True)
        notes=clean_text(body.get("notes",""),5000)
        route=clean_text(body.get("model_route",""),100)
        timestamp=now()
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            profile = update_profile(body, {})
            check_wake_binding(db, cid, profile)
            count=db.execute("SELECT COUNT(*) FROM emoi_v2_contacts WHERE archived=0").fetchone()[0]
            if count>=MAX_CONTACTS:raise HTTPException(409,"contact limit reached")
            try:
                db.execute("INSERT INTO emoi_v2_contacts(id,name,notes,model_route,memory_namespace,desire_namespace,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (cid,name,notes,route,"contact:"+cid, "desire:contact:"+cid,timestamp,timestamp))
            except sqlite3.IntegrityError:
                raise HTTPException(409,"contact id already exists") from None
            db.execute("UPDATE emoi_v2_contacts SET profile=? WHERE id=?", (profile, cid))
            bind_worldbooks(db, cid, body)
            # Each contact begins with an independent direct conversation.
            conv=str(uuid4())
            db.execute("INSERT INTO emoi_v2_conversations(id,kind,title,memory_namespace,created_at,updated_at) VALUES(?,'direct',?,?,?,?)",
                (conv,name,"conversation:"+conv,timestamp,timestamp))
            db.execute("INSERT INTO emoi_v2_members VALUES(?,?)",(conv,cid))
            return {"contact":view_contact(db, contact(db,cid)),
                    "conversation_id":conv}

    @app.patch("/emoi/v2/contacts/{contact_id}")
    async def v2_edit_contact(contact_id: str, request: Request):
        auth(request)
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(422,"invalid contact")
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            old=contact(db,contact_id)
            profile = update_profile(body, json.loads(old["profile"]))
            check_wake_binding(db, old["id"], profile)
            name=clean_text(body.get("name",old["name"]),60,True)
            notes=clean_text(body.get("notes",old["notes"]),5000)
            route=clean_text(body.get("model_route",old["model_route"]),100)
            # Never accept arbitrary memory/desire scope changes from the browser.
            db.execute("UPDATE emoi_v2_contacts SET name=?,notes=?,model_route=?,updated_at=?,profile=? WHERE id=?",
                (name,notes,route,now(),profile,old["id"]))
            bind_worldbooks(db, old["id"], body)
            return {"contact":view_contact(db, contact(db,old["id"]))}

    @app.delete("/emoi/v2/contacts/{contact_id}")
    async def v2_archive_contact(contact_id: str,request: Request):
        auth(request)
        with connect(path) as db:
            old=contact(db,contact_id)
            db.execute("UPDATE emoi_v2_contacts SET archived=1,updated_at=? WHERE id=?",(now(),old["id"]))
            return {"archived":True,"id":old["id"]}

    @app.get("/emoi/v2/conversations")
    async def v2_list_conversations(request: Request):
        auth(request)
        with connect(path) as db:
            rows=db.execute("SELECT * FROM emoi_v2_conversations WHERE archived=0 ORDER BY created_at").fetchall()
            return {"conversations":[view_conversation(db,row) for row in rows]}

    @app.post("/emoi/v2/conversations")
    async def v2_create_conversation(request: Request):
        auth(request)
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(422,"invalid conversation")
        members=body.get("members",[])
        if not isinstance(members,list) or not 1<=len(members)<=MAX_MEMBERS:
            raise HTTPException(422,"invalid members")
        ids=[valid_id(mid) for mid in members]
        if len(set(ids))!=len(ids):raise HTTPException(422,"duplicate members")
        title=clean_text(body.get("title"),80,True)
        kind=body.get("kind","group")
        if kind!="group":raise HTTPException(422,"only user-created groups supported")
        cid=valid_id(body.get("id") or str(uuid4()))
        created=now()
        with connect(path) as db:
            for id in ids:contact(db,id)
            count=db.execute("SELECT COUNT(*) FROM emoi_v2_conversations WHERE archived=0").fetchone()[0]
            if count>=200:raise HTTPException(409,"conversation limit")
            try:
                db.execute("INSERT INTO emoi_v2_conversations(id,kind,title,memory_namespace,created_at,updated_at) VALUES(?,'group',?,?,?,?)",
                    (cid,title,"conversation:"+cid,created,created))
            except sqlite3.IntegrityError:raise HTTPException(409,"duplicate conversation") from None
            db.execute("UPDATE emoi_v2_conversations SET profile=? WHERE id=?", (update_profile(body, {}, group=True), cid))
            db.executemany("INSERT INTO emoi_v2_members VALUES(?,?)",[(cid,id) for id in ids])
            return {"conversation":view_conversation(db,conversation(db,cid))}

    @app.patch("/emoi/v2/conversations/{conversation_id}")
    async def v2_edit_conversation(conversation_id: str, request: Request):
        auth(request)
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(422,"invalid conversation")
        with connect(path) as db:
            old=conversation(db,conversation_id)
            if old["kind"]!="group":
                raise HTTPException(422,"direct conversation ownership cannot be changed")
            title=clean_text(body.get("title",old["title"]),80,True)
            members=body.get("members")
            if members is None:
                ids=[m[0] for m in db.execute("SELECT contact_id FROM emoi_v2_members WHERE conversation_id=?",(old["id"],))]
            else:
                if not isinstance(members,list) or not 1<=len(members)<=MAX_MEMBERS:
                    raise HTTPException(422,"invalid members")
                ids=[valid_id(mid) for mid in members]
                if len(set(ids))!=len(ids):raise HTTPException(422,"duplicate members")
                for id in ids:contact(db,id)
            db.execute("UPDATE emoi_v2_conversations SET title=?,updated_at=?,profile=? WHERE id=?",(title,now(),update_profile(body,json.loads(old["profile"]),group=True),old["id"]))
            db.execute("DELETE FROM emoi_v2_members WHERE conversation_id=?",(old["id"],))
            db.executemany("INSERT INTO emoi_v2_members VALUES(?,?)",[(old["id"],id) for id in ids])
            return {"conversation":view_conversation(db,conversation(db,old["id"]))}

    @app.delete("/emoi/v2/conversations/{conversation_id}")
    async def v2_archive_conversation(conversation_id: str,request: Request):
        auth(request)
        with connect(path) as db:
            old=conversation(db,conversation_id)
            if old["kind"]!="group":
                raise HTTPException(422,"cannot delete the immutable direct conversation")
            db.execute("UPDATE emoi_v2_conversations SET archived=1,updated_at=? WHERE id=?",(now(),old["id"]))
            return {"archived":True,"id":old["id"]}

    @app.post("/emoi/v2/contacts/{contact_id}/proactive")
    async def proactive(contact_id: str, request: Request, background: BackgroundTasks):
        auth(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "主动消息格式无效")
        text = clean_text(body.get("text"), 9000, True)
        event = clean_text(body.get("event_id"), 120, True)
        mode = body.get("mode", "text")
        if mode not in ("text", "voice", "image", "voice_invite", "video_invite"):
            raise HTTPException(422, "主动消息类型无效")
        with connect(path) as db:
            person = contact(db, contact_id)
            profile = json.loads(person["profile"])
            if not profile.get("proactive_enabled"):
                raise HTTPException(403, "此联系人未启用主动消息")
            conversation_row = db.execute("""
              SELECT v.id FROM emoi_v2_conversations v JOIN emoi_v2_members m ON v.id=m.conversation_id
              WHERE m.contact_id=? AND v.kind='direct' AND v.archived=0
            """, (person["id"],)).fetchone()
            if not conversation_row:
                raise HTTPException(404, "联系人会话不可用")
            cid = conversation_row["id"]
            nonce = "proactive:" + event
            prior = db.execute("SELECT id FROM emoi_v2_messages WHERE conversation_id=? AND nonce=?", (cid, nonce)).fetchone()
            if prior:
                return {"id": prior["id"], "duplicate": True}
            recent = db.execute("""
               SELECT created_at FROM emoi_v2_messages WHERE conversation_id=? AND nonce LIKE 'proactive:%'
               ORDER BY rowid DESC LIMIT 1
            """, (cid,)).fetchone()
            if recent and (datetime.now(timezone.utc) - datetime.fromisoformat(recent["created_at"])).total_seconds() < 60:
                raise HTTPException(429, "主动消息过于频繁")
        media = relay.get("contact_media_runtime") or {}
        attachment = None
        if mode == "voice":
            if not profile.get("voice_connection") or not media or len(text) > 900:
                raise HTTPException(422, "请先绑定语音接口，单条语音最多 900 字")
            audio = await asyncio.to_thread(media["voice"], profile["voice_connection"], text)
            attachment = relay["save_upload_bytes"](audio, "message.mp3", "audio/mpeg")
            attachment.update(kind="voice", transcript=text)
        elif mode == "image":
            if not profile.get("image_connection") or not media:
                raise HTTPException(422, "请先绑定生图接口")
            prompt = clean_text(body.get("image_prompt"), 1200, True)
            try:
                attachment = await media["image"](profile["image_connection"], prompt, profile.get("face_reference"))
            except (httpx.HTTPError, ValueError, OSError):
                raise HTTPException(502, "生图接口暂不可用") from None
        elif mode in ("voice_invite", "video_invite"):
            attachment = {"kind": "call_invite", "mode": "video" if mode == "video_invite" else "voice"}
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            if not json.loads(contact(db, contact_id)["profile"]).get("proactive_enabled"):
                raise HTTPException(403, "此联系人未启用主动消息")
            ident = str(uuid4())
            count = db.execute("""
               INSERT OR IGNORE INTO emoi_v2_messages(id,conversation_id,author,contact_id,text,nonce,delivery,created_at,attachment)
               VALUES(?,?,'contact',?,?,?,'generated',?,?)
            """, (ident, cid, person["id"], text, nonce, now(), json.dumps(attachment) if attachment else None)).rowcount
            if not count:
                ident = db.execute("SELECT id FROM emoi_v2_messages WHERE conversation_id=? AND nonce=?",
                                   (cid, nonce)).fetchone()["id"]
        if count and relay.get("push_to_all"):
            summary = {"voice_invite": "邀请你语音通话", "video_invite": "邀请你视频通话"}
            background.add_task(relay["push_to_all"], {
                "title": person["name"], "body": summary.get(mode, "发来一条新消息"), "url": "/", "id": ident,
            })
        return {"id": ident, "duplicate": not count}

    def call_invite(row):
        attachment = json.loads(row["attachment"])
        return {"id": row["id"], "conversation_id": row["conversation_id"],
                "contact_id": row["contact_id"], "name": row["name"],
                "mode": attachment["mode"], "created_at": row["created_at"],
                "remaining_seconds": max(0, 90 - (datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"])).total_seconds())}

    @app.get("/emoi/v2/call-inbox")
    async def call_inbox(request: Request, response: Response):
        auth(request)
        response.headers["Cache-Control"] = "no-store"
        with connect(path) as db:
            row = db.execute("""
                SELECT m.*, c.name FROM emoi_v2_messages m
                JOIN emoi_v2_contacts c ON c.id=m.contact_id AND c.archived=0
                JOIN emoi_v2_conversations v ON v.id=m.conversation_id AND v.archived=0
                WHERE m.call_state IS NULL AND json_extract(m.attachment,'$.kind')='call_invite'
                  AND julianday(m.created_at)>julianday('now','-90 seconds')
                ORDER BY m.rowid DESC LIMIT 1
            """).fetchone()
            return {"invite": call_invite(row) if row else None}

    @app.patch("/emoi/v2/call-inbox/{message_id}")
    async def answer_call(message_id: str, request: Request):
        auth(request)
        body = await request.json()
        action = body.get("action") if isinstance(body, dict) else None
        if action not in ("accept", "decline"):
            raise HTTPException(422, "来电处理方式无效")
        with connect(path) as db:
            changed = db.execute("""
                UPDATE emoi_v2_messages SET call_state=? WHERE id=? AND call_state IS NULL
                  AND json_extract(attachment,'$.kind')='call_invite'
                  AND julianday(created_at)>julianday('now','-90 seconds')
            """, (action, valid_id(message_id))).rowcount
            if not changed:
                raise HTTPException(409, "来电已处理")
        return {"ok": True}

    async def prepare_wake(scope, mode, prompt):
        if mode not in ("image", "voice_invite", "video_invite", "moment"):
            return None
        with connect(path) as db:
            target = wake_target(db, scope)
            config = get_rule(db, target["id"]) if target is not None else autonomy.DEFAULTS
        if target is None:
            return None
        profile = json.loads(target["profile"])
        delivery = {"contact_id": target["id"], "mode": mode}
        if mode in ("voice_invite", "video_invite"):
            delivery["attachment"] = {"kind": "call_invite", "mode": mode.removesuffix("_invite")}
        elif mode == "image" or (mode == "moment" and prompt and config["moment_photo"] != "text"):
            media = relay.get("contact_media_runtime") or {}
            if not prompt or not profile.get("image_connection") or not media:
                return delivery if mode == "moment" else None
            try:
                delivery["attachment"] = await media["image"](profile["image_connection"], prompt, profile.get("face_reference"))
            except (HTTPException, httpx.HTTPError, ValueError, OSError):
                return delivery if mode == "moment" else None
        return delivery

    @app.get("/emoi/v2/conversations/{conversation_id}/messages")
    async def v2_messages(conversation_id:str, request:Request,limit:int=60,reply_to:str=""):
        auth(request)
        limit=max(1,min(limit,100))
        with connect(path) as db:
            conv=conversation(db,conversation_id)
            if reply_to:
                ident = valid_id(reply_to)
                msgs = db.execute("""SELECT * FROM emoi_v2_messages WHERE conversation_id=?
                    AND (id=? OR nonce LIKE ?) ORDER BY rowid DESC""",
                    (conv["id"], ident, "reply:" + ident + ":%")).fetchall()
            else:
                msgs=db.execute("SELECT * FROM emoi_v2_messages WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT ?",(conv["id"],limit)).fetchall()
            return {"messages":[view_message(row) for row in reversed(msgs)],
                    "model_connected": bool(relay.get("loop_base_url") and reply_targets(db, conv["id"])),
                    "replying": any(row["delivery"] == "replying" for row in msgs)}

    @app.get("/emoi/v2/moments")
    async def list_moments(request: Request):
        auth(request)
        with connect(path) as db:
            rows = db.execute("""
                SELECT m.id,m.text,m.created_at AS createdAt,m.contact_id,c.name AS author,m.attachment
                FROM emoi_v2_moments m LEFT JOIN emoi_v2_contacts c ON c.id=m.contact_id
                ORDER BY m.created_at DESC,m.id DESC LIMIT 200
            """)
            posts = []
            for row in rows:
                reactions = db.execute("""
                    SELECT c.name,a.liked,a.comment FROM emoi_moment_reactions a
                    JOIN emoi_v2_contacts c ON c.id=a.contact_id
                    WHERE a.moment_id=? AND a.done=1 ORDER BY a.due,a.contact_id
                """, (row["id"],))
                posts.append({**dict(row), "attachment": json.loads(row["attachment"]) if row["attachment"] else None,
                              "reactions": [dict(reaction) for reaction in reactions]})
            return {"posts": posts}

    @app.post("/emoi/v2/moments")
    async def publish_moment(request: Request):
        auth(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "动态格式无效")
        ident = valid_id(body.get("id"))
        attachment = saved_picture(body.get("photo_id"))
        text = clean_text(body.get("text", ""), 1000, not attachment)
        with connect(path) as db:
            inserted = db.execute("INSERT OR IGNORE INTO emoi_v2_moments(id,text,created_at,attachment) VALUES(?,?,?,?)",
                                  (ident, text, now(), json.dumps(attachment) if attachment else None)).rowcount
            if inserted:
                autonomy.enqueue_reactions(db, ident, time.time())
            row = db.execute("SELECT id,text,created_at AS createdAt,attachment FROM emoi_v2_moments WHERE id=?", (ident,)).fetchone()
        return {"post": {**dict(row), "attachment": json.loads(row["attachment"]) if row["attachment"] else None}}

    @app.delete("/emoi/v2/moments/{moment_id}")
    async def delete_moment(moment_id: str, request: Request):
        auth(request)
        with connect(path) as db:
            db.execute("DELETE FROM emoi_v2_moments WHERE id=?", (valid_id(moment_id),))
        return {"ok": True}

    @app.post("/emoi/v2/conversations/{conversation_id}/messages")
    async def v2_save_message(conversation_id:str,request:Request,background:BackgroundTasks):
        auth(request)
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(422,"invalid message")
        attachment=message_attachment(body.get("attachment"))
        text=clean_text(body.get("text", ""),10000,not attachment)
        nonce=clean_text(body.get("nonce"),100,True)
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,100}",nonce):
            raise HTTPException(422,"invalid nonce")
        with connect(path) as db:
            conv=conversation(db,conversation_id)
            old=db.execute("SELECT * FROM emoi_v2_messages WHERE conversation_id=? AND nonce=?",(conv["id"],nonce)).fetchone()
            if old:
                return {"message":view_message(old),"already_saved":True}
        if attachment and attachment["kind"] == "voice" and relay.get("VOICE_TRANSCRIBE_CMD"):
            audio = relay["UPLOAD_DIR"] / attachment["url"].split("/")[-1]
            transcript = await asyncio.to_thread(relay["transcribe_with_command"], audio, attachment["mime"])
            if transcript:
                attachment["transcript"] = transcript[:3000]
        if not text:
            text = attachment.get("transcript") or "[" + MEDIA_LABELS[attachment["kind"]] + "]"
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            conv=conversation(db,conversation_id)
            old=db.execute("SELECT * FROM emoi_v2_messages WHERE conversation_id=? AND nonce=?",(conv["id"],nonce)).fetchone()
            if old:
                return {"message":view_message(old),"already_saved":True}
            if db.execute("SELECT 1 FROM emoi_v2_messages WHERE conversation_id=? AND delivery='replying'", (conv["id"],)).fetchone():
                raise HTTPException(409, "请等这轮 AI 回复结束")
            recipients = reply_targets(db, conv["id"]) if relay.get("loop_base_url") else []
            mid=str(uuid4())
            db.execute("""
              INSERT INTO emoi_v2_messages(id,conversation_id,author,contact_id,text,nonce,delivery,created_at,attachment)
              VALUES(?,?,'human',NULL,?,?,?,?,?)
            """, (mid,conv["id"],text,nonce,"replying" if recipients else "stored_not_delivered",now(),
                  json.dumps(attachment, ensure_ascii=False) if attachment else None))
            row=db.execute("SELECT * FROM emoi_v2_messages WHERE id=?",(mid,)).fetchone()
        if recipients:
            mode = body.get("call_mode")
            mode = mode if mode in ("voice", "video") else ""
            background.add_task(generate_replies, conv["id"], mid, recipients, body.get("voice_reply") is True, mode)
        return {"message":view_message(row),"model_dispatched":bool(recipients)}

    return {"init":lambda:init(path), "store_wake":store_wake_message, "prepare_wake":prepare_wake, "watch":watch}
