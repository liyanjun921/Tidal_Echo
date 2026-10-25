"""Official Claude Code stream-json host. No account token import or API fallback."""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from fastapi import HTTPException, Request


class ClaudeError(Exception):
    pass


def command():
    # Server-only JSON argv, never executable text received from the browser.
    custom = os.environ.get('LUNE_CLAUDE_COMMAND')
    value = json.loads(custom) if custom else [shutil.which('claude') or 'claude']
    if not isinstance(value, list) or not value or any(not isinstance(p, str) for p in value):
        raise ClaudeError('Claude 启动配置无效')
    return value


def enabled():
    return os.environ.get('LUNE_CLAUDE_ENABLED') == '1'


async def require_login():
    proc = await asyncio.create_subprocess_exec(*command(), 'auth', 'status', env=cli_env(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), 15)
        data = json.loads(raw)
        if proc.returncode or data.get('authMethod') != 'claude.ai' or data.get('loggedIn') is False:
            raise ClaudeError('需要官方 Claude 订阅登录；拒绝 API Key、Console 或第三方计费身份')
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.communicate()


def root():
    return Path(os.environ.get('LUNE_CLAUDE_DIR') or Path(os.environ['RELAY_DB']).resolve().parent / 'lune-private/claude-code')


def cli_env():
    # CLI uses its own official login. Ambient API credentials cannot silently
    # replace the user's subscription, including those for unrelated providers.
    blocked = ('API_KEY', 'AUTH_TOKEN', 'BEARER_TOKEN', 'RELAY_SECRET')
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in blocked)
           and not k.startswith(('ANTHROPIC_', 'AWS_', 'GOOGLE_', 'AZURE_', 'CLAUDE_CODE_USE_'))}
    env.pop('CLAUDECODE', None)
    env['DISABLE_NON_ESSENTIAL_TRAFFIC'] = '1'
    return env


def token(scope):
    return hmac.new(os.environ['RELAY_SECRET'].encode(), ('lune-cli:' + scope).encode(), hashlib.sha256).hexdigest()


def scope_for(room):
    if room not in {'lune-claude', 'lune-group'}:
        raise ClaudeError('Claude 会话范围无效')
    return 'claude' if room == 'lune-claude' else 'group_claude'


class Session:
    def __init__(self, scope):
        self.scope, self.proc = scope, None
        self.directory = root() / scope
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_file = self.directory / 'host-state.json'
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        self.lock = asyncio.Lock()
        self.binding = None
        self.signature = None
        self.was_started = False

    def save(self):
        target = self.directory / ('.state-' + uuid.uuid4().hex)
        target.write_text(json.dumps(self.state), encoding='utf-8')
        os.chmod(target, 0o600)
        target.replace(self.state_file)

    async def close(self):
        proc, self.proc = self.proc, None
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.communicate(), 5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()

    async def boot(self, persona, model, tools, resume=None):
        await require_login()
        prompt = self.directory / 'persona.md'
        prompt.write_text(persona, encoding='utf-8')
        os.chmod(prompt, 0o600)
        mcp = self.directory / 'mcp.json'
        value = {'mcpServers': {'lune': {'type': 'http', 'url': 'http://127.0.0.1:3020/loop/claude/mcp/' + self.scope,
                 'headers': {'Authorization': 'Bearer ' + token(self.scope)}}}} if tools else {'mcpServers': {}}
        mcp.write_text(json.dumps(value))
        os.chmod(mcp, 0o600)
        args = command() + ['-p', '--input-format', 'stream-json', '--output-format', 'stream-json',
            '--include-partial-messages', '--verbose', '--max-turns', '8', '--tools', '', '--strict-mcp-config',
            '--mcp-config', str(mcp), '--permission-mode', 'dontAsk', '--system-prompt-file', str(prompt),
            '--settings', '{"disableAllHooks":true}', '--setting-sources', '']
        if tools:
            args += ['--allowedTools', ','.join('mcp__lune__' + t['function']['name'] for t in tools)]
        if model:
            args += ['--model', model]
        if resume:
            args += ['--resume', resume]
        return await asyncio.create_subprocess_exec(*args, cwd=self.directory, env=cli_env(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=8*1024*1024)

    async def chat(self, messages, tools, room, run_id, model, current_index, sink, gate, dispatch):
        async with self.lock:
            gate()
            self.binding = {'tools': tools or [], 'room': room, 'run_id': run_id, 'dispatch': dispatch}
            persona = str(messages[0]['content'])
            signature = hashlib.sha256((persona + model + json.dumps(tools, sort_keys=True)).encode()).hexdigest()
            self.last_tools = tools or []
            try:
                # A changed persona/tool set starts a fresh projection from the
                # preserved SQL history. It cannot keep a stale recorded prompt.
                if self.proc and self.signature != signature or self.state.get('signature') and self.state['signature'] != signature:
                    await self.close()
                    self.state = {}
                    self.save()
                fresh = self.proc is None or self.proc.returncode is not None
                if fresh:
                    self.proc = await self.boot(persona, model, tools, self.state.get('session_id'))
                    self.signature = signature
                    self.was_started = True
                if fresh and not self.state.get('session_id'):
                    payload = messages[1:]
                else:
                    # Fixed protocol goes in the original system prompt; only
                    # current memory/background and current turn are resent.
                    payload = [m for m in messages[1:current_index] if m['role'] == 'system'] + messages[current_index:]
                frame = {'type': 'user', 'message': {'role': 'user', 'content': self.content(payload)}, 'parent_tool_use_id': None}
                self.proc.stdin.write(json.dumps(frame, ensure_ascii=False).encode() + b'\n')
                await self.proc.stdin.drain()
                text, usage = [], {}
                while True:
                    gate()
                    try:
                        line = await asyncio.wait_for(self.proc.stdout.readline(), 1)
                    except asyncio.TimeoutError:
                        continue
                    if not line:
                        raise ClaudeError('Claude 进程已退出；原始聊天保留，未重放本轮')
                    event = json.loads(line)
                    kind = event.get('type')
                    if kind == 'system' and event.get('subtype') == 'init':
                        self.state['session_id'] = event['session_id']
                        self.save()
                    if kind == 'stream_event':
                        delta = event.get('event', {}).get('delta', {})
                        if delta.get('type') == 'text_delta':
                            text.append(delta.get('text', ''))
                            if sink:
                                await sink(delta.get('text', ''))
                    if kind == 'assistant':
                        usage = event.get('message', {}).get('usage') or usage
                    if kind == 'result':
                        if event.get('subtype') != 'success' or event.get('is_error'):
                            raise ClaudeError('Claude 本轮未完成，请检查官方 CLI 登录或额度；没有改用 API')
                        self.state.update(session_id=event.get('session_id') or self.state.get('session_id'), usage=usage or event.get('usage', {}), model=model, signature=signature)
                        self.save()
                        return {'text': event.get('result') or ''.join(text), 'thinking': '', 'usage': self.state['usage'], 'tool_calls': []}
            except BaseException:
                await self.close()
                raise
            finally:
                self.binding = None

    @staticmethod
    def content(payload):
        text_rows, images = [], []
        for item in payload:
            content = item.get('content')
            if isinstance(content, list):
                texts = []
                for part in content:
                    if part.get('type') == 'text':
                        texts.append(part.get('text', ''))
                    elif part.get('type') == 'image_url':
                        url = part['image_url']['url']
                        if not url.startswith('data:'):
                            raise ClaudeError('Claude 图片必须来自已验证的本地附件')
                        header, data = url.split(',', 1)
                        images.append({'type': 'image', 'source': {'type': 'base64', 'media_type': header[5:].split(';')[0], 'data': data}})
                content = '\n'.join(texts)
            text_rows.append({'role': item['role'], 'content': content})
        return [{'type': 'text', 'text': '以下是宿主提供的本轮消息与历史资料，system 标记为宿主背景；以当前用户消息为准。\n' + json.dumps(text_rows, ensure_ascii=False)}] + images


class Pool:
    def __init__(self):
        self.sessions = {}
        self.maintenance_state = {}

    def get(self, room):
        scope = scope_for(room)
        if scope not in self.sessions:
            self.sessions[scope] = Session(scope)
        return self.sessions[scope]

    async def close(self):
        await asyncio.gather(*(s.close() for s in self.sessions.values()))
        self.sessions.clear()

    async def generate(self, messages, model):
        # A distinct temporary process: no MCP or filesystem tools, no resume.
        import tempfile
        await require_login()
        root().mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix='lune-generation-', dir=root()) as tmp:
            prompt = Path(tmp) / 'prompt.md'
            prompt.write_text(str(messages[0]['content']), encoding='utf-8')
            args = command() + ['-p', '--output-format', 'json', '--tools', '', '--strict-mcp-config',
                    '--mcp-config', '{"mcpServers":{}}', '--settings', '{"disableAllHooks":true}', '--setting-sources', '',
                    '--permission-mode', 'dontAsk', '--system-prompt-file', str(prompt)]
            if model:
                args += ['--model', model]
            proc = await asyncio.create_subprocess_exec(*args, cwd=tmp, env=cli_env(),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(json.dumps(messages[1:], ensure_ascii=False).encode()), 600)
                value = json.loads(stdout)
                if proc.returncode or value.get('is_error') or value.get('subtype') != 'success':
                    raise ClaudeError('Claude 后台生成未完成')
                return {'text': value['result'], 'thinking': '', 'usage': value.get('usage', {}), 'tool_calls': []}
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.communicate()

    async def maintain(self, path, prepare):
        try:
            from lune_continuity import activity, idle, guarded_generation
            from lune_memory import LatentEngine
        except ModuleNotFoundError:
            from backend.lune_continuity import activity, idle, guarded_generation
            from backend.lune_memory import LatentEngine
        for scope, session in list(self.sessions.items()):
            room = 'claude' if scope == 'claude' else 'group'
            usage = session.state.get('usage') or {}
            size = sum(int(usage.get(k) or 0) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
            threshold = int(os.environ.get('LUNE_CLAUDE_FORGE_THRESHOLD', '150000'))
            retain = int(os.environ.get('LUNE_CLAUDE_FORGE_RETAIN', '50000'))
            if not 1000 <= retain < threshold or size <= threshold or not idle(path, room, 30) or session.lock.locked():
                continue
            async with session.lock:
                before = activity(path, room)
                try:
                    engine = LatentEngine(path)
                    if not engine.installation():
                        raise ClaudeError('缺少已验证的原版 Forge')
                    await guarded_generation(path, room, prepare(room), cursor=before['cursor'])
                    if activity(path, room) != before:
                        continue
                    sid = session.state.get('session_id')
                    home = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'projects'
                    files = list(home.rglob(str(sid) + '.jsonl')) if sid else []
                    if len(files) != 1:
                        raise ClaudeError('未找到唯一的官方会话文件，未重铸')
                    env = {**os.environ, 'LATENT_MCP_URL': os.environ['RELAY_URL'] + '/lune/native/' + room + '/mcp',
                           'LATENT_MCP_TOKEN': os.environ['RELAY_SECRET']}
                    proc = await asyncio.create_subprocess_exec(sys.executable, str(engine.source() / 'src/forge_session.py'),
                        'forge', str(files[0]), '--threshold', str(threshold), '--retain', str(retain),
                        '--state-dir', str(session.directory / 'forge-state'),
                        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
                    try:
                        raw, _ = await asyncio.wait_for(guarded_generation(path, room, proc.communicate(), cursor=before['cursor']), 180)
                    finally:
                        if proc.returncode is None:
                            proc.kill()
                            await proc.communicate()
                    value = json.loads(raw)
                    if proc.returncode or value.get('status') != 'forged':
                        self.maintenance_state[scope] = {'state': 'skipped', 'reason': '原版未通过续接条件'}
                        continue
                    if activity(path, room) != before:
                        continue
                    persona = (session.directory / 'persona.md').read_text()
                    tools = self.tools_for_scope(scope)
                    replacement = await session.boot(persona, session.state.get('model', ''), tools, value['sessionId'])
                    # Require an actual ready/init event before relinquishing the
                    # old process. Unsupported CLI versions retain the old one.
                    try:
                        init_event = json.loads(await asyncio.wait_for(guarded_generation(path, room, replacement.stdout.readline(), cursor=before['cursor']), 15))
                        if init_event.get('type') != 'system' or init_event.get('subtype') != 'init' or init_event.get('session_id') != value['sessionId']:
                            raise ClaudeError('新进程没有就绪')
                        if activity(path, room) != before:
                            raise ClaudeError('用户已恢复聊天')
                    except BaseException:
                        if replacement.returncode is None:
                            replacement.kill()
                        await replacement.communicate()
                        raise
                    await session.close()
                    session.proc = replacement
                    session.state['session_id'] = value['sessionId']
                    session.state['usage'] = {}
                    session.save()
                    self.maintenance_state[scope] = {'state': 'forged'}
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.maintenance_state[scope] = {'state': 'deferred', 'reason': '落档、官方文件或新进程未通过检查；保留旧会话'}

    def tools_for_scope(self, scope):
        return getattr(self.sessions[scope], 'last_tools', [])


pool = Pool()


def register(app, runtime):
    @app.post('/loop/claude/mcp/{scope}')
    async def mcp(scope: str, request: Request):
        if scope not in {'claude', 'group_claude'} or not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + token(scope)):
            raise HTTPException(401)
        msg = await request.json()
        if not isinstance(msg, dict) or not isinstance(msg.get('method'), str):
            raise HTTPException(422, 'MCP 请求格式不正确')
        session = pool.sessions.get(scope)
        binding = session.binding if session else None
        method, rid = msg.get('method'), msg.get('id')
        if method == 'initialize':
            result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': {'name': 'lune-scoped-host', 'version': '0.11'}}
        elif method.startswith('notifications/'):
            from fastapi.responses import Response
            return Response(status_code=202)
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            tools = binding['tools'] if binding else getattr(session, 'last_tools', [])
            result = {'tools': [{'name': t['function']['name'], 'description': t['function'].get('description', ''), 'inputSchema': t['function']['parameters']} for t in tools]}
        elif method == 'tools/call':
            if not binding:
                raise HTTPException(409, '没有有效聊天回合')
            params = msg.get('params')
            if not isinstance(params, dict) or not isinstance(params.get('arguments', {}), dict):
                raise HTTPException(422, '工具参数格式不正确')
            name = params.get('name')
            if name not in {t['function']['name'] for t in binding['tools']}:
                raise HTTPException(403, '工具未授权')
            result = {'content': [{'type': 'text', 'text': await binding['dispatch'](name, msg['params'].get('arguments', {}))}]}
        else:
            return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': 'Method not found'}}
        return {'jsonrpc': '2.0', 'id': rid, 'result': result}

    @app.get('/loop/claude/status')
    async def status():
        available = bool(shutil.which(command()[0]))
        ready = enabled() and available and any(s.proc and s.proc.returncode is None and s.state.get('signature') for s in pool.sessions.values())
        return {'ready': bool(ready), 'enabled': enabled(), 'installed': available,
                'sessions': {scope: {'running': bool(s.proc and s.proc.returncode is None), 'maintenance': pool.maintenance_state.get(scope)} for scope, s in pool.sessions.items()},
                'message': '已接入官方 Claude Code 常驻桥接；需在运行电脑登录官方 CLI 并完成账号验收。' if available else '桥接代码已接入，运行端尚未安装官方 Claude Code。'}
