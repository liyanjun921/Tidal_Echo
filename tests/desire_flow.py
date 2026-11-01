"""Real HTTP: tutorial gates, immediate pulse, verified tool action, E, clock, read-only base."""
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

import httpx

with httpx.Client(base_url='http://127.0.0.1:8089/relay',headers={'Authorization':'Bearer fixture-owner-secret'},trust_env=False,timeout=120) as c:
    def post(path,value):
        response=c.post(path,json=value);response.raise_for_status();return response.json()
    def status():return c.get('/lune/wren/gpt').json()
    old=status();cfg=old['settings']['desire']
    for key in ['enabled','coupling','self_drive','habits','experiences','message_pulses','semantic_pulses']:cfg[key]=True
    cfg['circadian']['enabled']=True
    response=c.patch('/lune/wren/gpt',json={'version':old['settings']['version'],'desire':cfg});response.raise_for_status()
    sent=post('/lune/rooms/gpt/send',{'text':'DESIRE_TOOL_TRIGGER 帮我记下海边那本小书。','nonce':uuid.uuid4().hex})
    for _ in range(500):
        runs=c.get('/lune/rooms/gpt/messages').json()['runs']
        run=next(x for x in runs if x['id']==sent['run']['id'])
        if run['state'] not in {'pending','running'}:
            assert run['state']=='completed',run
            break
        time.sleep(.1)
    else:raise AssertionError('desire tool turn timeout')
    value=status();body=value['body']
    assert len(body['drive'])==15 and body['circadian']['enabled']
    assert body['drive_display']!=body['drive']
    assert any(a['tool']=='lune_workspace' and a['intent']=='make' for a in body['actions']),body['actions']
    assert any(e['body']['content'].startswith('DESIRE_REAL_E') for e in body['experiences']),body['experiences']
    semantic=post('/lune/rooms/gpt/send',{'text':'我想弄懂星星为什么会在夜空发光。','nonce':uuid.uuid4().hex})
    for _ in range(500):
        runs=c.get('/lune/rooms/gpt/messages').json()['runs']
        run=next(x for x in runs if x['id']==semantic['run']['id'])
        if run['state'] not in {'pending','running'}:
            assert run['state']=='completed',run
            break
        time.sleep(.1)
    else:raise AssertionError('local BGE classifier timeout')
    classified=next(x for x in status()['body']['local_classifier'] if x['message_id']==semantic['id'])
    assert classified['status'] in {'matched','below-threshold'},classified
    with sqlite3.connect(os.environ['RELAY_DB']) as db:
        canonical=db.execute("SELECT value FROM lune_wren_drives WHERE scope='gpt'").fetchone()[0]
    for _ in range(3):status()
    with sqlite3.connect(os.environ['RELAY_DB']) as db:
        assert db.execute("SELECT value FROM lune_wren_drives WHERE scope='gpt'").fetchone()[0]==canonical,'GET wrote base'
        db.execute("UPDATE messages SET ts='2026-01-01T10:00:00+00:00' WHERE json_extract(meta,'$.api_session')='lune-gpt'")
        state=json.loads(canonical);state['at']-=301
        db.execute("UPDATE lune_wren_drives SET value=? WHERE scope='gpt'",(json.dumps(state),))
    nonce=uuid.uuid4().hex
    post('/lune/wren/gpt/wake',{'nonce':nonce})
    for _ in range(600):
        value=status()
        event=next((e for e in value['events'] if e['id']=='manual:gpt:'+nonce),None)
        if event and event['state']!='running':
            assert event['state']=='say',event
            break
        time.sleep(.1)
    else:raise AssertionError('desire wake timeout')
    assert all(e['consumed'] for e in value['body']['experiences'])
    assert any(a['intent']=='reach_out' for a in value['body']['actions'])
    assert any(e['drive']=='curiosity' and '亲历' in e['reason'] for e in value['body']['changes'])
    target=os.environ.get('LUNE_WREN_PREVIEW_DIR')
    if target:(Path(target)/'wren-fixture.json').write_text(json.dumps(value,ensure_ascii=False))
    # Exercise the exact legacy fallback, then retain the enabled state for restart QA.
    cfg['circadian']['enabled']=False
    response=c.patch('/lune/wren/gpt',json={'version':value['settings']['version'],'desire':cfg});response.raise_for_status()
    off=status();assert off['body']['drive']==off['body']['drive_display']
    cfg['circadian']['enabled']=True
    response=c.patch('/lune/wren/gpt',json={'version':off['settings']['version'],'desire':cfg});response.raise_for_status()
    print('Desire HTTP PASS: real message pulses → actual workspace operation proof → E snapshot/consumption → clock overlay without GET base writes → verified delivery fall → off identity + restart-ready gates')
