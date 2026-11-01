"""Real relay + normal model tool dispatch + native memory context + wake output."""
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

import httpx

with httpx.Client(base_url='http://127.0.0.1:8089/relay', headers={'Authorization':'Bearer fixture-owner-secret'}, trust_env=False, timeout=120) as c:
    def post(path, value):
        response = c.post(path, json=value)
        response.raise_for_status()
        return response.json()
    sent = post('/lune/rooms/gpt/send', {'text':'WREN_TOOL_TRIGGER 我想继续做海边那本小书。','nonce':uuid.uuid4().hex})
    for _ in range(500):
        rows = c.get('/lune/rooms/gpt/messages').json()
        run = next(x for x in rows['runs'] if x['id']==sent['run']['id'])
        if run['state'] not in {'pending','running'}:
            assert run['state']=='completed', run
            break
        time.sleep(.1)
    else:
        raise AssertionError('Room tool turn timeout')
    status = c.get('/lune/wren/gpt').json()
    assert len(status['thoughts'])==1 and status['thoughts'][0]['quote']=='海边那本小书',status
    assert not c.get('/lune/wren/claude').json()['thoughts']
    assert not status['settings']['enabled']
    # Simulate the passage of idle time without waiting in the test suite.
    with sqlite3.connect(os.environ['RELAY_DB']) as db:
        db.execute("UPDATE messages SET ts='2026-01-01T10:00:00+00:00' WHERE json_extract(meta,'$.api_session')='lune-gpt'")
    nonce = uuid.uuid4().hex
    post('/lune/wren/gpt/wake', {'nonce':nonce})
    for _ in range(600):
        status = c.get('/lune/wren/gpt').json()
        event = next((e for e in status['events'] if e['id']=='manual:gpt:'+nonce),None)
        if event and event['state']!='running':
            assert event['state']=='say',event
            break
        time.sleep(.1)
    else:
        raise AssertionError('wake timeout')
    assert event['usage']=={'prompt_tokens':31,'completion_tokens':12},event
    rows = c.get('/lune/rooms/gpt/messages').json()['messages']
    assert any(m['id']==event['message_id'] and 'WREN_WAKE_DELIVERED' in m['text'] for m in rows)
    post('/lune/wren/gpt/wake', {'nonce':nonce})
    time.sleep(.2)
    assert sum(e['id']=='manual:gpt:'+nonce for e in c.get('/lune/wren/gpt').json()['events'])==1
    records = [json.loads(line) for line in Path(os.environ['LUNE_TEST_REQUESTS']).read_text().splitlines()]
    wakes = [r for r in records if any('【LUNE_WREN_WAKE】' in str(m.get('content','')) for m in r.get('messages',[]))]
    assert len(wakes)==1 and not wakes[0].get('tools'), len(wakes)
    material = json.dumps(wakes[0],ensure_ascii=False)
    assert '海边那本小书' in material and '系统本轮自动装配的 Room 状态' in material
    # Save only synthetic, authenticated HTTP data for optional read-only browser QA.
    target = os.environ.get('LUNE_WREN_PREVIEW_DIR')
    if target:
        file = Path(target)/'wren-fixture.json'
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(json.dumps(status,ensure_ascii=False),encoding='utf-8')
    print('Wren HTTP PASS: normal model tool → evidenced thought → full room context → tool-free wake → original timeline, usage, idempotency and room isolation')
