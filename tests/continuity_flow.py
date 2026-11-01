"""Actual relay/model HTTP for Duet/threads; synthetic providers and CLI only."""
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
import httpx

with httpx.Client(base_url='http://127.0.0.1:8089/relay',headers={'Authorization':'Bearer fixture-owner-secret'},trust_env=False,timeout=90) as c:
    def post(path,body):
        r=c.post(path,json=body);r.raise_for_status();return r.json()
    def send(room,text):
        sent=post('/lune/rooms/'+room+'/send',{'text':text,'nonce':uuid.uuid4().hex})
        for _ in range(500):
            row=c.get('/lune/rooms/'+room+'/messages').json()
            run=next(x for x in row['runs'] if x['id']==sent['run']['id'])
            if run['state'] not in {'pending','running'}:
                assert run['state']=='completed',run
                return row
            time.sleep(.1)
        raise AssertionError('turn timeout')
    round=post('/lune/duet',{'room':'gpt','label':'合成独立日记','nonce':uuid.uuid4().hex,'lock_seconds':3600})
    written=post('/lune/duet/'+round['id']+'/write',{'body':'DUET_PARTNER_DRAFT_SECRET'})
    assert 'DUET_PARTNER_DRAFT_SECRET' not in json.dumps(written)
    post('/lune/duet/'+round['id']+'/generate',{})
    for _ in range(200):
        value=c.get('/lune/duet?room=gpt').json()
        if any(e['author']=='assistant' and e['state']=='ready' for e in value['rounds'][0]['entries']):break
        time.sleep(.1)
    else:raise AssertionError(value)
    assert 'DUET_PARTNER_DRAFT_SECRET' not in json.dumps(value)
    records=[json.loads(x) for x in Path(os.environ['LUNE_TEST_REQUESTS']).read_text().splitlines()]
    generation=[r for r in records if any('Duet 独立日记' in str(m.get('content','')) for m in r.get('messages',[]))]
    assert generation and all(not r.get('tools') and 'DUET_PARTNER_DRAFT_SECRET' not in json.dumps(r) for r in generation)
    with sqlite3.connect(os.environ['RELAY_DB']) as db:
        db.execute('UPDATE lune_duet_rounds SET unlock_at=0 WHERE id=?',(round['id'],))
    first=c.get('/lune/duet?room=gpt').json();second=c.get('/lune/duet?room=gpt').json()
    assert first==second and len(first['notifications'])==1
    assert 'DUET_PARTNER_DRAFT_SECRET' in json.dumps(first)
    send('gpt','DUET_OPEN_NOTICE_TRIGGER')
    records=[json.loads(x) for x in Path(os.environ['LUNE_TEST_REQUESTS']).read_text().splitlines()]
    assert any('DUET_PARTNER_DRAFT_SECRET' in str(m.get('content','')) and m.get('role')=='system' for r in records for m in r.get('messages',[]))
    rows=send('claude','CLAUDE_CONTINUITY_PRIVACY_TRIGGER')
    records=[json.loads(x) for x in Path(os.environ['LUNE_TEST_REQUESTS']).read_text().splitlines()]
    # No diary of the GPT private room in the other participant's requests.
    for r in records:
        if r.get('model')=='fixture-claude':assert 'DUET_PARTNER_DRAFT_SECRET' not in json.dumps(r)
    with sqlite3.connect(os.environ['RELAY_DB']) as db:
        db.execute("UPDATE messages SET ts='2026-01-01T10:00:00+00:00' WHERE json_extract(meta,'$.api_session')='lune-gpt'")
    state=post('/lune/continuity/gpt/threads',{})
    assert state['states']['gpt']=='pass',state
    assert post('/lune/continuity/gpt/threads',{})['states']['gpt']=='unchanged'
    if os.environ.get('LUNE_CLAUDE_ENABLED')=='1':
        post('/app/loop/agents',{'agent':'claude','connection_mode':'claude_subscription','subscription_model':'sonnet'})
        for prompt in ('CLI_PERSISTENT_FIRST','CLI_PERSISTENT_SECOND'):
            rows=send('claude',prompt)
            assert any('FIXTURE_CLAUDE_REPLY' in m['text'] for m in rows['messages'])
        status=c.get('/app/loop/claude/status').json()
        assert status['sessions']['claude']['running'],status
    print('Continuity HTTP PASS: independent tool-free Duet generation, hidden drafts, shared unlock and once-only notice, room isolation, idle PASS cursor and official-CLI protocol fixture')
