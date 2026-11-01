"""Pinned MIT Xinchao 4.1.1 runtime, isolated per existing Luné/Ombre scope."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import subprocess
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

try:
    from . import ombre_runtime as ob
except ImportError:
    import ombre_runtime as ob

REPOSITORY='https://github.com/liyanjun921/xinchao-nian.git'
REVISION='3acbaf48e92508d678dd5d5a90e13f82d900a370'
VERSION='4.1.1'
SCOPES=ob.SCOPES
TOOLS={'xinchao_context','xinchao_event','xinchao_awareness','xinchao_handoff_note',
       'xinchao_box','xinchao_personality_reflect','xinchao_personality_stats',
       'xinchao_anchor_update','xinchao_cabin_inbox','xinchao_cabin_note'}
DEFAULTS={'enabled':True,'context':True,'memory_read':True,'memory_write':True,
          'model_enabled':False,'dreams':False,'daytime':False,'self_signals':False,
          'accept_self_signals':False,'private_dreams':False,'timezone':'Asia/Shanghai',
          'model_daily_limit':20,'settle_minutes':15,'agent_name':'','recipient':'你',
          'interaction_rules':{},'drive_prompts':{}}


def root():
    return Path(os.environ.get('LUNE_XINCHAO_DIR') or Path(os.environ.get('RELAY_DB','relay.db')).resolve().parent/'lune-private'/'xinchao')


def source():return Path(os.environ.get('LUNE_XINCHAO_SOURCE') or root()/'source')


def installed():
    try:
        marker=json.loads((source().parent/(source().name+'.lune-verified.json')).read_text())
        return marker['revision']==REVISION and 'xinchao/src/server.js' in marker['files'] and all(
            hashlib.sha256((source()/name).read_bytes()).hexdigest()==digest for name,digest in marker['files'].items())
    except (OSError,ValueError,KeyError):return False


def credential(scope,purpose):
    ob.scope_check(scope)
    secret=os.environ.get('RELAY_SECRET','')
    if not secret:raise RuntimeError('Missing host credential')
    return hmac.new(secret.encode(),('xinchao:'+scope+':'+purpose).encode(),hashlib.sha256).hexdigest()


def endpoint(scope):
    ob.scope_check(scope)
    port=int(os.environ.get('LUNE_XINCHAO_PORT_BASE','18210'))+SCOPES.index(scope)
    if not 1024<=port<=65535:raise ValueError('Xinchao port range')
    return 'http://127.0.0.1:'+str(port)


def validate(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):raise ValueError('存在未知的心潮配置')
    cfg={**DEFAULTS,**value}
    for name,default in DEFAULTS.items():
        if type(default) is bool and type(cfg[name]) is not bool:raise ValueError('心潮开关应为布尔值')
    for key,low,high in [('model_daily_limit',1,100),('settle_minutes',1,1440)]:
        if type(cfg[key]) is not int or not low<=cfg[key]<=high:raise ValueError('心潮预算或结算间隔不正确')
    for key in ('agent_name','recipient'):
        if not isinstance(cfg[key],str) or len(cfg[key])>80:raise ValueError('称呼应在 80 字以内')
    try:ZoneInfo(cfg['timezone'])
    except (ZoneInfoNotFoundError,TypeError,ValueError):raise ValueError('时区不正确') from None
    for key in ('interaction_rules','drive_prompts'):
        if not isinstance(cfg[key],dict) or len(json.dumps(cfg[key],ensure_ascii=False))>24000:raise ValueError('规则或提示词配置过长')
    rules=cfg['interaction_rules']
    lists={'heavy','shy','distress','fiction','dailyBye','longAway','harsh','accuse'}
    if set(rules)-lists-{'closeness','softAfterCloseMinutes','_说明'}:raise ValueError('互动规则含未知字段')
    for key in lists & set(rules):
        if not isinstance(rules[key],list) or len(rules[key])>100 or any(not isinstance(x,str) or len(x)>200 for x in rules[key]):raise ValueError('互动词表应为字符串数组')
    if 'softAfterCloseMinutes' in rules and (type(rules['softAfterCloseMinutes']) not in (int,float) or not 0<=rules['softAfterCloseMinutes']<=1440):raise ValueError('互动时间范围不正确')
    if 'closeness' in rules and (not isinstance(rules['closeness'],dict) or any(v not in {'her','family','known','stranger'} for v in rules['closeness'].values())):raise ValueError('远近名单不正确')
    prompts=cfg['drive_prompts']
    if set(prompts)-{'hints','held','night','footer','_说明'}:raise ValueError('驱力文案含未知字段')
    if 'hints' in prompts and (not isinstance(prompts['hints'],dict) or any(not isinstance(v,str) or len(v)>2000 for v in prompts['hints'].values())):raise ValueError('驱力提示应为文字映射')
    if 'held' in prompts and (not isinstance(prompts['held'],list) or any(not isinstance(v,str) for v in prompts['held'])):raise ValueError('驱力列表不正确')
    if any(k in prompts and not isinstance(prompts[k],str) for k in ['night','footer']):raise ValueError('驱力页脚应为文字')
    return cfg


def config(scope):
    ob.scope_check(scope)
    file=root()/scope/'lune-config.json'
    if not file.is_file():return {**DEFAULTS,'version':0}
    value=json.loads(file.read_text())
    return {**validate({k:v for k,v in value.items() if k!='version'}),'version':value['version']}


def save_config(scope,value,version):
    old=config(scope)
    if version!=old['version']:raise ValueError('设置已更新，请刷新后重试')
    cfg={**validate(value),'version':version+1}
    words=[entry for key,entries in cfg['interaction_rules'].items() if key in {'heavy','shy','distress','fiction','dailyBye','longAway','harsh','accuse'} for entry in entries]
    if words:
        try:
            subprocess.run([node(),'-e',"const fs=require('node:fs');for(const s of JSON.parse(fs.readFileSync(0,'utf8')))new RegExp(s)"],input=json.dumps(words),text=True,capture_output=True,timeout=3,check=True)
        except (OSError,subprocess.SubprocessError):raise ValueError('互动规则含无效正则，未更改设置') from None
    directory=root()/scope
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=directory/'lune-config.json'
    temporary=target.with_suffix('.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as file:json.dump(cfg,file,ensure_ascii=False)
    temporary.replace(target)
    return cfg


def node():
    return os.environ.get('LUNE_XINCHAO_NODE') or shutil.which('node') or ''


def prepare(scope):
    cfg=config(scope)
    directory=root()/scope
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    env={k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','WINDIR','LANG','LC_ALL','TMPDIR'}}
    for name,payload in [('interaction-rules.json',cfg['interaction_rules']),('drive-prompts.json',cfg['drive_prompts'])]:
        file=directory/name
        fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as handle:json.dump(payload,handle,ensure_ascii=False)
    base='http://127.0.0.1:3020/xinchao-provider/'+scope
    values={'PORT':endpoint(scope).rsplit(':',1)[1],'SERVICE_TOKEN':credential(scope,'service'),
        'AGENT_NAME':cfg['agent_name'] or ('GPT' if scope.endswith('gpt') else 'Claude'),
        'NOTIFICATION_RECIPIENT':cfg['recipient'],'STATE_PATH':directory/'state.json',
        'PERSONALITY_PATH':directory/'personality.json','BOX_STATE_PATH':directory/'black-box.json',
        'CABIN_STATE_PATH':directory/'cabin.json','BRIDGE_STATE_PATH':directory/'bridge.json',
        'OAUTH_STATE_PATH':directory/'oauth.json','TRANSITION_JOURNAL_PATH':directory/'transitions.jsonl',
        'DRIVE_PROMPTS_FILE':directory/'drive-prompts.json','DRIVE_PROMPTS_STATE_PATH':directory/'drive-prompts-state.json',
        'INTERACTION_RULES_PATH':directory/'interaction-rules.json','SETTLE_INTERVAL_MINUTES':cfg['settle_minutes'],
        'SETTLE_TIME_ZONE':cfg['timezone'],'INTERACTION_TIME_ZONE':cfg['timezone'],
        'MCP_ENABLED':'true','XINCHAO_TOOLS_HIDE':'','OAUTH_ENABLED':'false','SHADOW_MODE':'false',
        'DASHBOARD_ENABLED':'true','DASHBOARD_PUBLIC_BASE_URL':endpoint(scope),
        'DASHBOARD_ACCESS_TOKEN':credential(scope,'dashboard'),'DASHBOARD_INCLUDE_PRIVATE_TEXT':str(cfg['private_dreams']).lower(),
        'BRIDGE_ENABLED':str(cfg['enabled']).lower(),'BRIDGE_MACHINE_TOKEN':credential(scope,'bridge'),
        'BRIDGE_SELF_SIGNALS':str(cfg['enabled'] and cfg['self_signals']).lower(),
        'MODEL_ENABLED':str(cfg['enabled'] and cfg['model_enabled']).lower(),
        'MODEL_BASE_URL':base+'/v1','MODEL_API_KEY':credential(scope,'provider'),'MODEL_NAME':'lune-selected-model',
        'MODEL_TIMEOUT_MS':120000,'DREAM_ENABLED':str(cfg['enabled'] and cfg['dreams']).lower(),
        'DAYTIME_EMERGENCE_ENABLED':str(cfg['enabled'] and cfg['daytime']).lower(),
        'DAYTIME_BARK_ENABLED':'false','BARK_ENABLED':'false','ATTENTION_ENABLED':'false','JEV_SHADOW_ENABLED':'false',
        'OMBRE_MCP_URL':ob.endpoint(scope)+'/mcp','OMBRE_MCP_TOKEN':ob.credential(scope,'mcp'),
        'OMBRE_READ_ENABLED':str(cfg['enabled'] and cfg['memory_read']).lower(),'OMBRE_WRITE_ENABLED':str(cfg['enabled'] and cfg['memory_write']).lower(),
        'CONTEXT_OMBRE_ENABLED':str(cfg['enabled'] and cfg['memory_read']).lower(),'OMBRE_HEARTBEAT_FILE':directory/'heartbeat.json',
        'LUNE_XINCHAO_SOURCE':source(),'LUNE_XINCHAO_SCOPE':scope,'LUNE_XINCHAO_PROVIDER':base}
    env.update({key:str(value) for key,value in values.items()})
    return env


async def request(scope,path,method='GET',body=None,*,kind='service',timeout=120):
    async with httpx.AsyncClient(timeout=timeout,trust_env=False) as client:
        response=await client.request(method,endpoint(scope)+path,headers={
            'Authorization':'Bearer '+credential(scope,kind),'Mcp-Session-Id':'lune-xinchao-'+scope},json=body)
        response.raise_for_status()
        return response.json() if response.content else {}


async def rpc(scope,method,params=None):
    value=await request(scope,'/mcp','POST',{'jsonrpc':'2.0','id':'lune','method':method,'params':params or {}})
    if value.get('error'):raise RuntimeError('心潮原版协议未完成')
    return value.get('result',{})


async def call(scope,name,args=None):return await rpc(scope,'tools/call',{'name':name,'arguments':args or {}})
