"""Durable, source-agnostic wake inbox for Luné.

Events are references, not prompts or permissions. The same Room tick handles
scheduled heartbeats, external events, reminders, manual wakes and commitments.
"""
import hashlib
import math
import re
import time
import uuid

SOURCES = frozenset({"garden", "gmail", "cove", "calendar", "device", "manual", "system", "self_commitment"})
SCOPES = frozenset({"gpt", "claude", "group_gpt", "group_claude"})
EVENT_TYPE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,79}$")
MAX_FUTURE_SECONDS = 30 * 86400
MAX_TTL_SECONDS = 7 * 86400
LEASE_SECONDS = 15 * 60
MAX_ATTEMPTS = 3


def init(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS lune_wake_inbox(
        id TEXT PRIMARY KEY, scope TEXT NOT NULL, source TEXT NOT NULL,
        source_event_id TEXT NOT NULL, event_type TEXT NOT NULL,
        summary TEXT NOT NULL, resource_ref TEXT NOT NULL DEFAULT '',
        priority INTEGER NOT NULL, created REAL NOT NULL, not_before REAL NOT NULL,
        expires_at REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0, claim_token TEXT, lease_until REAL,
        claimed_at REAL, consumed_at REAL, outcome TEXT,
        result_summary TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '',
        UNIQUE(scope, source, source_event_id)
    );
    CREATE INDEX IF NOT EXISTS lune_wake_due
        ON lune_wake_inbox(scope, state, not_before, priority);
    """)


def recover(db, now=None):
    """Do not replay a model call whose result became unknown at process restart."""
    clock = float(time.time() if now is None else now)
    db.execute(
        """UPDATE lune_wake_inbox
           SET state='interrupted', claim_token=NULL, lease_until=NULL,
               last_error='服务重启；本次模型调用结果未知，不自动重放'
           WHERE state='claimed'"""
    )
    db.execute(
        """UPDATE lune_wake_inbox SET state='expired', last_error='事件已过期'
           WHERE state='pending' AND expires_at<=?""", (clock,)
    )


def _clean_text(value, label, maximum, optional=False):
    if optional and value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(label + " 必须是文本")
    cleaned = " ".join(value.split())
    if (not optional and not cleaned) or len(cleaned) > maximum or "\x00" in cleaned:
        raise ValueError(label + " 为空或超出长度限制")
    return cleaned


def enqueue(db, scope, source, source_event_id, event_type, summary, *,
            resource_ref="", priority=50, now=None, not_before=None, ttl_seconds=86400):
    if scope not in SCOPES:
        raise ValueError("房间不正确")
    if source not in SOURCES:
        raise ValueError("不支持的事件来源")
    source_event_id = _clean_text(source_event_id, "event_id", 180)
    if not isinstance(event_type, str) or not EVENT_TYPE.fullmatch(event_type):
        raise ValueError("事件类型格式不正确")
    summary = _clean_text(summary, "summary", 600)
    resource_ref = _clean_text(resource_ref, "resource_ref", 300, optional=True)
    if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 100:
        raise ValueError("priority 必须是 1–100 的整数")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 60 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError("ttl_seconds 必须是 60 秒到 7 天")
    clock = float(time.time() if now is None else now)
    if not math.isfinite(clock):
        raise ValueError("now 不正确")
    due = clock if not_before is None else float(not_before)
    if not math.isfinite(due) or due > clock + MAX_FUTURE_SECONDS:
        raise ValueError("not_before 最多只能预约 30 天")
    due = max(clock, due)
    expires = due + ttl_seconds
    event_id = hashlib.sha256((scope + "\0" + source + "\0" + source_event_id).encode()).hexdigest()[:32]
    cursor = db.execute(
        """INSERT OR IGNORE INTO lune_wake_inbox
           (id,scope,source,source_event_id,event_type,summary,resource_ref,priority,
            created,not_before,expires_at,state,attempts)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,'pending',0)""",
        (event_id, scope, source, source_event_id, event_type, summary, resource_ref,
         priority, clock, due, expires)
    )
    row = db.execute("SELECT id,state,not_before FROM lune_wake_inbox WHERE id=?", (event_id,)).fetchone()
    return {"id": row["id"], "state": row["state"], "not_before": row["not_before"],
            "duplicate": cursor.rowcount == 0}


def peek_due(db, scope, now=None):
    clock = float(time.time() if now is None else now)
    db.execute(
        """UPDATE lune_wake_inbox SET state='expired', claim_token=NULL, lease_until=NULL,
                  last_error='事件已过期'
           WHERE scope=? AND state IN ('pending','claimed') AND expires_at<=?""",
        (scope, clock)
    )
    db.execute(
        """UPDATE lune_wake_inbox SET state='pending', claim_token=NULL, lease_until=NULL,
                  last_error='处理租约到期，等待下一次机会'
           WHERE scope=? AND state='claimed' AND lease_until<=? AND expires_at>?""",
        (scope, clock, clock)
    )
    row = db.execute(
        """SELECT * FROM lune_wake_inbox
           WHERE scope=? AND state='pending' AND not_before<=? AND expires_at>?
           ORDER BY priority DESC, not_before ASC, created ASC LIMIT 1""",
        (scope, clock, clock)
    ).fetchone()
    return dict(row) if row else None


def claim_due(db, scope, now=None):
    clock = float(time.time() if now is None else now)
    row = peek_due(db, scope, clock)
    if not row:
        return None
    token = uuid.uuid4().hex
    changed = db.execute(
        """UPDATE lune_wake_inbox
           SET state='claimed', attempts=attempts+1, claim_token=?, claimed_at=?, lease_until=?
           WHERE id=? AND state='pending'""",
        (token, clock, clock + LEASE_SECONDS, row["id"])
    ).rowcount
    if changed != 1:
        return None
    claimed = db.execute("SELECT * FROM lune_wake_inbox WHERE id=?", (row["id"],)).fetchone()
    result = dict(claimed)
    result["claim_token"] = token
    return result


def finish(db, event_id, claim_token, outcome, result_summary="", now=None):
    if outcome not in {"silent", "trace", "message"}:
        raise ValueError("醒来结局不正确")
    summary = _clean_text(result_summary, "result_summary", 300, optional=True)
    clock = float(time.time() if now is None else now)
    changed = db.execute(
        """UPDATE lune_wake_inbox
           SET state='consumed', consumed_at=?, outcome=?, result_summary=?,
               claim_token=NULL, lease_until=NULL, last_error=''
           WHERE id=? AND state='claimed' AND claim_token=?""",
        (clock, outcome, summary, event_id, claim_token)
    ).rowcount
    return changed == 1


def abort(db, event_id, claim_token, reason="本次醒来未完成", now=None):
    clock = float(time.time() if now is None else now)
    row = db.execute("SELECT * FROM lune_wake_inbox WHERE id=?", (event_id,)).fetchone()
    if not row or row["state"] != "claimed" or row["claim_token"] != claim_token:
        return False
    retry = row["attempts"] < MAX_ATTEMPTS and row["expires_at"] > clock
    state = "pending" if retry else "failed"
    due = max(row["not_before"], clock + 300) if retry else row["not_before"]
    error = _clean_text(str(reason), "error", 300, optional=True)
    db.execute(
        """UPDATE lune_wake_inbox
           SET state=?, not_before=?, claim_token=NULL, lease_until=NULL,
               last_error=? WHERE id=? AND claim_token=?""",
        (state, due, error, event_id, claim_token)
    )
    return True


def schedule_commitment(db, scope, source_event_id, minutes, reason, now=None):
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 30 <= minutes <= 10080:
        raise ValueError("自主预约必须在 30 分钟到 7 天之间")
    reason = _clean_text(reason, "自主预约理由", 300)
    clock = float(time.time() if now is None else now)
    existing = db.execute(
        "SELECT id,state,not_before FROM lune_wake_inbox WHERE scope=? AND source='self_commitment' AND source_event_id=?",
        (scope, str(source_event_id))
    ).fetchone()
    if existing:
        return {"id": existing["id"], "state": existing["state"],
                "not_before": existing["not_before"], "duplicate": True}
    db.execute(
        """UPDATE lune_wake_inbox SET state='cancelled', last_error='被新的自主预约替代'
           WHERE scope=? AND source='self_commitment' AND state='pending'""",
        (scope,)
    )
    return enqueue(
        db, scope, "self_commitment", str(source_event_id), "self.resume", reason,
        priority=65, now=clock, not_before=clock + minutes * 60,
        ttl_seconds=MAX_TTL_SECONDS
    )


def list_events(db, scope, limit=50):
    limit = max(1, min(int(limit), 100))
    rows = db.execute(
        """SELECT id,source,source_event_id,event_type,summary,resource_ref,priority,
                  created,not_before,expires_at,state,attempts,consumed_at,outcome,last_error
           FROM lune_wake_inbox WHERE scope=? ORDER BY created DESC LIMIT ?""",
        (scope, limit)
    ).fetchall()
    return [dict(row) for row in rows]
