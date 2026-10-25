"""Room-bound GPT/Claude cinema guests with durable cursors and idempotent posts."""
import asyncio
import base64
import json
import logging
import os
import sqlite3
import time
import uuid

import httpx
from fastapi import HTTPException, Request

try:
    from .lune_cinema import BASE
    from .lune_continuity import connection
except ImportError:
    from lune_cinema import BASE
    from lune_continuity import connection


def init(path):
    with connection(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS lune_cinema_guests(
          room_id TEXT NOT NULL, agent TEXT NOT NULL, enabled INTEGER NOT NULL,
          cursors TEXT NOT NULL, last_at REAL NOT NULL DEFAULT 0,
          pending_text TEXT, pending_nonce TEXT, pending_time INTEGER,
          pending_cursors TEXT, retry_after REAL NOT NULL DEFAULT 0,
          PRIMARY KEY(room_id,agent)
        );
        ''')


def register(app, relay):
    path = relay['DB_PATH']
    locks = {'gpt': asyncio.Lock(), 'claude': asyncio.Lock()}

    async def call(method, target, body=None, timeout=10):
        async with httpx.AsyncClient(base_url=BASE, trust_env=False, timeout=timeout) as client:
            response = await client.request(method, target, json=body)
        response.raise_for_status()
        return response.json()

    @app.get('/lune/cinema/guests')
    async def guests(request: Request):
        relay['check_auth'](request)
        with connection(path) as db:
            rows = db.execute('SELECT room_id,agent,enabled FROM lune_cinema_guests WHERE enabled=1').fetchall()
        return {'guests': [dict(r) for r in rows]}

    @app.post('/lune/cinema/guests')
    async def set_guests(request: Request):
        relay['check_auth'](request)
        body = await request.json()
        agents = body.get('agents') if isinstance(body, dict) else None
        if not isinstance(agents, list) or len(agents) > 2 or any(a not in {'gpt', 'claude'} for a in agents) or len(set(agents)) != len(agents):
            raise HTTPException(422, '请选择 GPT、Claude 或暂不邀请')
        try:
            room = (await call('GET', '/api/rooms'))['activeRoom']
            if not room or room['id'] != body.get('room_id'):
                raise HTTPException(409, '观影房间已变化，请刷新')
            media = next((m for m in (await call('GET', '/api/media'))['items'] if m['id'] == room['mediaId']), None)
            if agents and ((media or {}).get('aiPackage') or {}).get('status') != 'ready':
                raise HTTPException(409, '先准备这部影片的 AI 观影包，再邀请模型')
            messages = (await call('GET', f"/api/rooms/{room['id']}/messages"))['messages']
        except httpx.HTTPError as exc:
            raise HTTPException(503, '影院暂未连接') from exc
        cursor = {'mediaMs': max(0, room['lastPositionMs']), 'messageId': max((m['id'] for m in messages), default=0), 'observationSequence': 0}
        with connection(path) as db:
            db.execute('BEGIN IMMEDIATE')
            already = {r['agent'] for r in db.execute('SELECT agent FROM lune_cinema_guests WHERE room_id=? AND enabled=1', (room['id'],))}
            for agent in {'gpt', 'claude'} - set(agents):
                db.execute('''UPDATE lune_cinema_guests SET enabled=0,pending_text=NULL,pending_nonce=NULL,
                    pending_cursors=NULL WHERE room_id=? AND agent=?''', (room['id'],agent))
            for agent in agents:
                if agent in already:
                    continue  # Preserve its cursor and an undelivered reply on an unchanged invitation.
                else:
                    db.execute('''INSERT INTO lune_cinema_guests(room_id,agent,enabled,cursors)
                       VALUES(?,?,1,?) ON CONFLICT(room_id,agent) DO UPDATE SET enabled=1,cursors=excluded.cursors,
                       last_at=0,retry_after=0,pending_text=NULL,pending_nonce=NULL,pending_cursors=NULL''',
                       (room['id'],agent,json.dumps(cursor)))
        return {'room_id': room['id'], 'agents': agents}

    async def run_guest(room, row, *, generate_fn=None):
        agent, rid = row['agent'], room['id']
        async with locks[agent]:
            with connection(path) as db:
                state = db.execute('SELECT * FROM lune_cinema_guests WHERE room_id=? AND agent=? AND enabled=1', (rid,agent)).fetchone()
            if not state or state['retry_after'] > time.time():
                return
            async def deliver(text, nonce, media_time, cursors):
                current = (await call('GET', '/api/rooms'))['activeRoom']
                if not current or current['id'] != rid:
                    return
                await call('POST', f'/api/rooms/{rid}/messages', {'senderName': 'GPT' if agent=='gpt' else 'Claude',
                    'senderKind':'ai','content':text,'mediaTimeMs':media_time,'nonce':nonce})
                with connection(path) as db:
                    db.execute('''UPDATE lune_cinema_guests SET cursors=?,last_at=?,pending_text=NULL,
                        pending_nonce=NULL,pending_cursors=NULL,retry_after=0 WHERE room_id=? AND agent=? AND pending_nonce=? AND enabled=1''',
                        (json.dumps(cursors),time.time(),rid,agent,nonce))
            try:
                if state['pending_text']:
                    await deliver(state['pending_text'], state['pending_nonce'], state['pending_time'],json.loads(state['pending_cursors']))
                    return
                cursors = json.loads(state['cursors'])
                tick = (await call('POST', f'/api/rooms/{rid}/ai-tick',
                    {'consumerName': 'GPT' if agent=='gpt' else 'Claude', 'cursors': cursors}))['tick']
                upcoming = tick['cursors']
                human = [m for m in tick['newMessages'] if m['senderKind']=='user']
                film = tick['playback']['state']=='playing' and bool(tick['dialogueDelta'] or tick['motionEvents'])
                react = bool(human) or film and time.time()-state['last_at'] >= 100
                if not react:
                    with connection(path) as db:
                        db.execute('UPDATE lune_cinema_guests SET cursors=?,retry_after=0 WHERE room_id=? AND agent=? AND enabled=1', (json.dumps(upcoming),rid,agent))
                    return
                payload = {'film':tick['room']['mediaTitle'],'playheadMs':tick['playback']['playheadMs'],
                           'state':tick['playback']['state'],'dialogue':tick['dialogueDelta'][-20:],
                           'messages':tick['newMessages'][-20:],'motionEvents':tick['motionEvents'][-5:],
                           'visualAvailable':bool(tick['storyboards'])}
                frames = []
                if tick['storyboards']:
                    chosen = tick['storyboards'][-1]
                    try:
                        async with httpx.AsyncClient(base_url=BASE, trust_env=False, timeout=10) as client:
                            frame = await client.get(f'/api/rooms/{rid}/ai-frame',params={'storyboardRef':chosen['storyboardRef'],'mediaTimeMs':chosen['mediaTimeMs']})
                        frame.raise_for_status()
                        if frame.headers.get('content-type','').startswith('image/jpeg') and len(frame.content) <= 1000000:
                            frames = [base64.b64encode(frame.content).decode('ascii')]
                    except (httpx.HTTPError, KeyError):
                        pass
                prompt = ('【LUNE_CINEMA_TICK】这是影院已经播放过的增量片段。请像一起看片的朋友一样自然、简短地接话；'
                    '用户刚发言时优先回应，不要每段字幕都说话，也不要剧透。只根据下列资料判断；有画面时以实际图片为准，'
                    '没有画面时不要推断视觉细节。\n'+json.dumps(payload,ensure_ascii=False)[:15000])
                if generate_fn:
                    result = await generate_fn(agent,prompt,frames)
                else:
                    import httpx as _httpx
                    async with _httpx.AsyncClient(timeout=60, trust_env=False) as client:
                        response = await client.post('http://127.0.0.1:3020/loop/native/generate',
                          headers={'Authorization':'Bearer '+os.environ['RELAY_SECRET']},
                          json={'agent':agent,'room':'group','purpose':'cinema','prompt':prompt,'frames':frames})
                        response.raise_for_status()
                        result = response.json()
                value = json.loads(result['text'])
                if not isinstance(value,dict) or value.get('action') not in {'say','silent'}:
                    raise ValueError('cinema model returned invalid action')
                if value['action']=='silent':
                    with connection(path) as db:
                        db.execute('UPDATE lune_cinema_guests SET cursors=?,last_at=?,retry_after=0 WHERE room_id=? AND agent=? AND enabled=1', (json.dumps(upcoming),time.time(),rid,agent))
                    return
                text = value.get('text','')
                if not isinstance(text,str) or not 1 <= len(text.strip()) <= 800:
                    raise ValueError('cinema model returned invalid text')
                nonce = str(uuid.uuid4())
                with connection(path) as db:
                    db.execute('''UPDATE lune_cinema_guests SET pending_text=?,pending_nonce=?,pending_time=?,pending_cursors=?
                        WHERE room_id=? AND agent=? AND enabled=1''', (text.strip(),nonce,tick['playback']['playheadMs'],json.dumps(upcoming),rid,agent))
                with connection(path) as db:
                    allowed = db.execute('SELECT enabled FROM lune_cinema_guests WHERE room_id=? AND agent=?', (rid,agent)).fetchone()
                if allowed and allowed['enabled']:
                    await deliver(text.strip(),nonce,tick['playback']['playheadMs'],upcoming)
            except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError, asyncio.TimeoutError):
                with connection(path) as db:
                    db.execute('UPDATE lune_cinema_guests SET retry_after=? WHERE room_id=? AND agent=?', (time.time()+45,rid,agent))

    async def tick(generate_fn=None):
        try:
            room = (await call('GET','/api/rooms', timeout=2))['activeRoom']
        except (httpx.HTTPError, KeyError):
            return
        if not room:
            return
        with connection(path) as db:
            rows = db.execute('SELECT * FROM lune_cinema_guests WHERE room_id=? AND enabled=1', (room['id'],)).fetchall()
        if rows:
            await asyncio.gather(*(run_guest(room,row,generate_fn=generate_fn) for row in rows))

    async def watch():
        while True:
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger(__name__).exception('影院共看轮询失败')
            await asyncio.sleep(8)

    return {'init':lambda:init(path),'tick':tick,'watch':watch}
