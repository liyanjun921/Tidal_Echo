"""Luné owner controls and model routing into unmodified, isolated Ombre apps."""
import asyncio
import hmac
import json
import re
import sqlite3
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
import httpx

try:
    from . import ombre_runtime as ob
    from .lune_memory import MemoryStore
except ImportError:
    import ombre_runtime as ob
    from lune_memory import MemoryStore

FEATURES = [
    ('Folio 合并增强', '同一引擎与档案：新版时间线/记忆格/手机页、中文检索、精修预览与回收恢复'),
    ('情感坐标与混合检索', 'Russell 效价/唤醒度，关键词、BM25 与本地语义融合'),
    ('遗忘与浮现', '原版衰减、归档、恢复、digested/dont_surface 和开场 breath'),
    ('记忆、感受与做梦', 'hold/grow/trace/feel/dream 原版处理器、耐久向量队列'),
    ('承诺与坐标系', 'plan、anchor/release、核心准则与硬配额'),
    ('信件', '写信、读信、时间锁、永久锁与锁拥有者边界'),
    ('I / You / Them', '自我认知见证与替代；You/Them 保持原版独立开关和人类可见性'),
    ('完整管理面板', '桶编辑、检索调试、网络、配置、诊断、媒体和全部管理入口'),
    ('导入与备份', '原版历史导入、断点、冲突选择、ZIP 清单校验与一致性快照'),
    ('模型与连接', '本地向量、当前模型整理、可选供应商、Ollama、OAuth 和 Tunnel'),
    ('同步与维护', '原版 GitHub 同步、更新和恢复；需所有者配置后才运行'),
]


def init(path):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS lune_ombre_settings (scope TEXT PRIMARY KEY, enabled INTEGER NOT NULL, automatic INTEGER NOT NULL)')
        db.executemany('INSERT OR IGNORE INTO lune_ombre_settings VALUES(?,1,1)', [(s,) for s in ob.SCOPES])


def settings(path, scope):
    ob.scope_check(scope)
    with sqlite3.connect(path) as db:
        row = db.execute('SELECT enabled,automatic FROM lune_ombre_settings WHERE scope=?', (scope,)).fetchone()
    return {'enabled': bool(row[0]), 'automatic': bool(row[1])}


async def context(path, room, agent, query, opening=None,event_id=''):
    scope = ob.scope_for(room, agent)
    value = {'scope': scope, 'status': 'not_installed', 'tools': [], 'text': ''}
    if not ob.installed():
        return value
    cfg = settings(path, scope)
    if not cfg['enabled']:
        return {**value, 'status': 'disabled'}
    tools = (await ob.rpc(scope, 'tools/list')).get('tools', [])
    value.update(status='ready', tools=[{'type': 'function', 'function': {
        'name': 'ombre_' + t['name'], 'description': t.get('description', ''),
        'parameters': t['inputSchema']}} for t in tools])
    if cfg['automatic']:
        # Ombre must still open a session when Latent is disabled/unavailable.
        # The host records completed turns independently of either engine.
        if opening is None:
            with sqlite3.connect(path) as db:
                row = db.execute('SELECT last_at FROM lune_memory_sessions WHERE room=? AND agent=?',
                                 (room, agent)).fetchone()
            opening = row is None or time.time() - row[0] > 1800
        parts = []
        if opening:
            parts.append(ob.text_result(await ob.call(scope, 'breath')))
        coordinates={}
        try:
            try:from . import xinchao_runtime as xc
            except ImportError:import xinchao_runtime as xc
            if xc.installed() and xc.config(scope)['enabled'] and xc.config(scope)['memory_read']:
                state=await xc.request(scope,'/v1/dashboard/snapshot')
                emotion=state.get('emotion',{})
                coordinates={key:emotion[key] for key in ('valence','arousal') if type(emotion.get(key)) in (int,float)}
        except (httpx.HTTPError,ValueError,RuntimeError):pass
        parts.append(ob.text_result(await ob.call(scope, 'breath_advanced' if coordinates else 'breath_search',
            {'query': query, 'max_results': 2, 'mode': 'automatic',**coordinates})))
        # Never cut a memory body into an invented fragment: omit an oversized
        # projection entirely and leave all native tools available for retrieval.
        text = '\n\n'.join(p for p in parts if p)
        value['text'] = text if len(text) <= 24000 else ''
        value['projection_omitted'] = len(text) > 24000
        if coordinates and event_id:
            try:await xc.request(scope,'/lune-host/resonance','POST',{'id':'recall:'+event_id,'text':text[:24000]})
            except (httpx.HTTPError,ValueError,RuntimeError):pass
    return value


def register(app, relay):
    path = relay['DB_PATH']
    init(path)

    @app.get('/lune/ombre/status')
    async def status(request: Request):
        relay['check_auth'](request)
        rows = []
        for scope in ob.SCOPES:
            row = {'scope': scope, **settings(path, scope), 'running': False, 'tools': []}
            if ob.installed():
                try:
                    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                        row['running'] = (await client.get(ob.endpoint(scope) + '/health')).status_code == 200
                    if row['running']:
                        row['tools'] = [t['name'] for t in (await ob.rpc(scope, 'tools/list')).get('tools', [])]
                except (httpx.HTTPError, RuntimeError):
                    pass
            rows.append(row)
        try:
            from . import ombre_folio_runtime as folio
        except ImportError:
            import ombre_folio_runtime as folio
        return {'installed': ob.installed(), 'version': ob.VERSION, 'revision': ob.REVISION,
                'folio_installed': folio.installed(), 'folio_revision': folio.REVISION,
                'scopes': rows, 'features': [{'name': n, 'detail': d} for n, d in FEATURES]}

    @app.patch('/lune/ombre/{scope}/settings')
    async def configure(scope: str, request: Request):
        relay['check_auth'](request)
        try:
            current = settings(path, scope)
        except ValueError:
            raise HTTPException(422, '记忆空间不正确') from None
        data = await request.json()
        for key in ('enabled', 'automatic'):
            if key in data:
                if not isinstance(data[key], bool):
                    raise HTTPException(422, '开关需要布尔值')
                current[key] = data[key]
        with sqlite3.connect(path) as db:
            db.execute('UPDATE lune_ombre_settings SET enabled=?,automatic=? WHERE scope=?',
                       (int(current['enabled']), int(current['automatic']), scope))
        return current

    @app.post('/lune/ombre/{scope}/open')
    async def open_dashboard(scope: str, request: Request):
        relay['check_auth'](request)
        try:
            ob.scope_check(scope)
        except ValueError:
            raise HTTPException(422, '记忆空间不正确') from None
        if not ob.installed():
            raise HTTPException(503, '尚未安装或校验通过原版 Ombre-Brain')
        view = request.query_params.get('view', '')
        response = JSONResponse({'url': '/ombre/' + scope + ('/v2/' if view == 'folio' else '/')})
        response.set_cookie('lune_ombre_' + scope, ob.owner_ticket(scope), httponly=True,
                            secure=request.url.scheme == 'https', samesite='strict',
                            path='/ombre/' + scope + '/', max_age=3600)
        return response

    @app.post('/lune/assistant/ombre')
    async def model_tool(request: Request):
        relay['check_auth'](request)
        data = await request.json()
        try:
            scope = ob.scope_for(data.get('room'), data.get('agent_id'))
        except ValueError:
            raise HTTPException(403, '房间与模型不匹配') from None
        if not settings(path, scope)['enabled']:
            raise HTTPException(409, '该空间的 Ombre 已关闭')
        store = MemoryStore(path)
        with store.db() as db:
            store.gate(db, data)
        name = data.get('name', '')
        available = {t['name'] for t in (await ob.rpc(scope, 'tools/list')).get('tools', [])}
        if not isinstance(name, str) or not name.startswith('ombre_') or name[6:] not in available:
            raise HTTPException(422, '工具不可用或已关闭')
        native = name[6:]
        if native not in ob.READ_TOOLS and not store.config()['model_writes']:
            raise HTTPException(403, '模型写入已关闭')
        args = data.get('arguments', {})
        if not isinstance(args, dict):
            raise HTTPException(422, '工具参数格式不正确')
        # Current run was checked immediately before entering the native engine;
        # once a native write commits, cancellation cannot pretend to undo it.
        result=await ob.call(scope,native,args)
        if native in {'breath','breath_advanced'} and not result.get('isError'):
            try:
                try:from .lune_living_context import projection
                except ImportError:from lune_living_context import projection
                current=projection(path,data['room'],data['agent_id'])
                if current['text']:result={**result,'content':[*result.get('content',[]),{'type':'text','text':current['text']}]}
            except (RuntimeError,ValueError,OSError):pass
        return result


def themed_html(html, scope):
    prefix = '/ombre/' + ob.scope_check(scope)
    # The original UI has root-absolute navigation/assets. Keep its actual
    # controls and requests, rebasing only in the served projection.
    html = re.sub(r'([\"\x27`])/(api|v2|auth|static|onboarding|dashboard|favicon\.ico)(?=[/\"\x27`?#])',
                  lambda m: m[1] + prefix + '/' + m[2], html)
    html = html.replace("location.href='/'", "location.href='" + prefix + "/'")
    bootstrap = '''<script>(()=>{const prefix=PREFIX;
const rebase=x=>{const u=new URL(x,location.href);if(u.origin===location.origin&&!u.pathname.startsWith(prefix+'/'))u.pathname=prefix+u.pathname;return u.href};
const nativeFetch=window.fetch.bind(window);window.fetch=(x,o)=>nativeFetch(x instanceof Request?new Request(rebase(x.url),x):rebase(x),o);
const open=window.open.bind(window);window.open=(u,...a)=>open(u?rebase(u):u,...a);
const X=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u,...a){return X.call(this,m,rebase(u),...a)};
document.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(a&&a.getAttribute('href').startsWith('/'))a.href=rebase(a.href)},true);
})();</script>'''.replace('PREFIX', json.dumps(prefix))
    theme = '''<style>:root{--bg:#edf3f6!important;--accent:#628ba5!important;--text:#304652!important;--border:rgba(114,146,165,.2)!important;--text-light:#728b9a!important}body{background:linear-gradient(145deg,#edf4f8,#f5f8fa)!important}header,.card,.panel,.modal-content,.sidebar{background:rgba(255,255,255,.7)!important;backdrop-filter:blur(22px);border-radius:20px}button,input,select,textarea{border-radius:12px!important}</style>'''
    return html.replace('<head>', '<head>' + bootstrap + theme, 1)


def register_proxy(app):
    sessions = {}
    locks = {s: asyncio.Lock() for s in ob.SCOPES}

    @app.api_route('/ombre/{scope}/{tail:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'])
    async def proxy(scope: str, tail: str, request: Request):
        try:
            ob.scope_check(scope)
        except ValueError:
            raise HTTPException(404) from None
        if not ob.owner_valid(scope, request.cookies.get('lune_ombre_' + scope, '')):
            raise HTTPException(401, '请从 Luné 的 Ombre 面板重新打开管理页')
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, '拒绝跨站请求')
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            raise HTTPException(403, '来源不匹配')
        if len(await request.body()) > 32 * 1024 * 1024:
            raise HTTPException(413, '管理请求过大')
        base = ob.endpoint(scope)
        client = httpx.AsyncClient(timeout=300, trust_env=False, follow_redirects=False)
        try:
            async with locks[scope]:
                if scope not in sessions:
                    login = await client.post(base + '/auth/login', json={'password': ob.credential(scope, 'dashboard')})
                    login.raise_for_status()
                    sessions[scope] = login.cookies.get('ombre_session', '')
            headers = {'Cookie': 'ombre_session=' + sessions[scope]}
            for key in ('content-type', 'accept', 'range'):
                if key in request.headers:
                    headers[key] = request.headers[key]
            # Direct request to a loopback native origin. Do not forward an
            # external Host/Origin to the original app's OAuth/CSRF policy.
            headers['Origin'] = base
            upstream = client.build_request(request.method, base + '/' + tail,
                params=request.query_params, headers=headers, content=await request.body())
            result = await client.send(upstream, stream=True)
            if result.status_code == 401:
                sessions.pop(scope, None)
            response_headers = {'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'}
            if tail.startswith('v2/') and tail.endswith(('.woff2','.png','.ico','.svg')):
                response_headers['Cache-Control']='private, max-age=604800, immutable'
            for key in ('content-type', 'content-disposition', 'content-range', 'accept-ranges'):
                if key in result.headers:
                    response_headers[key] = result.headers[key]
            if 'location' in result.headers:
                location = result.headers['location']
                if location.startswith('/'):
                    location = '/ombre/' + scope + location
                response_headers['Location'] = location
            if 'text/html' in result.headers.get('content-type', ''):
                html = (await result.aread()).decode('utf-8')
                await result.aclose()
                await client.aclose()
                return Response(themed_html(html, scope), status_code=result.status_code, headers=response_headers)
            if tail.startswith('v2/') and any(t in result.headers.get('content-type','') for t in ('javascript','text/css','application/json')):
                raw = (await result.aread()).decode('utf-8')
                await result.aclose()
                await client.aclose()
                prefix = '/ombre/' + scope
                raw = re.sub(r'([\"\x27`])/(api|v2)(?=[/\"\x27`?#])',lambda m:m[1]+prefix+'/'+m[2],raw)
                return Response(raw,status_code=result.status_code,headers=response_headers)
            async def stream():
                try:
                    async for chunk in result.aiter_bytes():
                        yield chunk
                finally:
                    await result.aclose()
                    await client.aclose()
            response = StreamingResponse(stream(), status_code=result.status_code, headers=response_headers)
            if tail == 'auth/logout':
                sessions.pop(scope, None)
                response.delete_cookie('lune_ombre_' + scope, path='/ombre/' + scope + '/')
            return response
        except httpx.HTTPError:
            await client.aclose()
            raise HTTPException(503, '原版 Ombre 服务暂不可用，请检查本地后台') from None


def register_provider(app, runtime):
    """Original Ombre's OpenAI-compatible clients use the owner's existing route.

    Only this loopback app exposes it. Keys are per-scope derived credentials;
    no chat tools are made available to metadata/summary calls.
    """
    @app.post('/ombre-provider/{scope}/v1/{operation}')
    async def provider(scope: str, operation: str, request: Request):
        try:
            expected = 'Bearer ' + ob.credential(scope, 'provider')
        except ValueError:
            raise HTTPException(404) from None
        if not hmac.compare_digest(request.headers.get('authorization', ''), expected):
            raise HTTPException(401, 'unauthorized')
        if operation != 'embeddings':
            raise HTTPException(404)
        data = await request.json()
        texts = data.get('input')
        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, list) or not 1 <= len(texts) <= 256 or any(not isinstance(t, str) for t in texts) or sum(map(len, texts)) > 500000:
            raise HTTPException(422, '向量输入过大或格式不正确')
        try:
            try:
                from .lune_memory import LatentEngine
            except ImportError:
                from lune_memory import LatentEngine
            vectors = (await LatentEngine(runtime['RELAY_DB']).worker({'operation': 'embed', 'input': texts}))['vectors']
            return {'object': 'list', 'model': 'BAAI/bge-small-zh-v1.5', 'data': [
                {'object': 'embedding', 'index': i, 'embedding': v} for i, v in enumerate(vectors)]}
        except (RuntimeError, OSError, ValueError, TimeoutError):
            raise HTTPException(503, '本地向量尚未就绪，未调用云端向量服务') from None

    @app.post('/ombre-provider/{scope}/v1/chat/completions')
    async def complete(scope: str, request: Request):
        try:
            expected = 'Bearer ' + ob.credential(scope, 'provider')
        except ValueError:
            raise HTTPException(404) from None
        if not hmac.compare_digest(request.headers.get('authorization', ''), expected):
            raise HTTPException(401, 'unauthorized')
        body = await request.json()
        messages = body.get('messages')
        if not isinstance(messages, list) or not messages or len(messages) > 100 or any(
            not isinstance(m, dict) or m.get('role') not in {'system', 'user', 'assistant'} or not isinstance(m.get('content'), str) for m in messages):
            raise HTTPException(422, '整理消息格式不正确')
        if sum(len(m['content']) for m in messages) > 400000:
            raise HTTPException(413, '整理输入过大')
        a = runtime['CURRENT_AGENT'].set('gpt' if scope.endswith('gpt') else 'claude')
        r = runtime['CURRENT_RUN'].set('')
        task = None
        try:
            task = asyncio.create_task(runtime['run_model'](messages, None, stream=False))
            while not task.done():
                await asyncio.wait([task], timeout=1)
                if await request.is_disconnected():
                    raise asyncio.CancelledError()
            result = await task
            if result.get('tool_calls'):
                raise HTTPException(502, '整理模型返回了工具调用')
            return {'id': 'lune-ombre-' + str(time.time_ns()), 'object': 'chat.completion', 'created': int(time.time()),
                    'model': result.get('model', 'lune-selected-model'),
                    'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': result['text']}, 'finish_reason': 'stop'}]}
        except runtime['ModelError']:
            raise HTTPException(503, '所选模型连接尚不可用；订阅模式不会自动改用 API') from None
        finally:
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            runtime['CURRENT_AGENT'].reset(a)
            runtime['CURRENT_RUN'].reset(r)
