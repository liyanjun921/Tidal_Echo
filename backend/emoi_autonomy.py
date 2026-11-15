"""Persistent scheduling for a contact's private Émoi conversation."""
import json
import random
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

DEFAULTS = dict(idle=False, followup=False, moments=False, moment_photo="auto", calls=False, checkin=False,
                push=False, reactions=False, like_chance=90, comment_chance=70,
                comment_delay=120, comment_interval=60, idle_minutes=30, threshold=0, min_wait=15, max_wait=600,
                min_hours=3, max_hours=48, zone="Asia/Shanghai", quiet=True,
                quiet_start="01:00", quiet_end="07:00")


# An owner command is distinct from a model deciding to place a call.
_CALL_REQUEST = re.compile(
    r"(?:老公|老婆|宝宝|姐姐|亲爱的)?(?:现在|马上|立刻)?(?:请|能不能|可以|能|你)?"
    r"(?:给我|跟我|和我|向我|主动)?(?:打|拨打|发起|呼叫)(?:给我|一个|个|一通|通|一下)?"
    r"(?P<kind>视频通话|视频电话|视频|语音通话|语音电话|电话|语音)"
    r"(?:给我|试试|一下|好吗|好不好|可以吗|行吗|吗|吧|呀|啊|嘛|啦)*"
)
_APP_CALL_REQUEST = re.compile(r"(?:就要|就打|打|发起|试试)?(?:前端|应用内|这里|这个应用)(?:里的?|这个|的)?(?P<kind>视频通话|视频电话|语音通话|语音电话)")


def owner_call_request(text):
    command = re.sub(r"[\s,，。.!！?？、…～~]+", "", unicodedata.normalize("NFKC", text))
    match = _CALL_REQUEST.fullmatch(command) or _APP_CALL_REQUEST.fullmatch(command)
    if not match:
        return None
    return "video" if match["kind"].startswith("视频") else "voice"


def init(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS emoi_message_rules (
            contact_id TEXT PRIMARY KEY REFERENCES emoi_v2_contacts(id),
            settings TEXT NOT NULL, saved REAL NOT NULL, next_moment REAL NOT NULL,
            retry REAL NOT NULL DEFAULT 0, lease REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS emoi_shared_stickers (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, pack TEXT NOT NULL, attachment TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS emoi_moment_reactions (
            moment_id TEXT NOT NULL REFERENCES emoi_v2_moments(id) ON DELETE CASCADE,
            contact_id TEXT NOT NULL REFERENCES emoi_v2_contacts(id),
            due REAL NOT NULL, liked INTEGER NOT NULL, wants_comment INTEGER NOT NULL,
            done INTEGER NOT NULL DEFAULT 0, comment TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(moment_id, contact_id)
        );
        CREATE TABLE IF NOT EXISTS emoi_moment_owner_likes (
            moment_id TEXT PRIMARY KEY REFERENCES emoi_v2_moments(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS emoi_moment_owner_comments (
            id TEXT PRIMARY KEY,
            moment_id TEXT NOT NULL REFERENCES emoi_v2_moments(id) ON DELETE CASCADE,
            text TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS emoi_moment_owner_comment_post ON emoi_moment_owner_comments(moment_id,created_at);
        CREATE INDEX IF NOT EXISTS emoi_moment_reaction_due ON emoi_moment_reactions(done,due);
    """)


def settings(body):
    if not isinstance(body, dict):
        raise HTTPException(422, "无效的信息设置")
    result = {key: body.get(key, default) for key, default in DEFAULTS.items()}
    bounds = dict(idle_minutes=(1, 1440), threshold=(0, 100), min_wait=(15, 3600),
                  max_wait=(15, 3600), min_hours=(1, 168), max_hours=(1, 168),
                  like_chance=(0, 100), comment_chance=(0, 100),
                  comment_delay=(0, 3600), comment_interval=(0, 3600))
    try:
        for key, value in result.items():
            if type(value) is not type(DEFAULTS[key]):
                raise ValueError
            if key in bounds and not bounds[key][0] <= value <= bounds[key][1]:
                raise ValueError
            if key in ("quiet_start", "quiet_end"):
                if datetime.strptime(value, "%H:%M").strftime("%H:%M") != value:
                    raise ValueError
        if len(result["zone"]) > 80:
            raise ValueError
        ZoneInfo(result["zone"])
        if result["moment_photo"] not in ("auto", "text", "image"):
            raise ValueError
        if result["min_wait"] > result["max_wait"] or result["min_hours"] > result["max_hours"]:
            raise ValueError
    except (ValueError, ZoneInfoNotFoundError):
        raise HTTPException(422, "请检查时间范围和时区") from None
    return result


def next_moment(config, stamp):
    return stamp + 3600 * random.uniform(config["min_hours"], config["max_hours"])


def is_quiet(config, stamp):
    local = datetime.fromtimestamp(stamp, ZoneInfo(config["zone"])).strftime("%H:%M")
    start, end = config["quiet_start"], config["quiet_end"]
    return config["quiet"] and (start <= local < end if start <= end else local >= start or local < end)


def followup_delay(config, score):
    if type(score) is not int or not config["threshold"] <= score <= 100:
        return None
    fraction = (score - config["threshold"]) / max(1, 100 - config["threshold"])
    if score == 100:
        return config["min_wait"]
    return config["max_wait"] - (config["max_wait"] - config["min_wait"]) * fraction


def timeline(db, cid, saved):
    human = db.execute("""
        SELECT rowid, created_at FROM emoi_v2_messages
        WHERE conversation_id=? AND author='human' ORDER BY rowid DESC LIMIT 1
    """, (cid,)).fetchone()
    anchor = max(saved, datetime.fromisoformat(human["created_at"]).timestamp()) if human else saved
    entries = db.execute("""
        SELECT rowid, nonce, created_at, followup_score, delivery FROM emoi_v2_messages
        WHERE conversation_id=? AND rowid>? ORDER BY rowid DESC
    """, (cid, human["rowid"] if human else 0)).fetchall()
    active = [row for row in entries if datetime.fromisoformat(row["created_at"]).timestamp() >= anchor]
    last = max(anchor, datetime.fromisoformat(active[0]["created_at"]).timestamp()) if active else anchor
    count = sum(row["nonce"].startswith(("idle:", "followup:")) for row in active)
    return human["rowid"] if human else 0, active, last, count


def due(db, rule, cid, config, stamp):
    if is_quiet(config, stamp):
        return None
    cursor, entries, last, count = timeline(db, cid, rule["saved"])
    if db.execute("SELECT 1 FROM emoi_v2_messages WHERE conversation_id=? AND delivery='replying'", (cid,)).fetchone():
        return None
    if config["moments"] and rule["next_moment"] <= stamp:
        return "moment", cursor
    if count < 3 and config["followup"] and entries and entries[0]["nonce"].startswith("reply:"):
        delay = followup_delay(config, entries[0]["followup_score"])
        if delay is not None and last + delay <= stamp:
            return "followup", cursor
    if count < 3 and config["idle"] and last + 60 * config["idle_minutes"] <= stamp:
        return "idle", cursor
    return None


def catalog(db, history):
    entries = [dict(row) for row in db.execute("SELECT id,name,pack FROM emoi_shared_stickers")]
    words = history.casefold()
    def relevance(item):
        name = item["name"].rsplit(".", 1)[0].casefold()
        return (-int(bool(name) and name in words), item["name"], item["id"])
    entries.sort(key=relevance)
    return entries[:40]


def enqueue_reactions(db, moment_id, stamp):
    offset = 0
    rows = db.execute("""
        SELECT r.contact_id,r.settings FROM emoi_message_rules r
        JOIN emoi_v2_contacts c ON c.id=r.contact_id
        WHERE c.archived=0 AND c.model_route<>'' ORDER BY r.contact_id
    """)
    for row in rows:
        config = {**DEFAULTS, **json.loads(row["settings"])}
        if not config["reactions"]:
            continue
        liked = random.randrange(100) < config["like_chance"]
        comment = random.randrange(100) < config["comment_chance"]
        if liked or comment:
            db.execute("""
                INSERT OR IGNORE INTO emoi_moment_reactions(moment_id,contact_id,due,liked,wants_comment)
                VALUES(?,?,?,?,?)
            """, (moment_id, row["contact_id"], stamp + config["comment_delay"] + offset, liked, comment))
            offset += config["comment_interval"]
