"""Actual relay watcher -> model fixture -> persisted reminder -> same-room message."""
import time
import uuid
import httpx

with httpx.Client(base_url='http://127.0.0.1:8089/relay',headers={'Authorization':'Bearer fixture-owner-secret'},timeout=20,trust_env=False) as client:
    tag='CHECKLIST_HTTP_'+uuid.uuid4().hex[:8]
    due=int(time.time()*1000)+1600
    created=client.post('/lune/workspace',json={'kind':'todo','scope':'gpt','title':tag,'content':'','data':{
        'owner':'user','done':False,'cycle':'timed','timezone':'Asia/Shanghai',
        'trigger_at':due,'alarm_room':'gpt'
    }})
    created.raise_for_status()
    item=created.json()['item']
    for _ in range(60):
        states=client.get('/lune/checklist/alarms').json()['items']
        alarm=next((x for x in states if x['todo_id']==item['id']),None)
        if alarm and alarm['state']=='delivered':break
        time.sleep(.5)
    else:raise AssertionError(('alarm was not delivered',alarm))
    messages=client.get('/lune/rooms/gpt/messages').json()['messages']
    delivered=[x for x in messages if x.get('meta',{}).get('checklist_alarm')==item['id']]
    assert len(delivered)==1 and 'CHECKLIST_ALARM_DELIVERED' in delivered[0]['text'],delivered
    assert alarm['message_id']==delivered[0]['id']
    assert not any(x.get('meta',{}).get('checklist_alarm')==item['id'] for x in client.get('/lune/rooms/claude/messages').json()['messages'])
    print('Checklist HTTP PASS: scheduled todo -> durable claim -> real model fixture -> one GPT message; Claude isolated')
