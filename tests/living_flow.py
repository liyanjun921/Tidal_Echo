"""Isolated real HTTP chat path with synthetic model responses, no real account."""
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

import httpx


with httpx.Client(base_url='http://127.0.0.1:8089/relay',headers={'Authorization':'Bearer fixture-owner-secret'},trust_env=False,timeout=90) as c:
    def post(path,value):
        response=c.post(path,json=value);response.raise_for_status();return response.json()

    def view(scope='gpt'):
        result=c.get('/lune/living/'+scope);result.raise_for_status();return result.json()

    def send(room,text):
        result=post('/lune/rooms/'+room+'/send',{'text':text,'nonce':uuid.uuid4().hex})
        for _ in range(600):
            state=c.get('/lune/rooms/'+room+'/messages').json()
            run=next(x for x in state['runs'] if x['id']==result['run']['id'])
            if run['state'] not in {'pending','running'}:
                assert run['state']=='completed',run
                return result,run
            time.sleep(.1)
        raise AssertionError('still-true model turn timeout')

    def requests():return [json.loads(line) for line in Path(os.environ['LUNE_TEST_REQUESTS']).read_text().splitlines()]
    def snapshots():
        return [m['content'] for r in requests() for m in r.get('messages',[])
                if m.get('role')=='system' and isinstance(m.get('content'),str) and m['content'].startswith('当前背景由 still-true 管理')]

    initial=view()
    assert not initial['today'] and not initial['fresh'] and initial['settings']['enabled']
    assert all(not view(scope)['today'] for scope in ('claude','group_gpt','group_claude'))
    before=len(requests())
    sent,run=send('gpt','LIVING_WRITE_TRIGGER 我今天晚饭吃了青菜。妈妈准备下周回家，现在还在我这里。')
    written=view();assert written['today']['晚饭']['v']=='今天晚饭吃了青菜',written
    assert written['fresh'][0]['key']=='家人来访' and written['fresh'][0]['value']=='妈妈现在还在我这里，准备下周回家'
    assert written['fresh'][0]['recheck_after'] and written['events'][0]['source_id']==sent['id']
    assert {e['tool'] for e in written['events']} >= {'today_set','ctx_set'}
    emitted=requests()[before:]
    tools={t['function']['name'] for r in emitted for t in r.get('tools',[]) if t.get('type')=='function'}
    assert {'today_set','today_get','ctx_set','ctx_get','ctx_drop'} <= tools
    assert any(m.get('role')=='tool' and '今天晚饭吃了青菜' in str(m.get('content')) for r in emitted for m in r.get('messages',[]))
    assert any(m.get('role')=='tool' and '妈妈现在还在我这里' in str(m.get('content')) for r in emitted for m in r.get('messages',[]))
    assert all(not view(scope)['fresh'] and not view(scope)['today'] for scope in ('claude','group_gpt','group_claude'))
    # The first request is built before its tool calls; the next request must
    # carry the new complete snapshot.

    send('gpt','LIVING_FOLLOWUP_TRIGGER 这周的安排呢？')
    next_request=next(r for r in reversed(requests()) if 'LIVING_FOLLOWUP_TRIGGER' in json.dumps(r,ensure_ascii=False))
    assert any(m.get('role')=='system' and '妈妈现在还在我这里' in str(m.get('content')) for m in next_request['messages'])
    assert all('<state_snapshot' not in str(m.get('content')) for m in c.get('/lune/rooms/gpt/messages').json()['messages'])

    _,ended=send('gpt','LIVING_DROP_TRIGGER 妈妈今天已经回家了。')
    current=view();assert not current['fresh'] and not current['stale']
    assert any(x['key']=='家人来访' and x['archive_reason']=='dropped' for x in current['archive'])
    send('gpt','LIVING_AFTER_DROP_TRIGGER 现在呢？')
    after=next(r for r in reversed(requests()) if 'LIVING_AFTER_DROP_TRIGGER' in json.dumps(r,ensure_ascii=False))
    current_block=next(m['content'] for m in after['messages'] if m.get('role')=='system' and str(m.get('content','')).startswith('当前背景由 still-true 管理'))
    assert '妈妈现在还在我这里' not in current_block
    assert '未列出的旧项不再作为当前事实' in current_block
    assert current['today']['晚饭']['v']=='今天晚饭吃了青菜'

    set_result=post('/lune/living/gpt/write',{'name':'ctx_set','arguments':{'key':'申请季','value':'这阵子准备材料','ttl_days':21},'nonce':'owner-'+uuid.uuid4().hex,'version':current['version']})
    assert set_result['ok'] and view()['fresh'][0]['key']=='申请季'
    config=view()['settings']
    r=c.patch('/lune/living/gpt/settings',json={'enabled':False,'version':config['version']});r.raise_for_status()
    send('gpt','LIVING_DISABLED_TRIGGER')
    disabled=next(r for r in reversed(requests()) if 'LIVING_DISABLED_TRIGGER' in json.dumps(r,ensure_ascii=False))
    assert not any(t['function']['name'] in {'today_set','today_get','ctx_set','ctx_get','ctx_drop'} for t in disabled.get('tools',[]) if t.get('type')=='function')
    assert not any(str(m.get('content','')).startswith('当前背景由 still-true 管理') for m in disabled['messages'])
    r=c.patch('/lune/living/gpt/settings',json={'enabled':True,'version':config['version']+1});r.raise_for_status()

    with sqlite3.connect(os.environ['RELAY_DB']) as db:
        audit=db.execute('SELECT tool,key,source_id,result FROM lune_living_events WHERE scope=?',('gpt',)).fetchall()
        assert all('今天晚饭吃了青菜' not in json.dumps(row,ensure_ascii=False) for row in audit)
    target=os.environ.get('LUNE_LIVING_PREVIEW_DIR')
    if target:
        p=Path(target);p.mkdir(parents=True,exist_ok=True)
        (p/'living-fixture.json').write_text(json.dumps({'gpt':view(),'claude':view('claude'),'group_gpt':view('group_gpt'),'group_claude':view('group_claude')},ensure_ascii=False))
    print('Still-true HTTP PASS: five native tools, source-quoted writes/reads/drop, four-room isolation, current snapshot next turn, disabled path and private audit')
