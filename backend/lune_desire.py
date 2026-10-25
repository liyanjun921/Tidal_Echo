"""Persistence/evidence adapter for the pure desire kernel; one Room drive store."""
import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
try:
    from . import desire_kernel as k
    from .lune_continuity import connection
except ImportError:
    import desire_kernel as k
    from lune_continuity import connection

ENV_FLAGS={'DESIRE_DRIVEN':'enabled','DESIRE_COUPLING':'coupling',
           'DESIRE_BASELINE_DRIFT':'baseline_drift','HEARTBEAT_AUTONOMY':'autonomy',
           'DESIRE_SELF_DRIVE':'self_drive','DESIRE_HABITS':'habits',
           'DESIRE_EXPERIENCES':'experiences','DESIRE_NOISE':'noise',
           'DESIRE_MESSAGE_PULSES':'message_pulses','DESIRE_INTIMACY_PULSES':'intimacy_pulses',
           'DESIRE_SEMANTIC_PULSES':'semantic_pulses'}


def boot_defaults():
    cfg=k.config()
    for env,field in {**ENV_FLAGS,'DESIRE_CIRCADIAN':'circadian','DESIRE_MORNING':'morning'}.items():
        value=os.environ.get(env,'0')
        if value not in {'0','1'}:raise ValueError(env+' must be 0 or 1')
        if field in {'circadian','morning'}:cfg[field]['enabled']=value=='1'
        else:cfg[field]=value=='1'
    return cfg


def init(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS lune_desire_changes(id INTEGER PRIMARY KEY,scope TEXT,ts REAL,drive TEXT,delta REAL,reason TEXT,source_ref TEXT);
    CREATE TABLE IF NOT EXISTS lune_desire_actions(id TEXT PRIMARY KEY,scope TEXT,run_id TEXT,tool TEXT,intent TEXT,ts REAL,material INTEGER,changes TEXT);
    CREATE TABLE IF NOT EXISTS lune_desire_experiences(id TEXT PRIMARY KEY,scope TEXT,source_id INTEGER,source_memory_id TEXT,body TEXT,visibility TEXT,created REAL,consumed INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS lune_wren_thought_sources(thought_id TEXT,source_id INTEGER,quote TEXT,created REAL,PRIMARY KEY(thought_id,source_id,quote));
    CREATE TABLE IF NOT EXISTS lune_desire_classifier(scope TEXT,message_id INTEGER,status TEXT,drive TEXT,score REAL,created REAL,PRIMARY KEY(scope,message_id));
    ''')
    columns = {r[1] for r in db.execute('PRAGMA table_info(lune_wren_thoughts)')}
    for name, definition in [('topic_keys', "TEXT DEFAULT '[]'"), ('feedback_count', 'INTEGER DEFAULT 0'), ('advanced_at', 'REAL DEFAULT 0')]:
        if name not in columns:
            db.execute('ALTER TABLE lune_wren_thoughts ADD COLUMN ' + name + ' ' + definition)
    for row in db.execute("SELECT * FROM lune_wren_thoughts WHERE topic_keys='[]'").fetchall():
        db.execute('UPDATE lune_wren_thoughts SET topic_keys=? WHERE id=?',(json.dumps(k.topic_keys(row['quote'])),row['id']))
        db.execute('INSERT OR IGNORE INTO lune_wren_thought_sources VALUES(?,?,?,?)',(row['id'],row['source_id'],row['quote'],row['updated']))
    db.execute("UPDATE lune_desire_classifier SET status='interrupted' WHERE status='running'")


def validate(raw, old=None):
    if not isinstance(raw, dict):
        raise HTTPException(422, '欲望设置应为对象')
    if set(raw) - set(k.DEFAULTS):
        raise HTTPException(422, '存在未知的欲望设置')
    for name in ('circadian','morning'):
        if name in raw and not isinstance(raw[name],dict):
            raise HTTPException(422,'节律设置应为对象')
    if 'phases' in raw.get('circadian',{}) and not isinstance(raw['circadian']['phases'],dict):
        raise HTTPException(422,'相位表应为对象')
    cfg = k.config({**(old or {}), **raw})
    for name in k.FLAGS:
        if type(cfg[name]) is not bool:
            raise HTTPException(422, '欲望开关应为布尔值')
    def number(value, low, high):
        return type(value) in (int,float) and math.isfinite(value) and low <= value <= high
    c = cfg['circadian']
    if type(c['enabled']) is not bool or not number(c['cap'], 0, .2) or set(c['phases']) != set(k.REGISTRY):
        raise HTTPException(422, '生物钟幅度应在 0–0.2 之间，相位表须完整')
    for value in c['phases'].values():
        if not isinstance(value, dict) or set(value) != {'peak','amp'} or not number(value['peak'],0,24) or not number(value['amp'],0,1):
            raise HTTPException(422, '峰时应在 0–24 之间，振幅在 0–1 之间')
    m = cfg['morning']
    if type(m['enabled']) is not bool or not number(m['hour'],0,23.99) or not number(m['width'],.1,6) or not number(m['pulse'],0,.2) or not number(m['gain'],0,1) or not number(m['min_hours'],1,12) or not number(m['max_hours'],2,48) or m['max_hours'] <= m['min_hours']:
        raise HTTPException(422, '清晨脉冲的时间、幅度或过夜窗口不正确')
    return cfg


def load(db, scope, cfg):
    row = db.execute('SELECT * FROM lune_wren_drives WHERE scope=?', (scope,)).fetchone()
    state = json.loads(row['value'])
    if state.get('schema') != 2:
        state = k.new_state(row['updated'], {key: k.clamp(cfg['baseline'].get(key,0)+state.get(key,0)) for key in k.REGISTRY})
    # Add future dimensions without destroying existing state.
    for key in k.REGISTRY:
        state['drive'].setdefault(key,0)
        state['habit'].setdefault(key,0)
    return state


def save(db, scope, state, changes, ref, now):
    db.execute('UPDATE lune_wren_drives SET value=?,updated=? WHERE scope=?', (json.dumps(state,ensure_ascii=False),now,scope))
    db.executemany('INSERT INTO lune_desire_changes(scope,ts,drive,delta,reason,source_ref) VALUES(?,?,?,?,?,?)',
                   [(scope,now,c['drive'],c['delta'],c['reason'],ref) for c in changes])
    db.execute('DELETE FROM lune_desire_changes WHERE scope=? AND id NOT IN (SELECT id FROM lune_desire_changes WHERE scope=? ORDER BY id DESC LIMIT 10000)',(scope,scope))


def hour(cfg, now):
    stamp = datetime.fromtimestamp(now,ZoneInfo(cfg['timezone']))
    return stamp.hour + stamp.minute/60 + stamp.second/3600, stamp.date().isoformat()


def snapshot(db, scope, cfg, now):
    state = load(db,scope,cfg)
    h,day = hour(cfg,now)
    # Reading never delivers a morning pulse or mutates canonical base.
    raw = k.config(cfg.get('desire'))
    readonly = {**raw,'morning':{**raw['morning'],'enabled':False}}
    projected,_ = k.advance(state,now,cfg['baseline'],readonly,hour=h,day=day,seed=scope)
    display,circ = k.circadian(projected['drive'],h,raw)
    return projected,display,circ


def step(db, scope, cfg, now, user=None, *, force=False):
    state = load(db,scope,cfg)
    fresh = user is not None and user['id'] > state['last_user_id']
    if not force and not fresh and now-state['at'] < 300:
        return
    h,day = hour(cfg,now)
    idle = now-user['at'] if user else 0
    state,changes = k.advance(state,now,cfg['baseline'],cfg.get('desire'),hour=h,day=day,idle_seconds=idle,seed=scope)
    if fresh:
        state,delta = k.message(state,user['text'],user['id'],now,cfg.get('desire'))
        changes.extend(delta)
    if cfg['desire']['experiences']:
        for row in db.execute("SELECT * FROM lune_desire_experiences WHERE scope=? AND visibility='shared' AND consumed=0 ORDER BY created LIMIT 5",(scope,)).fetchall():
            item = json.loads(row['body'])
            state,delta = k.experience(state,item,now,cfg['desire'])
            changes.extend(delta)
            db.execute('UPDATE lune_desire_experiences SET consumed=1 WHERE id=?',(row['id'],))
            if item['priority'] >= 80:
                db.execute("UPDATE lune_wren_thoughts SET state='fixation',strength=max(strength,.8) WHERE id=? AND scope=? AND visibility='shared'",(row['source_memory_id'],scope))
    # September revision: time-based flits and topic merging; fixation feedback.
    for row in db.execute('SELECT * FROM lune_wren_thoughts WHERE scope=? AND state!=\'retired\'',(scope,)).fetchall():
        elapsed = max(0,now-(row['advanced_at'] or row['updated']))
        strength,feedback,status = row['strength'],row['feedback_count'],row['state']
        if status=='flit':
            strength *= 2 ** (-elapsed/86400)
            if strength<.02: status='retired'
        elif cfg['desire']['enabled']:
            strength = min(1,strength * 1.1 ** min(48,elapsed/300))
            if strength>=.85:
                if row['visibility']=='shared':
                    state,delta = k.pulse(state,{row['drive']:.18},now,'我反复惦记的一件真实小事，又推了我一下。',category='fixation:'+row['id'])
                    changes.extend(delta)
                strength *= .7
                feedback += 1
                if feedback>=3: status='retired'
        db.execute('UPDATE lune_wren_thoughts SET strength=?,feedback_count=?,state=?,advanced_at=? WHERE id=?',(strength,feedback,status,now,row['id']))
    save(db,scope,state,changes,'message:'+str(user['id']) if fresh else 'heartbeat',now)


def experience(db, scope, body, cfg, now):
    content = body.get('content')
    if not isinstance(content,str) or not 1<=len(content.strip())<=3000:
        raise HTTPException(422,'体验需要 3000 字以内的第一人称正文')
    item = {name:body.get(name) for name in ['valence','arousal','tension','response_tendency','growth_delta','priority']}
    for key,low,high in [('valence',-1,1),('arousal',0,1),('tension',0,1),('priority',1,100)]:
        value=item[key]
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
            raise HTTPException(422,'体验标量超出范围')
    if item['response_tendency'] not in {'comfort','engage','withdraw','alert'} or item['growth_delta'] not in {'growth','stable','setback'}:
        raise HTTPException(422,'体验姿态或成长方向不正确')
    anchor = db.execute('SELECT * FROM lune_wren_thoughts WHERE id=? AND scope=?',(body.get('source_memory_id'),scope)).fetchone()
    if not anchor:
        raise HTTPException(422,'体验须锚定本房间一条已有原话念头；先 read 取得编号')
    visibility=body.get('visibility') if body.get('visibility') in {'shared','private','surprise'} else 'private'
    if anchor['visibility']!='shared': visibility=anchor['visibility']
    item.update(content=content.strip(),drive_snapshot=load(db,scope,cfg)['drive'])
    eid=hashlib.sha256((scope+str(body.get('run_id'))+anchor['id']+content).encode()).hexdigest()
    db.execute('INSERT OR IGNORE INTO lune_desire_experiences(id,scope,source_id,source_memory_id,body,visibility,created) VALUES(?,?,?,?,?,?,?)',
               (eid,scope,anchor['source_id'],anchor['id'],json.dumps(item,ensure_ascii=False),visibility,now))
    return {'id':eid,'visibility':visibility,'source_memory_id':anchor['id']}


def action(db,scope,cfg,run_id,tool,intent,result,now):
    """Called only after the host saw a successful operation, never model self-report."""
    rid=hashlib.sha256((scope+run_id+intent).encode()).hexdigest()
    if db.execute('SELECT 1 FROM lune_desire_actions WHERE id=?',(rid,)).fetchone(): return
    state=load(db,scope,cfg)
    material=len(str(result))>100 and not any(token in str(result) for token in ['"matches": []','"items": []','"results": []','没有找到','未找到','无匹配','0 条'])
    state,changes=k.satisfy(state,intent,now,cfg['desire'],verified=True,material=material)
    save(db,scope,state,changes,'action:'+rid,now)
    db.execute('INSERT INTO lune_desire_actions VALUES(?,?,?,?,?,?,?,?)',(rid,scope,run_id,tool,intent,now,int(material),json.dumps(changes,ensure_ascii=False)))


def record_tool(path,room,agent,run_id,name,args,result):
    if not run_id or str(result).startswith('ERROR'): return
    try:
        parsed=json.loads(result)
    except (ValueError,TypeError):
        parsed=None
    if isinstance(parsed,dict):
        nested=parsed.get('result')
        if parsed.get('isError') or parsed.get('error') or isinstance(nested,dict) and nested.get('isError'): return
    intent=None
    if name in {'latent_search','ombre_breath_search','lune_memory'} and (name!='lune_memory' or args.get('action')=='search'):
        intent='reflect'
    if name=='lune_workspace':
        if args.get('action')=='list' and args.get('kind') in {'book','annotation'}: intent='reflect'
        if args.get('action') in {'create','update'}:
            if args.get('kind')!='todo':intent='make'
            elif args.get('action')=='update' and args.get('data',{}).get('done') is True:intent='follow_through'
    if not intent: return
    try:
        from .lune_wren import config,scope_for
    except ImportError:
        from lune_wren import config,scope_for
    scope=scope_for(room,agent)
    if not scope:return
    with connection(path) as db:
        db.execute('BEGIN IMMEDIATE')
        run=db.execute('SELECT * FROM lune_runs WHERE id=?',(run_id,)).fetchone()
        if not run or run['state']!='running' or 'lune-'+run['room']!=room or agent not in json.loads(run['targets']):return
        cfg=config(db,scope)
        if not cfg['desire']['enabled']:return
        action(db,scope,cfg,run_id,name,intent,result,time.time())


def view(db,scope,cfg,now,private=False):
    state,display,circ=snapshot(db,scope,cfg,now)
    experiences=[{**dict(row),'body':json.loads(row['body'])} for row in db.execute('SELECT * FROM lune_desire_experiences WHERE scope=? ORDER BY created DESC LIMIT 100',(scope,)) if private or row['visibility']=='shared']
    return {'flags':cfg['desire'],'drive':state['drive'],'drive_display':display,'circadian':circ,
            'habit':state['habit'],'cooldown':state['cooldown'],'self_drive':{
                'enabled':cfg['desire']['self_drive'],'curiosity_floor':state['curiosity_floor'],
                'actions':state['self_actions'],'last_pulse':state['last_self_pulse']},
            'experiences':experiences,
            'changes':[dict(r) for r in db.execute('SELECT * FROM lune_desire_changes WHERE scope=? ORDER BY id DESC LIMIT 80',(scope,))],
            'actions':[dict(r) for r in db.execute('SELECT * FROM lune_desire_actions WHERE scope=? ORDER BY ts DESC LIMIT 30',(scope,))],
            'local_classifier':[dict(r) for r in db.execute('SELECT * FROM lune_desire_classifier WHERE scope=? ORDER BY created DESC LIMIT 10',(scope,))]}


def positive_class(vectors):
    if not isinstance(vectors,list) or len(vectors)!=5 or not vectors[0] or any(not isinstance(v,list) or len(v)!=len(vectors[0]) or any(type(x) not in (int,float) or not math.isfinite(x) for x in v) for v in vectors):
        raise ValueError('local classifier vectors unavailable')
    def cosine(a,b):
        divisor=math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))
        return sum(x*y for x,y in zip(a,b))/divisor if divisor else 0
    scores=sorted([(key,cosine(vectors[0],vector)) for key,vector in zip(['curiosity','reflection','duty','social'],vectors[1:])],key=lambda pair:-pair[1])
    key,score=scores[0]
    return (key if score>=.62 and score-scores[1][1]>=.04 else None),score


async def classify_message(path,room,agent,text,message_id):
    """Optional existing local BGE, positive-only and one attempt per real message."""
    if type(message_id) is not int:return
    try:
        from .lune_wren import scope_for,config
        from .lune_memory import LatentEngine
    except ImportError:
        from lune_wren import scope_for,config
        from lune_memory import LatentEngine
    scope=scope_for(room,agent)
    if not scope:return
    with connection(path) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='lune_desire_classifier'").fetchone():return
        cfg=config(db,scope)
        if not cfg['desire']['semantic_pulses'] or not cfg['desire']['message_pulses']:return
        row=db.execute("SELECT text FROM messages WHERE id=? AND direction='in' AND json_extract(meta,'$.api_session')=?",(message_id,room)).fetchone()
        if not row or row['text']!=text:return
        if db.execute('SELECT 1 FROM lune_desire_classifier WHERE scope=? AND message_id=?',(scope,message_id)).fetchone():return
        known=any(word in text for word in ['代码','报错','http://','https://','帮我','去做','先开始','大家','群里','朋友','怎么还没','你不是说','赶紧','抱抱','亲亲','想贴着你','分手','隐私','泄露','嫉妒','压力','难过'])
        db.execute('INSERT INTO lune_desire_classifier VALUES(?,?,?,?,?,?)',(scope,message_id,'keyword' if known else 'running',None,None,time.time()))
    if known:return
    key,score,status=None,None,'unavailable'
    try:
        result=await LatentEngine(path).worker({'operation':'embed','input':[text[:500],
            '我想弄明白一个新知识或问题','我想回顾读过的书与共同经历','我有一项明确需要完成的任务','我想了解朋友与群体的讨论']})
        key,score=positive_class(result['vectors'])
        status='matched' if key else 'below-threshold'
    except (RuntimeError,ValueError,KeyError,OSError,TimeoutError):
        pass
    with connection(path) as db:
        db.execute('BEGIN IMMEDIATE')
        latest=config(db,scope)
        db.execute('UPDATE lune_desire_classifier SET status=?,drive=?,score=? WHERE scope=? AND message_id=?',(status,key,score,scope,message_id))
        if key and latest['version']==cfg['version']:
            state=load(db,scope,cfg)
            # A later human message supersedes this optional signal.
            if state['last_user_id']==message_id:
                state,changes=k.pulse(state,{key:.03},time.time(),'我从这段新材料里接到一点正向兴趣；没有判断你的情绪。',category='semantic:'+key)
                save(db,scope,state,changes,'semantic:'+str(message_id),time.time())


async def read_for_intent(path,scope,intent):
    """One bounded, actual read. Never pretend unavailable outside services ran."""
    if intent!='reflect':return None
    try:
        from .lune_wren import SCOPES
        from . import ombre_runtime as ob
    except ImportError:
        from lune_wren import SCOPES
        import ombre_runtime as ob
    with connection(path) as db:
        row=db.execute("SELECT id,title,content FROM lune_workspace WHERE scope IN ('shared',?) AND kind='book' AND deleted=0 AND length(content)>0 ORDER BY updated_at DESC LIMIT 1",(SCOPES[scope][0],)).fetchone()
        if row:return {'tool':'host:read_book_excerpt','intent':'reflect','result':{'source_id':row['id'],'title':row['title'],'excerpt':row['content'][:4000],'partial':len(row['content'])>4000}}
        thought=db.execute("SELECT topic_keys FROM lune_wren_thoughts WHERE scope=? AND visibility='shared' AND state!='retired' ORDER BY updated DESC LIMIT 1",(scope,)).fetchone()
    if thought and ob.installed():
        result=await ob.call(scope,'breath_search',{'query':' '.join(json.loads(thought['topic_keys'])[:4]),'max_results':2})
        if not result.get('isError'):
            return {'tool':'ombre_breath_search','intent':'reflect','result':result}
    return None


def record_reply(path,msg):
    """A persisted ordinary chat reply is delivery evidence, not model self-report."""
    meta=msg.get('meta',{})
    if msg.get('direction')!='out' or msg.get('kind')!='reply' or meta.get('error') or meta.get('api',{}).get('error'):return
    room,agent,rid=meta.get('api_session',''),meta.get('agent_id'),meta.get('run_id')
    if not rid:return
    try:
        from .lune_wren import scope_for,config
    except ImportError:
        from lune_wren import scope_for,config
    scope=scope_for(room,agent)
    if not scope:return
    with connection(path) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='lune_desire_actions'").fetchone():return
        db.execute('BEGIN IMMEDIATE')
        run=db.execute('SELECT * FROM lune_runs WHERE id=?',(rid,)).fetchone()
        if not run or run['state'] not in {'pending','running'} or 'lune-'+run['room']!=room or agent not in json.loads(run['targets']):return
        cfg=config(db,scope)
        if cfg['desire']['enabled']:action(db,scope,cfg,rid,'host:persisted_reply','reach_out',msg['text'],time.time())
