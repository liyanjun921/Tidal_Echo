"""Named worldbooks and their per-contact deployment."""
import json
import re
from uuid import uuid4

from fastapi import HTTPException, Request

MAX_BOOKS = 100
MAX_ENTRIES = 80
CONTEXT_LIMIT = 12000


def init(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS emoi_worldbooks (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL,
          is_global INTEGER NOT NULL, entries TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS emoi_worldbook_contacts (
          contact_id TEXT NOT NULL REFERENCES emoi_v2_contacts(id) ON DELETE CASCADE,
          book_id TEXT NOT NULL REFERENCES emoi_worldbooks(id) ON DELETE CASCADE,
          PRIMARY KEY(contact_id, book_id)
        );
    """)


def bindings(db, contact_id):
    return [row[0] for row in db.execute("""
        SELECT book_id FROM emoi_worldbook_contacts WHERE contact_id=? ORDER BY rowid
    """, (contact_id,))]


def bind(db, contact_id, ids, valid_id):
    if not isinstance(ids, list) or len(ids) > MAX_BOOKS:
        raise HTTPException(422, "世界书绑定格式无效")
    updated = list(dict.fromkeys(valid_id(ident) for ident in ids))
    for ident in updated:
        if not db.execute("SELECT 1 FROM emoi_worldbooks WHERE id=?", (ident,)).fetchone():
            raise HTTPException(422, "所选世界书已删除，请重新选择")
    db.execute("DELETE FROM emoi_worldbook_contacts WHERE contact_id=?", (contact_id,))
    db.executemany("INSERT INTO emoi_worldbook_contacts VALUES(?,?)", [(contact_id, ident) for ident in updated])


def context(db, recent, contact_id=""):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='emoi_worldbooks'").fetchone():
        return ""
    candidates = db.execute("""
        SELECT w.name, w.entries
        FROM emoi_worldbooks w LEFT JOIN emoi_worldbook_contacts b
          ON b.book_id=w.id AND b.contact_id=?
        WHERE w.enabled=1 AND (w.is_global=1 OR b.book_id IS NOT NULL)
        ORDER BY b.book_id IS NULL, w.rowid
    """, (contact_id,))
    recent = recent.casefold()
    selected, used = [], 0
    for name, entries in candidates:
        for entry in json.loads(entries):
            if not entry["enabled"] or not (entry["always"] or any(key.casefold() in recent for key in entry["keys"])):
                continue
            label = name + (" / " + entry["title"] if entry["title"] else "")
            block = f"【{label}】\n{entry['text']}"
            if used + len(block) + 2 <= CONTEXT_LIMIT:
                selected.append(block)
                used += len(block) + 2
    return "\n\n".join(selected)


def register(app, relay, connect, valid_id, clean_text):
    path = relay["DB_PATH"]
    auth = relay["check_auth"]

    def view(row):
        return {"id": row["id"], "name": row["name"], "enabled": bool(row["enabled"]),
                "is_global": bool(row["is_global"]), "entries": json.loads(row["entries"])}

    @app.get("/emoi/v2/worldbooks")
    async def list_worldbooks(request: Request):
        auth(request)
        with connect(path) as db:
            return {"books": [view(row) for row in db.execute("SELECT * FROM emoi_worldbooks ORDER BY rowid")]}

    def validated(body):
        if not isinstance(body, dict) or any(type(body.get(field)) is not bool for field in ("enabled", "is_global")):
            raise HTTPException(422, "世界书设置格式无效")
        name = clean_text(body.get("name"), 80, True)
        raw = body.get("entries")
        if not isinstance(raw, list) or len(raw) > MAX_ENTRIES:
            raise HTTPException(422, "每本世界书最多 80 个条目")
        entries = []
        for entry in raw:
            if not isinstance(entry, dict) or any(type(entry.get(field)) is not bool for field in ("always", "enabled")):
                raise HTTPException(422, "世界书条目格式无效")
            raw_keys = entry.get("keys")
            if not isinstance(raw_keys, str) or len(raw_keys) > 2400:
                raise HTTPException(422, "触发词格式无效")
            keys = list(dict.fromkeys(key.strip() for key in re.split(r"[,，\n]+", raw_keys) if key.strip()))
            if any(len(key) > 100 for key in keys) or (entry["enabled"] and not entry["always"] and not keys):
                raise HTTPException(422, "关键词条目需填写触发词，每个词最多 100 字")
            entries.append({
                "title": clean_text(entry.get("title", ""), 80),
                "text": clean_text(entry.get("text"), 6000, True), "keys": keys,
                "always": entry["always"], "enabled": entry["enabled"],
            })
        encoded = json.dumps(entries, ensure_ascii=False)
        if len(encoded) > 120000:
            raise HTTPException(422, "这本世界书过长，可拆成多本")
        return name, body["enabled"], body["is_global"], encoded

    @app.post("/emoi/v2/worldbooks")
    async def create_worldbook(request: Request):
        auth(request)
        fields = validated(await request.json())
        ident = str(uuid4())
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM emoi_worldbooks").fetchone()[0] >= MAX_BOOKS:
                raise HTTPException(409, "世界书已达 100 本")
            db.execute("INSERT INTO emoi_worldbooks VALUES(?,?,?,?,?)", (ident, *fields))
            return {"book": view(db.execute("SELECT * FROM emoi_worldbooks WHERE id=?", (ident,)).fetchone())}

    @app.put("/emoi/v2/worldbooks/{book_id}")
    async def update_worldbook(book_id: str, request: Request):
        auth(request)
        fields = validated(await request.json())
        ident = valid_id(book_id)
        with connect(path) as db:
            if not db.execute("UPDATE emoi_worldbooks SET name=?,enabled=?,is_global=?,entries=? WHERE id=?", (*fields, ident)).rowcount:
                raise HTTPException(404, "世界书不存在")
            return {"book": view(db.execute("SELECT * FROM emoi_worldbooks WHERE id=?", (ident,)).fetchone())}

    @app.delete("/emoi/v2/worldbooks/{book_id}")
    async def delete_worldbook(book_id: str, request: Request):
        auth(request)
        with connect(path) as db:
            if not db.execute("DELETE FROM emoi_worldbooks WHERE id=?", (valid_id(book_id),)).rowcount:
                raise HTTPException(404, "世界书不存在")
        return {"ok": True}
