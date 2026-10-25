"""Pinned native Xinchao through real HTTP, current Ombre and actor tool loop."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import xinchao_runtime as xc,ombre_runtime as ob

called=set()
def native(name,args=None,scope='gpt'):
    result=asyncio.run(xc.call(scope,name,args));called.add(name)
    assert not result.get('isError'),result
    return result

def text(value):return json.dumps(value,ensure_ascii=False)

with httpx.Client(base_url='http://127.0.0.1:8089/relay',headers={'Authorization':'Bearer fixture-owner-secret'},trust_env=False,timeout=120) as c:
    def get(tail):
        res=c.get('/lune/xinchao/gpt/'+tail);res.raise_for_status();return res.json()
    def post(tail,value):
        res=c.post('/lune/xinchao/gpt/'+tail,json=value);res.raise_for_status();return res.json()
    status=get('status');assert status['running'] and len(status['tools'])==10,status
    for scope in xc.SCOPES:
        other=c.get('/lune/xinchao/'+scope+'/status').json();assert other['running'],other
    initial=get('view/snapshot');assert len(initial['drives'])==11
    assert c.get('/lune/xinchao/gpt/view/box').status_code==404
    assert c.get('/lune/xinchao/gpt/status',headers={'Authorization':'Bearer wrong'}).status_code==401
    sent=c.post('/lune/rooms/gpt/send',json={'text':'XC_BOX_TRIGGER 请把自己的测试纸条留在自己的匣子。','nonce':uuid.uuid4().hex}).json()
    for _ in range(600):
        room=c.get('/lune/rooms/gpt/messages').json()
        run=next(r for r in room['runs'] if r['id']==sent['run']['id'])
        if run['state'] not in {'running','pending'}:
            assert run['state']=='completed',run;break
        time.sleep(.1)
    else:raise AssertionError('Xinchao model tool timeout')
    assert 'XC_SECRET_ACTUAL_TOOL_RESULT' in text(native('xinchao_box',{'action':'list'}))
    assert 'XC_SECRET_ACTUAL_TOOL_RESULT' not in text(room)
    assert 'XC_PRIVATE_TITLE' not in text(room)
    for scope in ['claude','group_gpt','group_claude']:
        assert 'XC_SECRET_ACTUAL_TOOL_RESULT' not in text(native('xinchao_box',{'action':'list'},scope))
    for page in ['snapshot','personality','timeline','cabin','connect']:
        assert 'XC_SECRET_ACTUAL_TOOL_RESULT' not in text(get('view/'+page))
    tools=(asyncio.run(xc.rpc('gpt','tools/list')))['tools']
    dims=next(t for t in tools if t['name']=='xinchao_personality_reflect')['inputSchema']['properties']['dimensions']['items']['properties']['key']['enum']
    native('xinchao_personality_reflect',{'month':'2026-10','dimensions':[{'key':key,'score':60,'reason':'XC_PRIVATE_REASON'} for key in dims],'period_summary':'XC_PRIVATE_MONTH_SUMMARY'})
    person=get('view/personality');assert len(person['dimensions'])==14
    assert 'XC_PRIVATE_REASON' not in text(person) and 'XC_PRIVATE_MONTH_SUMMARY' not in text(person)
    native('xinchao_personality_reflect',{'month':'2026-10','dimensions':[{'key':key,'score':90,'reason':'changed'} for key in dims]})
    assert all(d['score']==60 for d in get('view/personality')['dimensions'])
    native('xinchao_personality_stats',{})
    native('xinchao_anchor_update',{'action':'add','anchor':{'key':'test-evidence','label':'认真核对证据','description':'XC_PRIVATE_ANCHOR_REASON'}})
    assert get('view/snapshot')['personality']['anchors'][0]['label']=='认真核对证据'
    native('xinchao_awareness',{'action':'scan'})
    native('xinchao_handoff_note',{'event_id':uuid.uuid4().hex,'note':'合成测试已检查工具，下一步检查信箱。'})
    native('xinchao_context',{'mode':'turn'})
    native('xinchao_event',{'event_id':uuid.uuid4().hex,'interaction_type':'reflection','tone':'calm'})
    letter=post('cabin/note',{'event_id':uuid.uuid4().hex,'from':'ai','content':'XC_LOCKED_USER_LETTER','locked':True})
    assert letter['note']['from']=='user'
    assert 'XC_LOCKED_USER_LETTER' not in text(native('xinchao_cabin_inbox'))
    res=c.patch('/lune/xinchao/gpt/cabin/note',json={'id':letter['note']['id'],'locked':False});res.raise_for_status()
    assert 'XC_LOCKED_USER_LETTER' in text(native('xinchao_cabin_inbox'))
    native('xinchao_cabin_note',{'event_id':uuid.uuid4().hex,'content':'XC_AI_REPLY_LETTER'})
    assert 'XC_AI_REPLY_LETTER' in text(get('view/cabin'))
    for scope in ['claude','group_gpt','group_claude']:
        assert c.get('/lune/xinchao/'+scope+'/view/cabin').json()['notes']==[]
    entry=post('cabin/ledger',{'event_id':uuid.uuid4().hex,'type':'expense','item':'XC_LEDGER','amount':12.34})['entry']
    res=c.patch('/lune/xinchao/gpt/cabin/ledger',json={'id':entry['id'],'amount':15.5});res.raise_for_status()
    assert get('view/cabin')['totals']['expense']==15.5
    res=c.request('DELETE','/lune/xinchao/gpt/cabin/ledger',json={'id':entry['id']});res.raise_for_status()
    assert get('view/cabin')['totals']['expense']==0
    memory=get('view/memory-map');assert memory['available'] and memory['stats']['source']=='existing-ombre',memory
    assert memory['stars'],memory
    unlocked=next(r for r in memory['stars'] if not r['locked'])
    preview=get('view/memory-bucket?id='+unlocked['id']);assert preview['available'],preview
    for locked in [r for r in memory['stars'] if r['locked']]:
        hidden=get('view/memory-bucket?id='+locked['id']);assert not hidden['available'] and hidden['preview']=='',hidden
    event_id=uuid.uuid4().hex
    nativebody={'id':event_id,'text':'这是已经发出的合成表达'}
    first=asyncio.run(xc.request('gpt','/lune-host/reflux','POST',nativebody));second=asyncio.run(xc.request('gpt','/lune-host/reflux','POST',nativebody))
    assert first['applied'] and not second['applied'] and first['revision']==second['revision'],(first,second)
    # One native delivery becomes exactly one existing Wren timer and one saved reply.
    wren=c.get('/lune/wren/gpt').json()
    for pending in wren['timers']:
        if pending['state']=='pending' and pending['nonce'].startswith('xinchao:'):
            cancelled=c.patch('/lune/wren/gpt/timers/'+pending['id'],json={'version':pending['version']});cancelled.raise_for_status()
    res=c.patch('/lune/wren/gpt',json={'version':wren['settings']['version'],'daily_limit':10});res.raise_for_status()
    with sqlite3.connect(os.environ['RELAY_DB']) as db:
        db.execute("UPDATE messages SET ts='2026-01-01T10:00:00+00:00' WHERE json_extract(meta,'$.api_session')='lune-gpt'")
    bridge_body={'event_id':uuid.uuid4().hex,'message':'XC_BRIDGE_REAL_NOTE','reason':'user_note'}
    delivery=post('bridge',bridge_body)
    assert post('bridge',bridge_body)['deliveryId']==delivery['deliveryId']
    for _ in range(1800):
        with sqlite3.connect(os.environ['RELAY_DB']) as db:
            timer=db.execute('SELECT id,state FROM lune_wren_timers WHERE nonce=?',('xinchao:'+delivery['deliveryId'],)).fetchone()
            if timer and timer[1]=='done':
                event=db.execute('SELECT state,message_id FROM lune_wren_events WHERE id=?',('timer:'+timer[0]+':1',)).fetchone()
                break
        time.sleep(.1)
    else:raise AssertionError(('native SSE bridge did not deliver through Wren',get('status'),c.get('/lune/wren/gpt').json()['events'][:6]))
    with sqlite3.connect(os.environ['RELAY_DB']) as db:
        assert db.execute('SELECT count(*) FROM lune_wren_timers WHERE nonce=?',('xinchao:'+delivery['deliveryId'],)).fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM messages WHERE json_extract(meta,'$.wren_event') LIKE ?",('%'+timer[0]+'%',)).fetchone()[0]==1
    native_bridge=json.loads((xc.root()/'gpt/bridge.json').read_text())
    assert next(r for r in native_bridge['deliveries'] if r['id']==delivery['deliveryId'])['status']=='delivered'
    cfg=get('status')['settings']
    res=c.patch('/lune/xinchao/gpt/settings',json={'version':cfg['version'],'private_dreams':True,'model_enabled':True,'model_daily_limit':1});res.raise_for_status()
    for _ in range(100):
        try:
            value=get('view/snapshot')
            if value['capabilities']['privateDreamText']:break
        except httpx.HTTPError:pass
        time.sleep(.2)
    else:raise AssertionError('native setting restart timeout')
    assert 'XC_PRIVATE_REASON' in text(get('view/personality'))
    with httpx.Client(timeout=30,trust_env=False) as loop:
        endpoint='http://127.0.0.1:3020/xinchao-provider/gpt/v1/chat/completions'
        key={'Authorization':'Bearer '+xc.credential('gpt','provider')}
        assert loop.post(endpoint,json={'messages':[{'role':'user','content':'测试心潮工具外的模型任务'}]},headers=key).status_code==200
        assert loop.post(endpoint,json={'messages':[{'role':'user','content':'第二次应被预算拦下'}]},headers=key).status_code==429
    cfg=get('status')['settings'];res=c.patch('/lune/xinchao/gpt/settings',json={'version':cfg['version'],'private_dreams':False,'model_enabled':False});res.raise_for_status()
    for _ in range(100):
        try:
            value=get('view/snapshot')
            if not value['capabilities']['privateDreamText']:break
        except httpx.HTTPError:pass
        time.sleep(.2)
    assert 'XC_SECRET_ACTUAL_TOOL_RESULT' not in text(get('status'))
    assert called==xc.TOOLS,(called,xc.TOOLS)
    target=os.environ.get('LUNE_XINCHAO_PREVIEW_DIR')
    if target:
        fixture={'status':get('status')}
        for page in ['snapshot','timeline','cabin','memory-map','personality']:
            fixture[page]=get('view/'+page)
        fixture['memory-previews']={r['id']:get('view/memory-bucket?id='+r['id']) for r in memory['stars'][:8]}
        Path(target).mkdir(parents=True,exist_ok=True)
        (Path(target)/'xinchao-fixture.json').write_text(json.dumps(fixture,ensure_ascii=False))
    print('Xinchao HTTP PASS: 10 native tools, actual model tool with private-card redaction, four scopes, 14-dimension immutable assessment, locked cabin, ledger CRUD, existing Ombre map, idempotent reflux, native restart, current-model budget and privacy gates')
