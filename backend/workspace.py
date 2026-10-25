"""Luné living pages: owner CRUD and room-scoped assistant tools.

Independent implementation informed by fang-claude's documented feature model.
Uses Tidal Echo's existing authenticated relay and SQLite database.
"""
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone

from fastapi import HTTPException, Request

KINDS = {"journal", "todo", "event", "whisper", "book", "annotation", "report", "health"}
SCOPES = {"shared", "gpt", "claude", "group"}


def now():
    return datetime.now(timezone.utc).isoformat()


def init(path):
    with sqlite3.connect(path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS lune_workspace (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, scope TEXT NOT NULL,
          title TEXT NOT NULL, content TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
          author TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          version INTEGER NOT NULL DEFAULT 1, deleted INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS lune_workspace_scope ON lune_workspace(kind,scope,deleted);
        """)


def validate(body):
    if not isinstance(body, dict):
        raise HTTPException(422, "内容格式不正确")
    kind, scope = body.get("kind"), body.get("scope", "shared")
    title, content, data = body.get("title", ""), body.get("content", ""), body.get("data", {})
    if kind not in KINDS or scope not in SCOPES:
        raise HTTPException(422, "页面类型或可见范围不正确")
    if not isinstance(title, str) or not title.strip() or len(title) > 160:
        raise HTTPException(422, "请填写 160 字符以内的标题")
    if not isinstance(content, str) or len(content) > (1000000 if kind == "book" else 24000):
        raise HTTPException(422, "内容超过本页保存上限")
    if not isinstance(data, dict) or len(json.dumps(data, ensure_ascii=False)) > 8000:
        raise HTTPException(422, "附加资料格式不正确")
    for key in ("date", "due"):
        if data.get(key):
            try:
                date.fromisoformat(data[key])
            except (ValueError, TypeError):
                raise HTTPException(422, "日期格式应为 YYYY-MM-DD")
    if data.get("time") and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(data["time"])):
        raise HTTPException(422, "时间格式应为 HH:MM")
    if "done" in data and not isinstance(data["done"], bool):
        raise HTTPException(422, "完成状态不正确")
    if kind == "todo" and data.get("owner", "user") not in {"user", "gpt", "claude"}:
        raise HTTPException(422, "待办归属不正确")
    if kind == "annotation" and (not isinstance(data.get("book_id"), str) or not isinstance(data.get("quote"), str)):
        raise HTTPException(422, "批注缺少书籍和引文")
    if kind == "annotation" and (not data["quote"].strip() or len(data["quote"]) > 2000 or "para" in data and (type(data["para"]) is not int or data["para"] < 0)):
        raise HTTPException(422, "批注引文或段落不正确")
    if kind == "book" and ("progress" in data and (type(data["progress"]) is not int or data["progress"] < 0) or data.get("status", "reading") not in {"reading", "finished"}):
        raise HTTPException(422, "阅读进度或状态不正确")
    if kind == "annotation":
        if ("start" in data) != ("end" in data) or "start" in data and (type(data["start"]) is not int or type(data["end"]) is not int or data["start"] < 0 or data["end"] <= data["start"]):
            raise HTTPException(422, "引文位置不正确")
        replies = data.get("replies", [])
        if not isinstance(replies, list) or len(replies) > 24 or any(not isinstance(r, dict) or r.get("author") not in {"user", "gpt", "claude"} or not isinstance(r.get("text"), str) or not 0 < len(r["text"].strip()) <= 280 or not isinstance(r.get("at"), str) or len(r["at"]) > 40 for r in replies):
            raise HTTPException(422, "共读回复格式不正确")
    return {"kind": kind, "scope": scope, "title": title.strip(), "content": content, "data": data}


def view(row):
    d = dict(row)
    d["data"] = json.loads(d["data"])
    return d


def whisper_context(path, room, agent):
    if agent not in {"gpt", "claude"} or room not in {"lune-" + agent, "lune-group"}:
        return ""
    allowed = ("shared", "group" if room == "lune-group" else agent)
    try:
        with sqlite3.connect(path) as c:
            rows = c.execute("SELECT title,content FROM lune_workspace WHERE kind='whisper' AND deleted=0 AND scope IN (?,?) ORDER BY updated_at DESC LIMIT 4", allowed).fetchall()
        return "\n".join(title + "：" + content[:350] for title, content in rows)[:1600]
    except sqlite3.OperationalError:
        return ""


def register(app, relay):
    path = relay["DB_PATH"]

    @contextmanager
    def db():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def save(body, actor="user", allowed=None, mid=None, version=None):
        body = validate(body)
        if allowed is not None and body["scope"] not in allowed:
            raise HTTPException(403, "本会话不能访问这个范围")
        ts = now()
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT * FROM lune_workspace WHERE id=? AND deleted=0", (mid,)).fetchone() if mid else None
            if mid and not old:
                raise HTTPException(404, "条目不存在")
            if old and allowed is not None and old["scope"] not in allowed:
                raise HTTPException(403, "本会话不能访问这个范围")
            if body["kind"] == "annotation":
                book = c.execute("SELECT scope,content FROM lune_workspace WHERE id=? AND kind='book' AND deleted=0", (body["data"]["book_id"],)).fetchone()
                if not book or book["scope"] != body["scope"]:
                    raise HTTPException(422, "批注与书籍的范围必须一致")
                if "start" in body["data"]:
                    ps = re.split(r"\n\s*\n", book["content"])
                    d = body["data"]
                    if type(d.get("para")) is not int or d["para"] < 0 or d["para"] >= len(ps) or ps[d["para"]][d["start"]:d["end"]] != d["quote"]:
                        raise HTTPException(422, "批注引文与原文位置不一致")
                replies = body["data"].get("replies", [])
                previous = json.loads(old["data"]).get("replies", []) if old else []
                if replies[:len(previous)] != previous or len(replies) > len(previous) + 1 or (replies and len(replies) > len(previous) and replies[-1]["author"] != actor):
                    raise HTTPException(422, "不能改写已有的共读回复")
                if old and actor != "user" and old["author"] != actor:
                    before = json.loads(old["data"])
                    if body["title"] != old["title"] or body["content"] != old["content"] or {k:v for k,v in body["data"].items() if k != "replies"} != {k:v for k,v in before.items() if k != "replies"}:
                        raise HTTPException(403, "只能回复他人的批注")
            # Check the expected version within the write transaction.
            if old:
                if version != old["version"]:
                    raise HTTPException(409, "条目已经更新，请刷新后再修改")
                if body["kind"] != old["kind"]:
                    raise HTTPException(422, "不能改变条目类型")
                if old["kind"] == "book" and body["scope"] != old["scope"]:
                    c.execute("UPDATE lune_workspace SET scope=?,version=version+1,updated_at=? WHERE kind='annotation' AND json_extract(data,'$.book_id')=? AND deleted=0", (body["scope"], ts, mid))
                c.execute("UPDATE lune_workspace SET scope=?,title=?,content=?,data=?,updated_at=?,version=version+1 WHERE id=?", (body["scope"], body["title"], body["content"], json.dumps(body["data"], ensure_ascii=False), ts, mid))
            else:
                mid = uuid.uuid4().hex
                c.execute("INSERT INTO lune_workspace VALUES(?,?,?,?,?,?,?,?,?,?,0)", (mid, body["kind"], body["scope"], body["title"], body["content"], json.dumps(body["data"], ensure_ascii=False), actor, ts, ts, 1))
            return view(c.execute("SELECT * FROM lune_workspace WHERE id=?", (mid,)).fetchone())

    @app.get("/lune/workspace")
    async def listing(request: Request, kind: str = "", scope: str = ""):
        relay["check_auth"](request)
        if kind and kind not in KINDS or scope and scope not in SCOPES:
            raise HTTPException(422, "筛选范围不正确")
        where, params = ["deleted=0"], []
        if kind:
            where.append("kind=?"); params.append(kind)
        if scope:
            where.append("scope=?"); params.append(scope)
        with db() as c:
            rows = c.execute("SELECT * FROM lune_workspace WHERE " + " AND ".join(where) + " ORDER BY updated_at DESC LIMIT 2000", params).fetchall()
        return {"items": [view(r) for r in rows]}

    @app.post("/lune/workspace")
    async def create(request: Request):
        relay["check_auth"](request)
        item = save(await request.json())
        await relay["broadcast"](relay["app_subs"], {"type": "workspace", "kind": item["kind"]})
        return {"item": item}

    @app.patch("/lune/workspace/{mid}")
    async def update(mid: str, request: Request):
        relay["check_auth"](request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "内容格式不正确")
        item = save(body, mid=mid, version=body.get("version"))
        await relay["broadcast"](relay["app_subs"], {"type": "workspace", "kind": item["kind"]})
        return {"item": item}

    @app.delete("/lune/workspace/{mid}")
    async def delete(mid: str, request: Request, version: int):
        relay["check_auth"](request)
        with db() as c:
            old = c.execute("SELECT kind FROM lune_workspace WHERE id=? AND deleted=0", (mid,)).fetchone()
            cur = c.execute("UPDATE lune_workspace SET deleted=1,version=version+1,updated_at=? WHERE id=? AND version=? AND deleted=0", (now(), mid, version))
            if not cur.rowcount:
                raise HTTPException(409, "条目已经变化，请刷新后再删除")
            if old and old["kind"] == "book":
                c.execute("UPDATE lune_workspace SET deleted=1,version=version+1,updated_at=? WHERE kind='annotation' AND json_extract(data,'$.book_id')=? AND deleted=0", (now(), mid))
        await relay["broadcast"](relay["app_subs"], {"type": "workspace"})
        return {"ok": True}

    @app.post("/lune/assistant/workspace")
    async def assistant(request: Request):
        relay["check_auth"](request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "内容格式不正确")
        agent, room, rid = body.get("agent_id"), body.get("room"), body.get("run_id")
        if agent not in {"gpt", "claude"} or room not in {"lune-" + agent, "lune-group"}:
            raise HTTPException(403, "模型与会话不匹配")
        with db() as c:
            run = c.execute("SELECT room,state FROM lune_runs WHERE id=?", (rid,)).fetchone()
        if not run or "lune-" + run["room"] != room or run["state"] not in {"pending", "running"}:
            raise HTTPException(409, "会话任务已经停止")
        allowed = ["shared", "group" if room == "lune-group" else agent]
        action = body.get("action", "list")
        if action == "list":
            kind = body.get("kind", "todo")
            if kind not in KINDS:
                raise HTTPException(422, "页面类型不正确")
            with db() as c:
                rows = c.execute("SELECT * FROM lune_workspace WHERE deleted=0 AND kind=? AND scope IN (?,?) ORDER BY updated_at DESC LIMIT 10", (kind, *allowed)).fetchall()
            items = [view(r) for r in rows]
            for item in items:
                item["content_truncated"] = len(item["content"]) > 4000
                item["content"] = item["content"][:4000]
            return {"items": items}
        if action not in {"create", "update"}:
            raise HTTPException(422, "不支持的操作")
        if body.get("kind") not in {"todo", "journal", "event", "whisper", "annotation", "report"}:
            raise HTTPException(403, "这个类型只能由用户上传或记录")
        if action == "update" and not body.get("id"):
            raise HTTPException(422, "修改条目需要编号")
        item = save(body, actor=agent, allowed=allowed, mid=body.get("id") if action == "update" else None, version=body.get("version"))
        await relay["broadcast"](relay["app_subs"], {"type": "workspace", "kind": item["kind"]})
        return {"item": item}

    @app.get("/lune/rooms/{room}/search")
    async def search(room: str, request: Request, q: str = ""):
        relay["check_auth"](request)
        if room not in {"gpt", "claude", "group"} or not q.strip() or len(q) > 200:
            raise HTTPException(422, "请选择会话并输入 200 字以内的关键词")
        with db() as c:
            rows = c.execute("SELECT * FROM messages WHERE json_extract(meta,'$.api_session')=? AND instr(lower(text),lower(?))>0 ORDER BY id DESC LIMIT 50", ("lune-" + room, q.strip())).fetchall()
        return {"messages": [relay["app_payload"](m) for m in relay["rows_to_messages"](rows)]}

    return {"init": lambda: init(path)}
