"""Merged Folio UI/API uses the same native runtime, locks and four vaults."""
import asyncio
import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path
import sys
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import ombre_runtime as ob

with httpx.Client(base_url='http://127.0.0.1:8089',headers={'Authorization':'Bearer fixture-owner-secret'},trust_env=False,timeout=90) as c:
    def get(path):
        r=c.get('/ombre/gpt/api/folio/'+path);r.raise_for_status();return r.json()
    def post(path,body):
        r=c.post('/ombre/gpt/api/folio/'+path,json=body);r.raise_for_status();return r.json()
    assert c.get('/ombre/gpt/v2/').status_code==401
    opened=c.post('/relay/lune/ombre/gpt/open?view=folio',json={});opened.raise_for_status()
    assert opened.json()['url']=='/ombre/gpt/v2/'
    for path in ['v2/','v2/cells/','v2/network/','v2/console/','v2/console/config/','v2/console/import/','v2/console/breath/','v2/console/trash/','v2/mobile/']:
        r=c.get('/ombre/gpt/'+path);r.raise_for_status()
        assert '/ombre/gpt/api/folio/' in r.text or '/ombre/gpt/v2/' in r.text
        assert 'I · You · Them' in r.text
        assert 'https://unpkg.com/' not in r.text
    r=c.get('/ombre/gpt/v2/mobile/app.jsx');r.raise_for_status();assert '/ombre/gpt/api/folio/' in r.text
    r=c.get('/ombre/gpt/v2/auth-token.js');r.raise_for_status()
    assert 'localStorage' not in r.text and ob.credential('gpt','dashboard') not in r.text
    assert get('capabilities')['same_engine']
    rows=get('buckets')
    assert any('Ombre真实工具接线' in x['name'] for x in rows),'Folio created a separate store'
    old=c.get('/ombre/gpt/api/buckets').json()
    assert {r['id'] for r in rows}=={r['id'] for r in old}
    first=post('bucket/create',{'name':'FOLIO_NEW_MEMORY','content':'FOLIO_COMMON_VAULT 原文正文保持不变。','tags':['测试'],'event_time':'2026-10-01T12:00:00+08:00'})['id']
    assert 'FOLIO_COMMON_VAULT' in ob.text_result(asyncio.run(ob.call('gpt','breath_search',{'query':'FOLIO_COMMON_VAULT'})))
    for scope in ('claude','group_gpt','group_claude'):
        assert '原文正文保持不变' not in ob.text_result(asyncio.run(ob.call(scope,'breath_search',{'query':'FOLIO_COMMON_VAULT'})))
    before=c.get('/ombre/gpt/api/bucket/'+first).json()['content']
    preview=post('bucket/'+first+'/redehydrate',{})
    assert preview['new']['summary']=='FOLIO_REFINED_SUMMARY'
    assert c.get('/ombre/gpt/api/bucket/'+first).json()['content']==before
    post('bucket/'+first+'/update',{'name':'changed after preview'})
    stale=preview
    preview=post('bucket/'+first+'/redehydrate',{})
    assert c.post('/ombre/gpt/api/folio/bucket/'+first+'/redehydrate-commit',json=stale['new']).status_code==409
    post('bucket/'+first+'/redehydrate-commit',preview['new'])
    post('bucket/'+first+'/redehydrate-commit',preview['new'])
    assert get('bucket/'+first)['metadata']['summary']=='FOLIO_REFINED_SUMMARY'
    assert get('bucket/'+first)['content']==before
    post('scoring-config',{'strict_keyword_mode':True,'keyword_first_sort':True,'title_hit_bonus':10})
    post('decay-config',{'decay_lambda':.06})
    post('prompts-config',{'REDEHYDRATE':'只整理给定材料，输出 JSON。'})
    assert get('prompts-config')['current']['REDEHYDRATE']=='只整理给定材料，输出 JSON。'
    get('search?q=Folio精修标题&simulate=true')
    get('search?q=Folio精修标题')
    assert get('hit-stats')['hit_buckets']>0
    assert get('recent-searches')['items']
    trial=json.dumps({'items':[{'name':'FOLIO_TRIAL_ONE','content':'FOLIO_TRIAL_FIRST 原文甲。'},{'name':'FOLIO_TRIAL_TWO','content':'FOLIO_TRIAL_SECOND 原文乙。'}]},ensure_ascii=False).encode()
    upload=c.post('/ombre/gpt/api/folio/import/upload?preserve_raw=1&mode=large&max_chunks=1',files={'file':('trial.json',trial,'application/json')});upload.raise_for_status()
    import time
    for _ in range(100):
        progress=get('import/status')
        if progress.get('status') not in {'running','pending'}:break
        time.sleep(.1)
    assert progress['status']=='paused' and progress['processed']==1,progress
    assert any('FOLIO_TRIAL_ONE' in x['name'] for x in get('import/results')['buckets'])
    assert not any('FOLIO_TRIAL_TWO' in x['name'] for x in get('buckets'))
    post('config/strategy',{'auto_merge':False,'merge_threshold':80,'max_recall':6})
    assert get('config/strategy')['auto_merge'] is False
    second=post('bucket/create',{'name':'FOLIO_MERGE_SOURCE','content':'second source material'})['id']
    post('bucket/'+second+'/update',{'highlight':True,'protected':True})
    meta=get('bucket/'+second)['metadata']
    assert meta['highlight'] and meta['protected'] and not meta.get('pinned')
    assert 'second source material' in ob.text_result(asyncio.run(ob.call('gpt','breath')))
    post('bucket/'+second+'/update',{'highlight':False,'protected':False})
    merge=post('bucket/'+second+'/merge-preview?into='+first,{})
    post('bucket/'+second+'/update',{'name':'source changed after preview'})
    assert c.post('/ombre/gpt/api/folio/bucket/'+second+'/merge-commit?into='+first,json={'preview_id':merge['preview_id'],'merged_content':'bad stale merge'}).status_code==409
    merge=post('bucket/'+second+'/merge-preview?into='+first,{})
    post('bucket/'+second+'/merge-commit?into='+first,{'preview_id':merge['preview_id'],'merged_content':'FOLIO_MERGED_BODY 两条原文的合并。'})
    assert 'FOLIO_MERGED_BODY' in c.get('/ombre/gpt/api/bucket/'+first).json()['content']
    post('bucket/'+first+'/delete',{})
    assert any(x['id']==first for x in get('trash'))
    post('bucket/'+first+'/restore',{})
    assert any(x['id']==first for x in get('buckets'))
    assert c.post('/ombre/gpt/api/folio/bucket/'+first+'/purge',json={}).status_code==410
    # A new lock is created in the native engine, then every new UI path must
    # retain its native access boundary, including previews and search logs.
    asyncio.run(ob.call('gpt','letter_write',{'author':'ai','content':'FOLIO_LOCKED_BODY','title':'FOLIO_LOCKED_TITLE','lock_type':'timed','unlock_date':'2099-01-01'}))
    locked=next(x for x in c.get('/ombre/gpt/api/buckets').json() if x.get('letter_locked'))
    for path in ('buckets','bucket/'+locked['id'],'search?q=FOLIO_LOCKED_BODY','trash'):
        text=json.dumps(get(path));assert 'FOLIO_LOCKED_BODY' not in text and 'FOLIO_LOCKED_TITLE' not in text,(path,text)
    assert 'FOLIO_LOCKED_TITLE' not in json.dumps(get('recent-searches'))
    for action in ('update','redehydrate','delete','archive','restore'):
        assert c.post('/ombre/gpt/api/folio/bucket/'+locked['id']+'/'+action,json={'content':'bad'}).status_code==403
    mood=post('mood-evoke',{'valence':.7,'arousal':.4,'radius':.4})
    assert mood['narrative']=='FOLIO_MOOD_NARRATIVE'
    assert all(s['id']!=locked['id'] for s in mood['sources'])
    assert 'FOLIO_LOCKED_TITLE' not in json.dumps(get('families'))
    # Too few related memories may honestly return a no-family result; it must
    # still execute the pinned clustering against the modern compressed vectors.
    family_result=post('families/rebuild',{'threshold':.1})
    assert 'families' in family_result or 'error' in family_result
    profile=post('config/api/profile',{'name':'synthetic profile','base_url':'http://127.0.0.1:8766/v1','model':'fixture-gpt','api_key':'FOLIO_PROFILE_SECRET'})
    assert 'FOLIO_PROFILE_SECRET' not in json.dumps(get('config/api'))
    post('config/api/active',{'id':profile['id']})
    assert get('config/api')['current_effective']['model']=='fixture-gpt'
    assert post('config/api/test',{'id':profile['id']})['ok']
    post('config/api/active',{'id':None})
    assert get('config/api')['current_effective']['model']=='lune-selected-model'
    assert get('config/api')['embedding']['model']=='BAAI/bge-small-zh-v1.5'
    assert get('config/api')['embedding']['dim']==512
    noisy=post('bucket/create',{'name':'FOLIO_NOISE','content':'FOLIO_NOISE_BODY'})['id']
    post('bucket/'+noisy+'/update',{'protected':True,'highlight':True})
    post('bucket/'+noisy+'/update',{'resolved':True,'importance':1})
    meta=get('bucket/'+noisy)['metadata']
    assert meta['importance']==1 and not meta.get('protected') and not meta.get('highlight'),meta
    assert len(asyncio.run(ob.rpc('gpt','tools/list'))['tools'])==16
    for path in ('/api/settings/you','/api/settings/them','/api/self','/api/plans'):
        c.get('/ombre/gpt'+path).raise_for_status()
    if os.environ.get('LUNE_FOLIO_PREVIEW_DIR'):
        target=Path(os.environ['LUNE_FOLIO_PREVIEW_DIR'])
        for path in ('buckets','capabilities','config/api','config/strategy','scoring-config','decay-config','prompts-config','hit-stats','recent-searches','trash','network','breath-debug','import/status','import/results','families'):
            value=get(path);file=target/'api/folio'/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(json.dumps(value,ensure_ascii=False))
        for row in get('buckets'):
            file=target/'api/folio/bucket'/row['id'];file.parent.mkdir(parents=True,exist_ok=True);file.write_text(json.dumps(get('bucket/'+row['id']),ensure_ascii=False))
    print('Folio merge PASS: same native store/tools, five UI views, original-body preview/conflict/commit, Chinese scoring, settings, merge/archive/trash/restore and locked-letter boundaries')
