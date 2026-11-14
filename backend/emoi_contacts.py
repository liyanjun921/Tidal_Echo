"""Émoi v2 multi-AI identity registry and safely separated conversations.

Every route requires the existing relay owner bearer authentication.
Creates additive tables; legacy gpt/claude/group messages are untouched.
Replies use explicit API bindings and the history of this conversation only.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from fastapi import BackgroundTasks, HTTPException, Request

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
MODEL_ROUTES = {"default", "gpt", "claude"}
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
        db.execute("UPDATE emoi_v2_messages SET delivery='interrupted' WHERE delivery='replying'")


def register(app, relay):
    path = relay["DB_PATH"]

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

    def view_contact(row):
        return {
            "id": row["id"], "name": row["name"], "notes": row["notes"],
            "model_route": row["model_route"], "memory_namespace": row["memory_namespace"],
            "desire_namespace": row["desire_namespace"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "connected": False,
            "memory_connected": False, "desire_connected": False,
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
        return {"kind": kind, "url": "/uploads/" + stored, "mime": mime,
                "size": (path / stored).stat().st_size, "name": MEDIA_LABELS[kind]}

    def model_members(db, cid):
        return db.execute("""
          SELECT c.* FROM emoi_v2_members m JOIN emoi_v2_contacts c ON c.id=m.contact_id
          WHERE m.conversation_id=? AND c.archived=0 ORDER BY m.rowid
        """, (cid,)).fetchall()

    def reply_targets(db, cid):
        return [member for member in model_members(db, cid) if member["model_route"] in MODEL_ROUTES]

    async def generate_replies(cid, message_id, recipients, voice_reply=False):
        completed = 0
        try:
            url = relay["loop_base_url"]() + "/loop/contact-reply"
            async with httpx.AsyncClient(timeout=31, trust_env=False) as client:
                for recipient in recipients:
                    with connect(path) as db:
                        active = {m["id"]: m for m in reply_targets(db, cid)}
                        if not db.execute("SELECT 1 FROM emoi_v2_conversations WHERE id=? AND archived=0", (cid,)).fetchone():
                            break
                        current = active.get(recipient["id"])
                        if not current or current["model_route"] != recipient["model_route"]:
                            continue
                        rows = db.execute("""
                          SELECT m.id, m.author, m.contact_id, m.text, m.attachment, c.name
                          FROM emoi_v2_messages m LEFT JOIN emoi_v2_contacts c ON c.id=m.contact_id
                          WHERE m.conversation_id=? ORDER BY m.rowid DESC LIMIT 40
                        """, (cid,)).fetchall()
                    history = [dict(row) for row in reversed(rows)]
                    for entry in history:
                        attachment = entry.pop("attachment")
                        if attachment and entry["id"] == message_id:
                            entry["attachment"] = json.loads(attachment)
                    try:
                        response = await client.post(url, json={
                            "route": current["model_route"], "contact_id": current["id"],
                            "name": current["name"], "notes": current["notes"], "history": history,
                        })
                        response.raise_for_status()
                        text = clean_text(response.json().get("text"), 10000, True)
                    except (httpx.HTTPError, ValueError, HTTPException):
                        continue
                    audio = None
                    if voice_reply and len(text) <= 900 and relay.get("speech_runtime"):
                        try:
                            data = await asyncio.to_thread(relay["speech_runtime"]["synthesize"], {"text": text})
                            audio = relay["save_upload_bytes"](data, "reply.mp3", "audio/mpeg")
                            audio.update(kind="voice", transcript=text)
                        except (HTTPException, OSError, ValueError):
                            pass
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
                        db.execute("""
                          INSERT INTO emoi_v2_messages(id,conversation_id,author,contact_id,text,nonce,delivery,created_at,attachment)
                          VALUES(?,?,'contact',?,?,?,'generated',?,?)
                        """, (str(uuid4()), cid, current["id"], text, "reply:"+message_id+":"+current["id"], now(),
                              json.dumps(audio, ensure_ascii=False) if audio else None))
                        completed += 1
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
            "created_at":row["created_at"],"connected":False,
        }

    @app.get("/emoi/v2/contacts")
    async def v2_list_contacts(request: Request):
        auth(request)
        with connect(path) as db:
            rows=db.execute("SELECT * FROM emoi_v2_contacts WHERE archived=0 ORDER BY created_at").fetchall()
            return {"contacts":[view_contact(row) for row in rows]}

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
            count=db.execute("SELECT COUNT(*) FROM emoi_v2_contacts WHERE archived=0").fetchone()[0]
            if count>=MAX_CONTACTS:raise HTTPException(409,"contact limit reached")
            try:
                db.execute("INSERT INTO emoi_v2_contacts(id,name,notes,model_route,memory_namespace,desire_namespace,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (cid,name,notes,route,"contact:"+cid, "desire:contact:"+cid,timestamp,timestamp))
            except sqlite3.IntegrityError:
                raise HTTPException(409,"contact id already exists") from None
            # Each contact begins with an independent direct conversation.
            conv=str(uuid4())
            db.execute("INSERT INTO emoi_v2_conversations(id,kind,title,memory_namespace,created_at,updated_at) VALUES(?,'direct',?,?,?,?)",
                (conv,name,"conversation:"+conv,timestamp,timestamp))
            db.execute("INSERT INTO emoi_v2_members VALUES(?,?)",(conv,cid))
            return {"contact":view_contact(contact(db,cid)),
                    "conversation_id":conv}

    @app.patch("/emoi/v2/contacts/{contact_id}")
    async def v2_edit_contact(contact_id: str, request: Request):
        auth(request)
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(422,"invalid contact")
        with connect(path) as db:
            old=contact(db,contact_id)
            name=clean_text(body.get("name",old["name"]),60,True)
            notes=clean_text(body.get("notes",old["notes"]),5000)
            route=clean_text(body.get("model_route",old["model_route"]),100)
            # Never accept arbitrary memory/desire scope changes from the browser.
            db.execute("UPDATE emoi_v2_contacts SET name=?,notes=?,model_route=?,updated_at=? WHERE id=?",
                (name,notes,route,now(),old["id"]))
            return {"contact":view_contact(contact(db,old["id"]))}

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
            db.execute("UPDATE emoi_v2_conversations SET title=?,updated_at=? WHERE id=?",(title,now(),old["id"]))
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

    @app.get("/emoi/v2/conversations/{conversation_id}/messages")
    async def v2_messages(conversation_id:str, request:Request,limit:int=60):
        auth(request)
        limit=max(1,min(limit,100))
        with connect(path) as db:
            conv=conversation(db,conversation_id)
            msgs=db.execute("SELECT * FROM emoi_v2_messages WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT ?",(conv["id"],limit)).fetchall()
            return {"messages":[view_message(row) for row in reversed(msgs)],
                    "model_connected": bool(relay.get("loop_base_url") and reply_targets(db, conv["id"])),
                    "replying": any(row["delivery"] == "replying" for row in msgs)}

    @app.get("/emoi/v2/moments")
    async def list_moments(request: Request):
        auth(request)
        with connect(path) as db:
            rows = db.execute("SELECT id,text,created_at AS createdAt FROM emoi_v2_moments ORDER BY created_at DESC,id DESC LIMIT 200")
            return {"posts": [dict(row) for row in rows]}

    @app.post("/emoi/v2/moments")
    async def publish_moment(request: Request):
        auth(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "动态格式无效")
        ident = valid_id(body.get("id"))
        text = clean_text(body.get("text"), 1000, True)
        with connect(path) as db:
            db.execute("INSERT OR IGNORE INTO emoi_v2_moments VALUES(?,?,?)", (ident, text, now()))
            row = db.execute("SELECT id,text,created_at AS createdAt FROM emoi_v2_moments WHERE id=?", (ident,)).fetchone()
        return {"post": dict(row)}

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
            background.add_task(generate_replies, conv["id"], mid, recipients, body.get("voice_reply") is True)
        return {"message":view_message(row),"model_dispatched":bool(recipients)}

    return {"init":lambda:init(path)}
