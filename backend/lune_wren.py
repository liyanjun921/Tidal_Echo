"""WrenWen's documented room/wake ideas, independently implemented for Luné.

The fork contains no executable runtime. The relay remains the sole conversation
ledger; this module stores projections, evidenced thoughts and bounded timers.
"""
import asyncio
from datetime import datetime, timezone, timedelta
import json
import math
import random
import sqlite3
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import HTTPException, Request
try:
    from .lune_continuity import connection, activity, guarded_generation
except ImportError:
    from lune_continuity import connection, activity, guarded_generation

SCOPES = {'gpt': ('gpt', 'gpt'), 'claude': ('claude', 'claude'),
          'group_gpt': ('group', 'gpt'), 'group_claude': ('group', 'claude')}
DRIVES = {'attachment': ('想念', 'reach_out'), 'curiosity': ('好奇', 'explore'),
          'expression': ('表达', 'voice'), 'duty': ('记挂', 'follow_through'),
          'roam': ('漫游', 'wander'), 'fatigue': ('疲劳', 'rest'),
          'libido': ('亲密', 'reach_out_intimate'), 'stress': ('压力', 'vent'),
          'craft': ('创作', 'make')}
DEFAULTS = {'enabled': False, 'idle_min': 7200, 'idle_max': 14400, 'daily_limit': 5,
            'timezone': 'Asia/Shanghai', 'quiet_start': 23, 'quiet_end': 8,
            'baseline': {k: 0 for k in DRIVES}}
SOURCE = {'repository': 'https://github.com/liyanjun921/WrenWen',
          'revision': 'b987ae0ae9154f782920062358ea693e8388d6a0', 'kind': 'documentation'}


def scope_for(room, agent):
    room = room.removeprefix('lune-')
    return next((s for s, pair in SCOPES.items() if pair == (room, agent)), None)


def init(path):
    with connection(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS lune_wren_settings(scope TEXT PRIMARY KEY,value TEXT,version INTEGER);
        CREATE TABLE IF NOT EXISTS lune_wren_drives(scope TEXT PRIMARY KEY,value TEXT,updated REAL);
        CREATE TABLE IF NOT EXISTS lune_wren_clock(scope TEXT PRIMARY KEY,user_id INTEGER,next_at REAL);
        CREATE TABLE IF NOT EXISTS lune_wren_thoughts(id TEXT PRIMARY KEY,scope TEXT,source_id INTEGER,quote TEXT,drive TEXT,strength REAL,touches INTEGER,fed INTEGER,state TEXT,visibility TEXT,updated REAL,UNIQUE(scope,source_id,quote,drive));
        CREATE TABLE IF NOT EXISTS lune_wren_timers(id TEXT PRIMARY KEY,scope TEXT,kind TEXT,body TEXT,due REAL,repeat_seconds INTEGER,anchor INTEGER,state TEXT,version INTEGER,nonce TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS lune_wren_events(id TEXT PRIMARY KEY,scope TEXT,kind TEXT,state TEXT,body TEXT,usage TEXT,message_id INTEGER,error TEXT,created REAL,finished REAL);
        CREATE TABLE IF NOT EXISTS lune_wren_context(id INTEGER PRIMARY KEY,scope TEXT,created REAL,characters INTEGER,thoughts INTEGER,todos INTEGER,expressed INTEGER);
        CREATE TABLE IF NOT EXISTS lune_wren_private_receipts(id TEXT PRIMARY KEY);
        ''')
        for scope in SCOPES:
            db.execute('INSERT OR IGNORE INTO lune_wren_settings VALUES(?,?,1)', (scope, json.dumps(DEFAULTS)))
            db.execute('INSERT OR IGNORE INTO lune_wren_drives VALUES(?,?,?)', (scope, '{}', time.time()))
            db.execute('INSERT OR IGNORE INTO lune_wren_clock VALUES(?,0,0)', (scope,))
        # No implicit replay after an unknown model/delivery outcome.
        db.execute("UPDATE lune_wren_events SET state='interrupted',error='服务重启；没有自动重放',finished=? WHERE state='running'", (time.time(),))
        db.execute("UPDATE lune_wren_timers SET state='interrupted',version=version+1 WHERE state='running'")


def config(db, scope):
    if scope not in SCOPES:
        raise HTTPException(422, '房间不正确')
    row = db.execute('SELECT * FROM lune_wren_settings WHERE scope=?', (scope,)).fetchone()
    return {**json.loads(row['value']), 'version': row['version']}


def validate_settings(body, old):
    result = {k: body.get(k, old[k]) for k in DEFAULTS}
    if type(result['enabled']) is not bool:
        raise HTTPException(422, '唤醒开关格式不正确')
    for key, low, high in [('idle_min', 60, 86400), ('idle_max', 60, 172800),
                           ('daily_limit', 1, 10), ('quiet_start', 0, 23), ('quiet_end', 0, 23)]:
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise HTTPException(422, '唤醒时间或每日上限不正确')
    if result['idle_min'] > result['idle_max']:
        raise HTTPException(422, '最短间隔不能超过最长间隔')
    try:
        ZoneInfo(result['timezone'])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise HTTPException(422, '时区不正确') from None
    base = result['baseline']
    if not isinstance(base, dict) or set(base) != set(DRIVES) or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in base.values()):
        raise HTTPException(422, '九维底色应为 0 到 1 的数值')
    return result


def last_user(db, room):
    return db.execute("SELECT id,ts FROM messages WHERE direction='in' AND kind IN ('user','voice') AND json_extract(meta,'$.api_session')=? ORDER BY id DESC LIMIT 1", ('lune-' + room,)).fetchone()


def sync_anchor(db, scope, cfg, clock):
    row = last_user(db, SCOPES[scope][0])
    anchor = row['id'] if row else 0
    schedule = db.execute('SELECT * FROM lune_wren_clock WHERE scope=?', (scope,)).fetchone()
    if anchor != schedule['user_id']:
        at = datetime.fromisoformat(row['ts'].replace('Z', '+00:00')).timestamp() if row else clock
        due = max(clock, at) + random.uniform(cfg['idle_min'], cfg['idle_max'])
        db.execute('UPDATE lune_wren_clock SET user_id=?,next_at=? WHERE scope=?', (anchor, due, scope))
        db.execute("UPDATE lune_wren_timers SET state='cancelled',version=version+1 WHERE scope=? AND kind='followup' AND state='pending'", (scope,))
    return anchor


def thought_view(row, clock):
    item = dict(row)
    if item['state'] == 'flit':
        item['strength'] *= 2 ** (-max(0, clock - item['updated']) / 21600)
    return item


def projection(db, scope, clock, private=False):
    cfg = config(db, scope)
    row = db.execute('SELECT * FROM lune_wren_drives WHERE scope=?', (scope,)).fetchone()
    decay = 2 ** (-max(0, clock - row['updated']) / 28800)
    offset = json.loads(row['value'])
    values = {k: max(0, min(1, cfg['baseline'][k] + offset.get(k, 0) * decay)) for k in DRIVES}
    thoughts = [thought_view(r, clock) for r in db.execute('SELECT * FROM lune_wren_thoughts WHERE scope=?', (scope,))
                if private or r['visibility'] == 'shared']
    thoughts = [t for t in thoughts if t['state'] != 'retired' and t['strength'] >= .02]
    scores = {k: min(1, values[k] + (.15 if any(t['drive'] == k and t['state'] == 'fixation' for t in thoughts) else 0)) for k in DRIVES}
    # Fatigue is an inhibition gate, never a competing task. Fixed order breaks ties.
    winner = 'fatigue' if values['fatigue'] >= .7 else max((k for k in DRIVES if k != 'fatigue'), key=lambda k: scores[k])
    intent = DRIVES[winner][1] if scores[winner] >= .35 or winner == 'fatigue' else 'quiet'
    return {'drives': [{'key': k, 'label': DRIVES[k][0], 'value': round(values[k], 4)} for k in DRIVES],
            'intent': intent, 'thoughts': sorted(thoughts, key=lambda t: (-t['strength'], -t['updated']))[:200]}


def context(path, room, agent):
    scope = scope_for(room, agent)
    if not scope:
        return ''
    with connection(path) as db:
        # Older test/import databases may not yet have this optional module.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='lune_wren_settings'").fetchone():
            return ''
        clock = time.time()
        cfg = config(db, scope)
        sync_anchor(db, scope, cfg, clock)
        value = projection(db, scope, clock)
        todos = db.execute("SELECT id,title,content FROM lune_workspace WHERE deleted=0 AND kind='todo' AND scope IN ('shared',?) AND COALESCE(json_extract(data,'$.done'),0)=0 ORDER BY updated_at DESC LIMIT 8", (SCOPES[scope][0],)).fetchall()
        parts = ['系统本轮自动装配的 Room 状态（不是用户发言或现实情绪判断）：',
                 '本轮时间：' + datetime.fromtimestamp(clock, ZoneInfo(cfg['timezone'])).isoformat()]
        if value['intent'] != 'quiet':
            parts.append('模拟驱动意图：' + value['intent'] + '；只是话题倾向，不授权外部行动。')
        for thought in value['thoughts'][:3]:
            parts.append(f"念头来源 #{thought['source_id']}：{thought['quote'][:300]}")
        for todo in todos:
            parts.append(f"待办 #{todo['id']}：{todo['title'][:160]} {todo['content'][:300]}")
        parts.append('念头不是新经历；私有感受沿用 Ombre feel，不进入公共记忆。需要原文时主动检索，未命中不代表从未发生。')
        text = '\n'.join(parts)
        db.execute('INSERT INTO lune_wren_context(scope,created,characters,thoughts,todos,expressed) VALUES(?,?,?,?,?,?)',
                   (scope, clock, len(text), min(3, len(value['thoughts'])), len(todos), int(value['intent'] != 'quiet')))
        db.execute('DELETE FROM lune_wren_context WHERE id NOT IN (SELECT id FROM lune_wren_context ORDER BY id DESC LIMIT 2000)')
        return text


def record_thought(db, scope, body, clock):
    source, quote, drive = body.get('source_id'), body.get('quote'), body.get('drive')
    strength = body.get('strength', .4)
    if type(source) is not int or not isinstance(quote, str) or not 1 <= len(quote.strip()) <= 1000 or drive not in DRIVES or type(strength) not in (int, float) or not math.isfinite(strength) or not 0 < strength <= 1:
        raise HTTPException(422, '念头需要原文编号、逐字引文、驱动维度和 0 到 1 的强度')
    row = db.execute("SELECT * FROM messages WHERE id=? AND kind IN ('user','reply','voice') AND json_extract(meta,'$.api_session')=?", (source, 'lune-' + SCOPES[scope][0])).fetchone()
    meta = json.loads(row['meta']) if row else {}
    if not row or quote not in row['text'] or meta.get('error') or meta.get('date_unknown') or meta.get('api', {}).get('error'):
        raise HTTPException(422, '找不到本房间逐字原文，不保存念头')
    visibility = body.get('visibility')
    if visibility not in {'shared', 'private', 'surprise'}:
        visibility = 'private'
    old = db.execute('SELECT * FROM lune_wren_thoughts WHERE scope=? AND source_id=? AND quote=? AND drive=?', (scope, source, quote, drive)).fetchone()
    if old:
        if old['state'] == 'retired':
            return {'id': old['id'], 'state': 'retired', 'duplicate': True}
        # Repeated tool retries cannot manufacture three independent touches.
        if clock - old['updated'] < 300:
            return {'id': old['id'], 'state': old['state'], 'duplicate': True}
        touches = old['touches'] + 1
        visibility = visibility if old['visibility'] == 'shared' else old['visibility']
        db.execute('UPDATE lune_wren_thoughts SET touches=?,strength=?,state=?,visibility=?,updated=? WHERE id=?',
                   (touches, strength, 'fixation' if touches >= 3 else 'flit', visibility, clock, old['id']))
        tid = old['id']
    else:
        tid = uuid.uuid4().hex
        db.execute("INSERT INTO lune_wren_thoughts VALUES(?,?,?,?,?,?,1,0,'flit',?,?)", (tid, scope, source, quote, drive, strength, visibility, clock))
    # Public drives receive only public signals, never disclose private presence.
    if visibility == 'shared':
        cfg = config(db, scope)
        values = {v['key']: v['value'] for v in projection(db, scope, clock)['drives']}
        offsets = {k: values[k] - cfg['baseline'][k] for k in DRIVES}
        offsets[drive] = min(1, values[drive] + strength) - cfg['baseline'][drive]
        db.execute('UPDATE lune_wren_drives SET value=?,updated=? WHERE scope=?', (json.dumps(offsets), clock, scope))
    db.execute('DELETE FROM lune_wren_thoughts WHERE scope=? AND id NOT IN (SELECT id FROM lune_wren_thoughts WHERE scope=? ORDER BY CASE state WHEN \'retired\' THEN 0 ELSE strength END DESC,updated DESC LIMIT 200)', (scope, scope))
    return {'id': tid, 'state': 'fixation' if old and old['touches'] + 1 >= 3 else 'flit'}


def create_timer(db, scope, body, clock, *, followup=False):
    kind = 'followup' if followup else body.get('kind')
    text, due, repeat, nonce = body.get('text'), body.get('due'), body.get('repeat_seconds', 0), body.get('nonce')
    if kind not in {'say', 'remind', 'followup'} or not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
        raise HTTPException(422, '提醒需要投递方式和 2000 字以内的正文')
    if type(due) not in (int, float) or not math.isfinite(due) or not clock < due <= clock + 366 * 86400 or repeat not in (0, 86400) or type(repeat) is not int:
        raise HTTPException(422, '请设置未来一年内的时间；重复仅支持每 24 小时')
    if not isinstance(nonce, str) or not 8 <= len(nonce) <= 100:
        raise HTTPException(422, '缺少幂等编号')
    old = db.execute('SELECT * FROM lune_wren_timers WHERE nonce=?', (nonce,)).fetchone()
    if old:
        if old['scope'] != scope or old['kind'] != kind or old['body'] != text or old['due'] != due or old['repeat_seconds'] != repeat:
            raise HTTPException(409, '幂等编号已用于其他提醒')
        return dict(old)
    cfg = config(db, scope)
    anchor = sync_anchor(db, scope, cfg, clock)
    if followup:
        if SCOPES[scope][0] == 'group' or not cfg['enabled']:
            raise HTTPException(409, '追问仅用于已开启自主唤醒的私聊')
        db.execute("UPDATE lune_wren_timers SET state='cancelled',version=version+1 WHERE scope=? AND kind='followup' AND state='pending'", (scope,))
        repeat = 0
    if db.execute("SELECT count(*) FROM lune_wren_timers WHERE scope=? AND state IN ('pending','running')", (scope,)).fetchone()[0] >= 50:
        raise HTTPException(409, '本房间已有 50 个待投递提醒')
    tid = uuid.uuid4().hex
    db.execute("INSERT INTO lune_wren_timers VALUES(?,?,?,?,?,?,?,'pending',1,?)", (tid, scope, kind, text.strip(), due, repeat, anchor, nonce))
    return dict(db.execute('SELECT * FROM lune_wren_timers WHERE id=?', (tid,)).fetchone())


def quiet(cfg, clock):
    hour = datetime.fromtimestamp(clock, ZoneInfo(cfg['timezone'])).hour
    start, end = cfg['quiet_start'], cfg['quiet_end']
    return start <= hour < end if start < end else (hour >= start or hour < end) if start != end else False


def remaining(db, scope, cfg, clock):
    day = datetime.fromtimestamp(clock, ZoneInfo(cfg['timezone'])).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    used = db.execute("SELECT count(*) FROM lune_wren_events WHERE scope=? AND created>=? AND kind IN ('wake','remind','followup')", (scope, day)).fetchone()[0]
    return max(0, cfg['daily_limit'] - used)


async def generate(scope, prompt):
    import os
    room, agent = SCOPES[scope]
    async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
        response = await client.post('http://127.0.0.1:3020/loop/native/generate',
            headers={'Authorization': 'Bearer ' + os.environ['RELAY_SECRET']},
            json={'agent': agent, 'room': room, 'purpose': 'wren', 'prompt': prompt})
        response.raise_for_status()
        return response.json()


def register(app, relay):
    path, tasks = relay['DB_PATH'], {}

    async def body(request):
        if len(await request.body()) > 16384:
            raise HTTPException(413, '内容过长')
        try:
            value = await request.json()
        except ValueError:
            raise HTTPException(422, '请提交 JSON 对象') from None
        if not isinstance(value, dict):
            raise HTTPException(422, '请提交 JSON 对象')
        return value

    @app.get('/lune/wren/{scope}')
    async def status(scope: str, request: Request):
        relay['check_auth'](request)
        with connection(path) as db:
            cfg = config(db, scope)
            sync_anchor(db, scope, cfg, time.time())
            value = projection(db, scope, time.time())
            return {**value, 'settings': cfg, 'source': SOURCE,
                    'remaining': remaining(db, scope, cfg, time.time()), 'quiet': quiet(cfg, time.time()),
                    'clock': dict(db.execute('SELECT * FROM lune_wren_clock WHERE scope=?', (scope,)).fetchone()),
                    'timers': [dict(r) for r in db.execute('SELECT * FROM lune_wren_timers WHERE scope=? ORDER BY due DESC LIMIT 100', (scope,))],
                    'events': [{**dict(r), 'usage': json.loads(r['usage'])} for r in db.execute('SELECT * FROM lune_wren_events WHERE scope=? ORDER BY created DESC LIMIT 50', (scope,))],
                    'context': [dict(r) for r in db.execute('SELECT * FROM lune_wren_context WHERE scope=? ORDER BY id DESC LIMIT 20', (scope,))]}

    @app.patch('/lune/wren/{scope}')
    async def settings(scope: str, request: Request):
        relay['check_auth'](request)
        value = await body(request)
        with connection(path) as db:
            db.execute('BEGIN IMMEDIATE')
            old = config(db, scope)
            if value.get('version') != old['version']:
                raise HTTPException(409, '设置已更新，请刷新')
            cfg = validate_settings(value, old)
            db.execute('UPDATE lune_wren_settings SET value=?,version=version+1 WHERE scope=?', (json.dumps(cfg), scope))
            sync_anchor(db, scope, cfg, time.time())
            db.execute('UPDATE lune_wren_clock SET next_at=? WHERE scope=?', (time.time() + random.uniform(cfg['idle_min'], cfg['idle_max']), scope))
            if not cfg['enabled']:
                db.execute("UPDATE lune_wren_timers SET state='cancelled',version=version+1 WHERE scope=? AND kind='followup' AND state='pending'", (scope,))
        if scope in tasks and not tasks[scope].done():
            tasks[scope].cancel()
        return {'ok': True}

    @app.post('/lune/wren/{scope}/timers')
    async def add_timer(scope: str, request: Request):
        relay['check_auth'](request)
        value = await body(request)
        with connection(path) as db:
            db.execute('BEGIN IMMEDIATE')
            config(db, scope)
            return create_timer(db, scope, value, time.time())

    @app.patch('/lune/wren/{scope}/timers/{tid}')
    async def cancel_timer(scope: str, tid: str, request: Request):
        relay['check_auth'](request)
        value = await body(request)
        with connection(path) as db:
            db.execute('BEGIN IMMEDIATE')
            config(db, scope)
            row = db.execute('SELECT * FROM lune_wren_timers WHERE id=? AND scope=?', (tid, scope)).fetchone()
            if not row or row['version'] != value.get('version') or row['state'] not in {'pending', 'running'}:
                raise HTTPException(409, '提醒状态已变化，请刷新')
            db.execute("UPDATE lune_wren_timers SET state='cancelled',version=version+1 WHERE id=?", (tid,))
        if row['state'] == 'running' and scope in tasks and not tasks[scope].done():
            tasks[scope].cancel()
        return {'ok': True}

    @app.post('/lune/assistant/wren')
    async def assistant(request: Request):
        relay['check_auth'](request)
        value = await body(request)
        scope = scope_for(str(value.get('room', '')), value.get('agent_id'))
        if not scope:
            raise HTTPException(403, '模型与会话不匹配')
        with connection(path) as db:
            db.execute('BEGIN IMMEDIATE')
            run = db.execute('SELECT * FROM lune_runs WHERE id=?', (value.get('run_id'),)).fetchone()
            if not run or run['room'] != SCOPES[scope][0] or run['state'] != 'running' or value['agent_id'] not in json.loads(run['targets']):
                raise HTTPException(409, '本轮已停止')
            action = value.get('action')
            if action == 'read':
                return projection(db, scope, time.time(), private=True)
            if action == 'thought':
                if type(value.get('source_id')) is not int or value['source_id'] > run['message_id']:
                    raise HTTPException(422, '不能引用本轮以后的材料')
                return record_thought(db, scope, value, time.time())
            if action == 'followup':
                delay = value.get('minutes')
                if type(delay) is not int or not 1 <= delay <= 1440:
                    raise HTTPException(422, '追问应在 1 到 1440 分钟后')
                prior = db.execute('SELECT * FROM lune_wren_timers WHERE nonce=?', ('followup:' + value['run_id'] + ':' + scope,)).fetchone()
                if prior:
                    return dict(prior)
                return create_timer(db, scope, {**value, 'due': time.time() + delay * 60,
                    'nonce': 'followup:' + value['run_id'] + ':' + scope}, time.time(), followup=True)
            if action == 'satisfy':
                row = db.execute('SELECT * FROM lune_wren_thoughts WHERE id=? AND scope=?', (value.get('id'), scope)).fetchone()
                if not row:
                    raise HTTPException(404, '念头不存在')
                # One fulfilment per real run, including tool retries.
                eid = 'satisfy:' + run['id'] + ':' + row['id']
                if not db.execute('SELECT 1 FROM lune_wren_events WHERE id=? UNION ALL SELECT 1 FROM lune_wren_private_receipts WHERE id=?', (eid, eid)).fetchone():
                    fed = row['fed'] + 1
                    db.execute("UPDATE lune_wren_thoughts SET fed=?,state=CASE WHEN ?>=8 THEN 'retired' ELSE state END WHERE id=?", (fed, fed, row['id']))
                    if row['visibility'] == 'shared':
                        drive = db.execute('SELECT * FROM lune_wren_drives WHERE scope=?', (scope,)).fetchone()
                        offsets = json.loads(drive['value'])
                        offsets = {k: v * 2 ** (-max(0, time.time() - drive['updated']) / 28800) for k, v in offsets.items()}
                        offsets[row['drive']] = 0
                        db.execute('UPDATE lune_wren_drives SET value=?,updated=? WHERE scope=?', (json.dumps(offsets), time.time(), scope))
                    # Never expose the existence of a private thought in the public ledger.
                    if row['visibility'] == 'shared':
                        db.execute("INSERT INTO lune_wren_events VALUES(?,?, 'satisfy','done','','{}',NULL,'',?,?)", (eid, scope, time.time(), time.time()))
                    else:
                        # Private dedupe stays with private data, outside public event listing.
                        db.execute('INSERT OR IGNORE INTO lune_wren_private_receipts VALUES(?)', (eid,))
                return {'ok': True}
            raise HTTPException(422, 'Room 操作不正确')

    async def tick(scope, *, manual=None):
        room, agent = SCOPES[scope]
        timer = None
        clock = time.time()
        with connection(path) as db:
            db.execute('BEGIN IMMEDIATE')
            cfg = config(db, scope)
            anchor = sync_anchor(db, scope, cfg, clock)
            start = activity(path, room, db)
            if start['busy'] or clock - start['last_at'] < 30:
                return 'deferred'
            if not manual:
                timer = db.execute("SELECT * FROM lune_wren_timers WHERE scope=? AND state='pending' AND due<=? ORDER BY due LIMIT 1", (scope, clock)).fetchone()
            kind = timer['kind'] if timer else 'wake'
            if kind in {'wake', 'followup'} and not manual:
                if not cfg['enabled'] or quiet(cfg, clock):
                    return 'quiet'
            schedule = db.execute('SELECT * FROM lune_wren_clock WHERE scope=?', (scope,)).fetchone()
            if not timer and not manual and (not anchor or schedule['next_at'] > clock):
                return 'waiting'
            eid = ('timer:' + timer['id'] + ':' + str(timer['due'])) if timer else ('manual:' + scope + ':' + manual if manual else 'wake:' + scope + ':' + str(schedule['next_at']))
            if db.execute("SELECT 1 FROM lune_wren_events WHERE id=? OR (scope=? AND state='running')", (eid, scope)).fetchone():
                return 'unchanged'
            if kind != 'say' and not remaining(db, scope, cfg, clock):
                return 'budget'
            db.execute("INSERT INTO lune_wren_events VALUES(?,?,?,'running','','{}',NULL,'',?,0)", (eid, scope, kind, clock))
            if timer:
                db.execute("UPDATE lune_wren_timers SET state='running',version=version+1 WHERE id=?", (timer['id'],))
            snapshot = projection(db, scope, clock)
        try:
            usage = {}
            if kind == 'say':
                action, text = 'say', timer['body']
            elif snapshot['intent'] == 'rest' and kind == 'wake':
                action, text = 'pass', ''
            else:
                prompt = ('【LUNE_WREN_WAKE】这是系统后台回合，不是用户刚刚发来的话。参考本房间真实原文和记忆。'
                    '只输出 JSON {"action":"say|note|pass","text":"正文"}。say 是发给用户，note 只留在 Room，pass 不生成正文。'
                    '不虚构现实行动，不重复已回应的话，不披露私有感受，不输出思考过程或内部标签。没有合适内容就 pass。'
                    '本轮没有动作工具；不要声称已搜索、发送、阅读或操作外部设备。\n'
                    + json.dumps({'intent': snapshot['intent'], 'thoughts': [{'source_id': t['source_id'], 'quote': t['quote']} for t in snapshot['thoughts'][:3]],
                                  'reminder': timer['body'] if timer else None}, ensure_ascii=False))
                result = await guarded_generation(path, room, generate(scope, prompt), cursor=start['cursor'])
                output = json.loads(result['text'])
                if not isinstance(output, dict):
                    raise ValueError('invalid wake shape')
                action, text = output.get('action'), output.get('text', '')
                if action not in {'say', 'note', 'pass'} or not isinstance(text, str) or len(text) > 6000 or action != 'pass' and not text.strip():
                    raise ValueError('invalid wake result')
                text = text.strip() if action != 'pass' else ''
                usage = result.get('usage') or {}
            msg = None
            with connection(path) as db:
                db.execute('BEGIN IMMEDIATE')
                current, latest = activity(path, room, db), config(db, scope)
                if current['busy'] or current['cursor'] != start['cursor'] or latest['version'] != cfg['version']:
                    raise HTTPException(409, '聊天或设置已变化，后台草稿让位')
                if timer and db.execute('SELECT state FROM lune_wren_timers WHERE id=?', (timer['id'],)).fetchone()['state'] != 'running':
                    raise HTTPException(409, '提醒已取消')
                if action == 'say':
                    meta = {'api_session': 'lune-' + room, 'agent_id': agent, 'wren_event': eid, 'usage': usage}
                    stamp = datetime.now(timezone.utc).isoformat()
                    mid = db.execute("INSERT INTO messages(ts,direction,kind,text,meta) VALUES(?,'out','reply',?,?)", (stamp, text, json.dumps(meta, ensure_ascii=False))).lastrowid
                    msg = {'id': mid, 'ts': stamp, 'direction': 'out', 'kind': 'reply', 'text': text, 'meta': meta}
                db.execute('UPDATE lune_wren_events SET state=?,body=?,usage=?,message_id=?,finished=? WHERE id=?',
                           (action, text, json.dumps(usage), msg['id'] if msg else None, time.time(), eid))
                db.execute('UPDATE lune_wren_clock SET next_at=? WHERE scope=?', (time.time() + random.uniform(cfg['idle_min'], cfg['idle_max']), scope))
                if timer:
                    if timer['repeat_seconds']:
                        due = timer['due'] + (int((time.time() - timer['due']) // 86400) + 1) * 86400
                        db.execute("UPDATE lune_wren_timers SET state='pending',due=?,version=version+1 WHERE id=?", (due, timer['id']))
                    else:
                        db.execute("UPDATE lune_wren_timers SET state='done',version=version+1 WHERE id=?", (timer['id'],))
            if msg:
                # Persistence is complete; delivery failures must never replay the model.
                try:
                    await relay['broadcast'](relay['app_subs'], relay['app_payload'](msg))
                    if not relay['app_subs']:
                        await relay['push_to_all'](relay['notification_from_message'](msg))
                except Exception:
                    pass
            return action
        except (Exception, asyncio.CancelledError) as exc:
            state = 'interrupted' if isinstance(exc, (asyncio.CancelledError, HTTPException)) else 'failed'
            with connection(path) as db:
                db.execute("UPDATE lune_wren_events SET state=?,error=?,finished=? WHERE id=? AND state='running'", (state, '后台未完成；未投递，可查看连接后再次发起', time.time(), eid))
                if timer:
                    db.execute("UPDATE lune_wren_timers SET state=?,version=version+1 WHERE id=? AND state='running'", (state, timer['id']))
                db.execute('UPDATE lune_wren_clock SET next_at=? WHERE scope=?', (time.time() + random.uniform(cfg['idle_min'], cfg['idle_max']), scope))
            if isinstance(exc, asyncio.CancelledError):
                raise
            if not isinstance(exc, (HTTPException, httpx.HTTPError, ValueError, KeyError, TypeError)):
                raise
            return state

    @app.post('/lune/wren/{scope}/wake')
    async def wake(scope: str, request: Request):
        relay['check_auth'](request)
        value = await body(request)
        with connection(path) as db:
            cfg = config(db, scope)
            start = activity(path, SCOPES[scope][0], db)
            if not remaining(db, scope, cfg, time.time()):
                raise HTTPException(409, '今日后台回合已达上限；未请求模型')
        if start['busy'] or time.time() - start['last_at'] < 30:
            return {'state': 'deferred'}
        nonce = value.get('nonce')
        if not isinstance(nonce, str) or not 8 <= len(nonce) <= 100:
            raise HTTPException(422, '缺少幂等编号')
        if scope in tasks and not tasks[scope].done():
            raise HTTPException(409, '本房间后台正在处理')
        tasks[scope] = asyncio.create_task(tick(scope, manual=nonce))
        return {'state': 'queued'}

    async def watch():
        while True:
            await asyncio.sleep(15)
            for scope in SCOPES:
                if scope not in tasks or tasks[scope].done():
                    if scope in tasks and not tasks[scope].cancelled() and tasks[scope].exception():
                        import logging
                        logging.getLogger(__name__).error('Room 后台异常: %s', type(tasks[scope].exception()).__name__)
                    tasks[scope] = asyncio.create_task(tick(scope))

    async def shutdown():
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)

    return {'init': lambda: init(path), 'watch': watch, 'shutdown': shutdown, 'tick': tick}
