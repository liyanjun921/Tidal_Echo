"""Luné rooms and memory, extending Tidal Echo's relay without replacing it.

Single-owner deployment: all public routes use the relay's existing auth.
Model-visible memory is filtered again in api_loop; browser filters are not ACLs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import HTTPException, Request
try:
    from .lune_memory import MemoryStore, init as init_memory
except ImportError:
    from lune_memory import MemoryStore, init as init_memory
try:
    from .workspace import validate as validate_workspace, view as workspace_view
except ImportError:
    from workspace import validate as validate_workspace, view as workspace_view

ROOMS = {"gpt": ["gpt"], "claude": ["claude"], "group": ["gpt", "claude"]}
SCOPES = {"shared", "gpt", "claude", "group"}


def now():
    return datetime.now(timezone.utc).isoformat()


def init(db_path):
    with sqlite3.connect(db_path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS lune_memories (
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, title TEXT NOT NULL,
            content TEXT NOT NULL, source_message_id INTEGER, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            deleted INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS lune_memory_revisions (
            memory_id TEXT NOT NULL, version INTEGER NOT NULL, snapshot TEXT NOT NULL,
            PRIMARY KEY(memory_id, version)
        );
        CREATE TABLE IF NOT EXISTS lune_runs (
            id TEXT PRIMARY KEY, room TEXT NOT NULL, nonce TEXT NOT NULL UNIQUE,
            message_id INTEGER NOT NULL, targets TEXT NOT NULL, state TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS lune_runs_room ON lune_runs(room, created_at);
        CREATE INDEX IF NOT EXISTS lune_memory_scope ON lune_memories(scope, deleted);
        CREATE TABLE IF NOT EXISTS lune_imports (digest TEXT PRIMARY KEY, created_at TEXT NOT NULL);
        """)
        # A restart does not prove a tool or upstream request was not executed.
        # Leave interrupted work inspectable; never automatically replay it.
        c.execute("UPDATE lune_runs SET state='interrupted', error='服务已重启，请核对已有回复后继续', updated_at=? WHERE state IN ('pending','running')", (now(),))
    init_memory(db_path)


def memory_context(db_path, room, agent, query, budget=4000):
    """Read only explicitly permitted scopes. Keep raw messages untouched."""
    allowed = ["shared"]
    if room == "lune-group":
        allowed.append("group")
    elif room == "lune-" + agent and agent in {"gpt", "claude"}:
        allowed.append(agent)
    else:
        return ""
    with sqlite3.connect(db_path) as c:
        c.row_factory = sqlite3.Row
        try:
            rows = c.execute("SELECT m.* FROM lune_memories m LEFT JOIN lune_memory_details d ON d.memory_id=m.id WHERE m.deleted=0 AND COALESCE(d.status,'current')='current' AND m.scope IN (" + ",".join("?" for _ in allowed) + ") ORDER BY m.updated_at DESC LIMIT 300", allowed).fetchall()
        except sqlite3.OperationalError:
            return ""
    words = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2}", query.lower()))
    ranked = sorted(rows, key=lambda r: sum(w in (r["title"] + r["content"]).lower() for w in words), reverse=True)
    selected, used = [], 0
    for r in ranked[:8]:
        line = f"[{r['id']} · {r['scope']} · {r['updated_at']}] {r['title']}：{r['content']}"
        if used + len(line) > budget:
            continue
        selected.append(line)
        used += len(line)
    return "\n".join(selected)


def register(app, relay):
    tasks = {}
    locks = {room: asyncio.Lock() for room in ROOMS}
    db_path = relay["DB_PATH"]

    def connect():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    def room_check(room):
        if room not in ROOMS:
            raise HTTPException(404, "会话不存在")

    def run_view(row):
        return dict(row) if row else None

    def update_run(rid, state, error=""):
        with connect() as c:
            c.execute("UPDATE lune_runs SET state=?,error=?,updated_at=? WHERE id=?", (state, error, now(), rid))

    async def run(rid, room, msg, targets):
        update_run(rid, "running")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10), trust_env=False) as client:
                for agent in targets:
                    # In group chat later agents must see the earlier agent's completed reply.
                    # The loop excludes only this current user row, not newer completed replies.
                    resp = await client.post(relay["LOOP_INGEST_URL"], json={
                        "id": msg["id"], "text": msg["text"], "session_id": "lune-" + room,
                        "agent_id": agent, "run_id": rid,
                        "attachments": msg["meta"].get("attachments", []),
                    })
                    if resp.status_code != 200 or not resp.json().get("ok"):
                        raise RuntimeError("model_turn_failed")
                    try:
                        try:from .lune_xinchao import queue_exchange
                        except ImportError:from lune_xinchao import queue_exchange
                        queue_exchange(db_path,room,agent,msg,rid)
                    except (OSError,ValueError,sqlite3.Error):
                        print('心潮回流暂未入队；原聊天已保存')
            update_run(rid, "completed")
        except asyncio.CancelledError:
            update_run(rid, "cancelled", "已停止等待；已执行的工具操作不会撤销")
            raise
        except Exception:
            update_run(rid, "failed", "模型服务未完成，请检查模型设置和已保存的回复")
        finally:
            tasks.pop(rid, None)
            await relay["broadcast"](relay["app_subs"], {"type": "lune_run", "room": room, "run_id": rid})

    @app.get("/lune/rooms")
    async def rooms(request: Request):
        relay["check_auth"](request)
        return {"rooms": [{"id": k, "participants": v} for k, v in ROOMS.items()]}

    @app.get("/lune/rooms/{room}/messages")
    async def messages(room: str, request: Request, before: int = 0, after: int = 0, limit: int = 40):
        relay["check_auth"](request)
        room_check(room)
        limit = max(1, min(limit, 100))
        where = ["json_extract(meta,'$.api_session')=?"]
        params = ["lune-" + room]
        if before:
            where.append("id<?"); params.append(before)
        if after:
            where.append("id>?"); params.append(after)
        order = "ASC" if after else "DESC"
        with connect() as c:
            rows = c.execute("SELECT * FROM messages WHERE " + " AND ".join(where) + f" ORDER BY id {order} LIMIT ?", params + [limit]).fetchall()
            runs = c.execute("SELECT * FROM lune_runs WHERE room=? ORDER BY created_at DESC LIMIT 5", (room,)).fetchall()
        rows = rows if after else list(reversed(rows))
        msgs = [relay["app_payload"](m) for m in relay["rows_to_messages"](rows)]
        return {"messages": msgs, "has_more": len(rows) == limit, "runs": [run_view(r) for r in runs]}

    @app.post("/lune/rooms/{room}/send")
    async def send(room: str, request: Request):
        relay["check_auth"](request)
        room_check(room)
        body = await request.json()
        text = str(body.get("text") or "").strip()
        nonce = str(body.get("nonce") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,100}", nonce):
            raise HTTPException(422, "缺少有效的发送编号")
        atts = body.get("attachments", [])
        if not isinstance(atts, list) or len(atts) > 8 or len(text) > 24000 or (not text and not atts):
            raise HTTPException(422, "消息或附件格式不正确")
        # Only accept uploads already held by this owner's relay, never client paths or arbitrary URLs.
        cleaned = []
        for att in atts:
            if not isinstance(att, dict):
                raise HTTPException(422, "附件格式不正确")
            path = str(att.get("url") or "")
            prefix = relay["PUBLIC_PREFIX"] + "/uploads/"
            if not path.startswith(prefix) or "?" in path:
                raise HTTPException(422, "附件来源不正确")
            name = path[len(prefix):]
            if Path(name).name != name or not (relay["UPLOAD_DIR"] / name).is_file():
                raise HTTPException(422, "附件不存在")
            cleaned.append({k: att.get(k) for k in ("url", "name", "mime", "size")})
        targets = ROOMS[room]
        if room == "group":
            requested = body.get("targets")
            if requested is not None:
                if not isinstance(requested, list) or not requested or any(t not in ROOMS[room] for t in requested):
                    raise HTTPException(422, "群聊回复对象不正确")
                targets = list(dict.fromkeys(requested))
            else:
                named = re.findall(r"@(gpt|claude)\b", text, re.I)
                if named:
                    targets = list(dict.fromkeys(x.lower() for x in named))
        async with locks[room]:
            with connect() as c:
                c.execute("BEGIN IMMEDIATE")
                old = c.execute("SELECT * FROM lune_runs WHERE nonce=?", (nonce,)).fetchone()
                if old:
                    if old["room"] != room:
                        raise HTTPException(409, "发送编号属于另一个会话")
                    return {"id": old["message_id"], "run": run_view(old), "duplicate": True}
                active = c.execute("SELECT id FROM lune_runs WHERE room=? AND state IN ('pending','running')", (room,)).fetchone()
                if active:
                    raise HTTPException(409, "这个会话仍在回复，请稍候或停止")
                ts, rid = now(), uuid.uuid4().hex
                meta = {"api_session": "lune-" + room, "nonce": nonce, "attachments": cleaned}
                cur = c.execute("INSERT INTO messages(ts,direction,kind,text,meta) VALUES(?,?,?,?,?)", (ts, "in", "user", text, json.dumps(meta, ensure_ascii=False)))
                mid = cur.lastrowid
                c.execute("INSERT INTO lune_runs VALUES(?,?,?,?,?,?,?,?,?)", (rid, room, nonce, mid, json.dumps(targets), "pending", "", ts, ts))
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='lune_wren_settings'").fetchone():
                    try:
                        from .lune_wren import SCOPES as BODY_SCOPES,config as body_config,sync_anchor,advance_body
                    except ImportError:
                        from lune_wren import SCOPES as BODY_SCOPES,config as body_config,sync_anchor,advance_body
                    import time
                    clock=time.time()
                    for scope,pair in BODY_SCOPES.items():
                        if pair[0]==room:
                            cfg=body_config(c,scope)
                            sync_anchor(c,scope,cfg,clock)
                            advance_body(c,scope,cfg,clock)
                c.commit()
            msg = {"id": mid, "ts": ts, "direction": "in", "kind": "user", "text": text, "meta": meta}
            tasks[rid] = asyncio.create_task(run(rid, room, msg, targets))
            await relay["broadcast"](relay["app_subs"], relay["app_payload"](msg))
            return {"id": mid, "run": {"id": rid, "state": "pending", "room": room}}

    @app.post("/lune/runs/{rid}/stop")
    async def stop(rid: str, request: Request):
        relay["check_auth"](request)
        task = tasks.get(rid)
        if task:
            update_run(rid, "cancelled", "已停止等待；已执行的工具操作不会撤销")
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        with connect() as c:
            row = c.execute("SELECT * FROM lune_runs WHERE id=?", (rid,)).fetchone()
        if not row:
            raise HTTPException(404, "请求不存在")
        return {"run": run_view(row)}

    @app.get("/lune/memories")
    async def memories(request: Request):
        relay["check_auth"](request)
        return {"memories": MemoryStore(db_path).list(history=request.query_params.get("history") == "1")}

    def memory_body(body):
        if not isinstance(body, dict):
            raise HTTPException(422, "记忆内容必须是对象")
        scope = body.get("scope")
        title, content = str(body.get("title") or "").strip(), str(body.get("content") or "").strip()
        if scope not in SCOPES or not title or not content or len(title) > 120 or len(content) > 12000:
            raise HTTPException(422, "请填写有效的标题、内容和记忆范围")
        source = body.get("source_message_id")
        if source is not None and (isinstance(source, bool) or not isinstance(source, int)):
            raise HTTPException(422, "原文编号不正确")
        if source is not None:
            with connect() as c:
                row = c.execute("SELECT direction FROM messages WHERE id=?", (source,)).fetchone()
            if not row or row["direction"] != "in":
                raise HTTPException(422, "记忆出处须为已有的用户消息")
        return scope, title, content, source

    @app.post("/lune/memories")
    async def create_memory(request: Request):
        relay["check_auth"](request)
        body = await request.json()
        return {"memory": MemoryStore(db_path).save(memory_body(body), body)}

    @app.patch("/lune/memories/{mid}")
    async def edit_memory(mid: str, request: Request):
        relay["check_auth"](request)
        body = await request.json()
        values = memory_body(body)
        return {"memory": MemoryStore(db_path).save(values, body, mid)}

    @app.delete("/lune/memories/{mid}")
    async def delete_memory(mid: str, request: Request, version: int):
        relay["check_auth"](request)
        return MemoryStore(db_path).delete(mid, version)

    @app.get("/lune/memories/{mid}/revisions")
    async def memory_revisions(mid: str, request: Request):
        relay["check_auth"](request)
        with connect() as c:
            rows = c.execute("SELECT version,snapshot FROM lune_memory_revisions WHERE memory_id=? ORDER BY version DESC", (mid,)).fetchall()
        return {"revisions": [{"version": r["version"], "snapshot": json.loads(r["snapshot"])} for r in rows]}

    @app.get("/lune/export")
    async def export(request: Request):
        relay["check_auth"](request)
        with connect() as c:
            msgs = c.execute("SELECT * FROM messages WHERE json_extract(meta,'$.api_session') IN ('lune-gpt','lune-claude','lune-group') ORDER BY id").fetchall()
            mem = MemoryStore.rows(c)
            memory_loops = [dict(r) for r in c.execute("SELECT * FROM lune_memory_loops WHERE status='open'")]
            workspace = c.execute("SELECT * FROM lune_workspace WHERE deleted=0").fetchall()
        return {"format": "lune-v04", "memory_format": "lune-latent-v1", "memory_loops": memory_loops, "exported_at": now(), "messages": [relay["app_payload"](m) for m in relay["rows_to_messages"](msgs)], "memories": mem, "workspace": [workspace_view(r) for r in workspace], "media_note": "JSON 含记忆状态、变迁链与当前未完事项；附件二进制、审计历史与已删除资料需备份私人数据库"}

    @app.post("/lune/import")
    async def restore(request: Request):
        relay["check_auth"](request)
        raw = await request.body()
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(413, "备份超过 20 MB，请拆分后导入")
        try:
            body = json.loads(raw)
        except (ValueError, TypeError):
            raise HTTPException(422, "备份不是有效 JSON")
        if not isinstance(body, dict) or body.get("format") not in {"lune-v03", "lune-v04", "lune-local-v04"}:
            raise HTTPException(422, "无法识别的备份格式")
        source = body.get("data", body)
        if not isinstance(source, dict):
            raise HTTPException(422, "备份内容格式不正确")
        messages, memories = source.get("messages", {}), source.get("memories", [])
        workspace = source.get("workspace", [])
        if not isinstance(workspace, list) or len(workspace) > 2000:
            raise HTTPException(422, "生活页备份格式不正确")
        validated_workspace = [(str(item.get("id", "")), validate_workspace(item)) for item in workspace if isinstance(item, dict) and not item.get("demo")]
        workspace_keys = [mid for mid, _ in validated_workspace]
        if any(not mid for mid in workspace_keys) or len(set(workspace_keys)) != len(workspace_keys):
            raise HTTPException(422, "生活页备份编号缺失或重复")
        if any(not isinstance(item, dict) for item in workspace):
            raise HTTPException(422, "生活页条目格式不正确")
        normalized = []

        def imported_meta(message):
            meta = message.get("meta", {})
            if not isinstance(meta, dict):
                raise HTTPException(422, "消息资料格式不正确")
            result = {}
            if "attachments" in meta:
                atts = meta["attachments"]
                if not isinstance(atts, list) or len(atts) > 8:
                    raise HTTPException(422, "附件索引格式不正确")
                cleaned = []
                for att in atts:
                    if not isinstance(att, dict) or not re.fullmatch(r"/[\w/-]*uploads/[^/?#]+", str(att.get("url", ""))):
                        raise HTTPException(422, "备份附件来源不正确")
                    cleaned.append({k: att.get(k) for k in ("url", "name", "mime", "size")})
                result["attachments"] = cleaned
            if message.get("kind") == "act" and isinstance(meta.get("steps"), list):
                result["steps"] = meta["steps"]
            return result

        if isinstance(messages, dict):
            for room, rows in messages.items():
                if room not in ROOMS or not isinstance(rows, list):
                    raise HTTPException(422, "会话格式不正确")
                for m in rows:
                    if not isinstance(m, dict) or m.get("role") not in {"user", "gpt", "claude"}:
                        raise HTTPException(422, "消息作者不正确")
                    normalized.append({"old_id": m.get("id"), "room": room, "direction": "in" if m["role"] == "user" else "out", "kind": "act" if m.get("kind") == "act" else ("user" if m["role"] == "user" else "reply"), "text": m.get("text", ""), "ts": m.get("ts"), "meta": {**imported_meta(m), "agent_id": m["role"] if m["role"] != "user" else ""}})
        elif isinstance(messages, list):
            for m in messages:
                if not isinstance(m, dict) or not isinstance(m.get("meta", {}), dict):
                    raise HTTPException(422, "消息格式不正确")
                meta = m.get("meta", {}) if isinstance(m, dict) else {}
                room = str(meta.get("api_session", "")).removeprefix("lune-")
                if room not in ROOMS or m.get("from") not in {"human", "ai"}:
                    raise HTTPException(422, "消息范围不正确")
                normalized.append({"old_id": m.get("id"), "room": room, "direction": "in" if m["from"] == "human" else "out", "kind": "act" if m.get("kind") == "act" else ("user" if m["from"] == "human" else "reply"), "text": m.get("text", ""), "ts": m.get("ts"), "meta": {**imported_meta(m), "agent_id": meta.get("agent_id", "")}})
        else:
            raise HTTPException(422, "消息格式不正确")
        if len(normalized) > 50000 or not isinstance(memories, list) or len(memories) > 2000:
            raise HTTPException(422, "备份条目过多")
        validated_mem = []
        memory_sources = []
        memory_metadata = []
        for m in memories:
            if not isinstance(m, dict):
                raise HTTPException(422, "记忆格式不正确")
            if m.get("demo"):
                continue
            validated_mem.append(memory_body({**m, "source_message_id": None}))
            memory_sources.append(m.get("source_message_id"))
            state, status, reason = m.get("current_state", "未补充；从旧备份导入"), m.get("status", "current"), m.get("reason", "")
            if not isinstance(state, str) or len(state) > 1500 or status not in {"current", "superseded", "retracted"} or not isinstance(reason, str) or len(reason) > 1000:
                raise HTTPException(422, "备份中的记忆状态不正确")
            memory_metadata.append({**m, "current_state": state, "status": status, "reason": reason})
            for key in ("id", "supersedes", "superseded_by"):
                if m.get(key) is not None and (not isinstance(m[key], str) or len(m[key]) > 100):
                    raise HTTPException(422, "备份记忆编号不正确")
            for key in ("created_at", "updated_at"):
                try:
                    dt = datetime.fromisoformat(str(m.get(key) or now()).replace("Z", "+00:00"))
                    memory_metadata[-1][key] = dt.replace(tzinfo=dt.tzinfo or timezone.utc).isoformat()
                except (ValueError, TypeError):
                    raise HTTPException(422, "备份记忆时间不正确")
        keys = [m.get("id") for m in memory_metadata if m.get("id")]
        if len(set(keys)) != len(keys):
            raise HTTPException(422, "备份记忆编号重复")
        meta_by_id = {m.get("id"): m for m in memory_metadata if m.get("id")}
        for m in memory_metadata:
            for link in ("supersedes", "superseded_by"):
                target = m.get(link)
                if target and (target not in meta_by_id or meta_by_id[target]["scope"] != m["scope"]):
                    raise HTTPException(422, "备份记忆变迁链断裂或跨范围")
            seen, cursor = set(), m.get("id")
            while cursor:
                if cursor not in meta_by_id:
                    raise HTTPException(422, "备份记忆变迁链断裂")
                if cursor in seen:
                    raise HTTPException(422, "备份记忆变迁链成环")
                seen.add(cursor)
                cursor = meta_by_id[cursor].get("supersedes")
        loop_backup = source.get("memory_loops", [])
        if not isinstance(loop_backup, list) or len(loop_backup) > 2000:
            raise HTTPException(422, "未完事项备份不正确")
        for item in loop_backup:
            if not isinstance(item, dict) or item.get("scope") not in SCOPES or not isinstance(item.get("summary"), str) or not 0 < len(item["summary"]) <= 1000:
                raise HTTPException(422, "未完事项备份不正确")
        for m in normalized:
            if not isinstance(m["text"], str) or len(m["text"]) > 100000:
                raise HTTPException(422, "备份包含过长消息")
            if m["ts"]:
                try:
                    datetime.fromisoformat(m["ts"].replace("Z", "+00:00"))
                except (ValueError, TypeError, AttributeError):
                    raise HTTPException(422, "备份日期不正确")
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT 1 FROM lune_imports WHERE digest=?", (digest,)).fetchone():
                return {"ok": True, "duplicate": True, "messages": 0, "memories": 0}
            if c.execute("SELECT 1 FROM lune_runs WHERE state IN ('pending','running')").fetchone():
                raise HTTPException(409, "请等待回复结束后再导入")
            source_ids = {}
            for m in normalized:
                meta = {**m["meta"], "api_session": "lune-" + m["room"], "imported": True, "date_unknown": not bool(m["ts"])}
                cur = c.execute("INSERT INTO messages(ts,direction,kind,text,meta) VALUES(?,?,?,?,?)", (m["ts"] or now(), m["direction"], m["kind"], m["text"], json.dumps(meta, ensure_ascii=False)))
                if m["old_id"] is not None and m["direction"] == "in":
                    source_ids[str(m["old_id"])] = cur.lastrowid
            memory_ids = {key: uuid.uuid4().hex for key in keys}
            for values, original_source, metadata in zip(validated_mem, memory_sources, memory_metadata):
                ts = now()
                values = (*values[:3], source_ids.get(str(original_source)))
                mid = memory_ids.get(metadata.get("id"), uuid.uuid4().hex)
                c.execute("INSERT INTO lune_memories VALUES(?,?,?,?,?,?,?,?,?)", (mid, *values, metadata["created_at"], metadata["updated_at"], 1, 0))
                c.execute("INSERT INTO lune_memory_details(memory_id,current_state,status,supersedes,superseded_by,reason,author) VALUES(?,?,?,?,?,?,?)", (mid, metadata["current_state"], metadata["status"], memory_ids.get(metadata.get("supersedes")), memory_ids.get(metadata.get("superseded_by")), metadata["reason"], "imported"))
            for item in loop_backup:
                ts = now()
                c.execute("INSERT INTO lune_memory_loops VALUES(?,?,?,?,?,?,?,1)", (uuid.uuid4().hex, item["scope"], item["summary"], "open", source_ids.get(str(item.get("source_message_id"))), ts, ts))
            workspace_ids = {old_id: uuid.uuid4().hex for old_id, _ in validated_workspace}
            for old_id, item in sorted(validated_workspace, key=lambda x: x[1]["kind"] == "annotation"):
                ts = now()
                if item["kind"] == "annotation":
                    original_book = item["data"]["book_id"]
                    book_id = workspace_ids.get(original_book, original_book)
                    book = c.execute("SELECT scope FROM lune_workspace WHERE id=? AND kind='book' AND deleted=0", (book_id,)).fetchone()
                    if not book or book["scope"] != item["scope"]:
                        raise HTTPException(422, "批注缺少对应范围的书籍")
                    item["data"]["book_id"] = book_id
                c.execute("INSERT INTO lune_workspace VALUES(?,?,?,?,?,?,?,?,?,?,0)", (workspace_ids[old_id], item["kind"], item["scope"], item["title"], item["content"], json.dumps(item["data"], ensure_ascii=False), "imported", ts, ts, 1))
            c.execute("INSERT INTO lune_imports VALUES(?,?)", (digest, now()))
        return {"ok": True, "messages": len(normalized), "memories": len(validated_mem), "workspace": len(validated_workspace)}

    return {"tasks": tasks, "init": lambda: init(db_path)}
