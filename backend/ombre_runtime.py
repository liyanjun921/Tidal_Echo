"""Paths, identity and native HTTP client for separately installed Ombre Brain."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import time

import httpx

REVISION = '115d831d979bf67efc7150f976e2cb34c333c935'
VERSION = '3.6.14'
SCOPES = ('gpt', 'claude', 'group_gpt', 'group_claude')
BASE_TOOLS = {'breath', 'breath_search', 'breath_advanced', 'hold', 'grow', 'trace', 'dream',
              'feel', 'pulse', 'plan', 'anchor', 'release', 'letter_write', 'letter_read',
              'letter_lock_update', 'I'}
READ_TOOLS = {'breath', 'breath_search', 'breath_advanced', 'feel', 'pulse', 'letter_read'}


def scope_for(room, agent):
    if agent not in {'gpt', 'claude'} or room not in {'lune-' + agent, 'lune-group'}:
        raise ValueError('Ombre room and speaker mismatch')
    return agent if room != 'lune-group' else 'group_' + agent


def scope_check(scope):
    if scope not in SCOPES:
        raise ValueError('Unknown Ombre scope')
    return scope


def root():
    return Path(os.environ.get('LUNE_OMBRE_DIR') or
                Path(os.environ.get('RELAY_DB', 'relay.db')).resolve().parent / 'lune-private' / 'ombre')


def source():
    return Path(os.environ.get('LUNE_OMBRE_SOURCE') or root() / 'source')


def installed():
    try:
        marker = json.loads((source().parent / (source().name + '.lune-verified.json')).read_text())
        return marker['revision'] == REVISION and all(
            hashlib.sha256((source() / name).read_bytes()).hexdigest() == digest
            for name, digest in marker['files'].items())
    except (OSError, ValueError, KeyError):
        return False


def credential(scope, purpose):
    scope_check(scope)
    secret = os.environ.get('RELAY_SECRET', '')
    if not secret:
        raise RuntimeError('Missing host credential')
    return hmac.new(secret.encode(), ('ombre:' + scope + ':' + purpose).encode(), hashlib.sha256).hexdigest()


def endpoint(scope):
    scope_check(scope)
    port = int(os.environ.get('LUNE_OMBRE_PORT_BASE', '18110')) + SCOPES.index(scope)
    if not 1024 <= port <= 65535:
        raise ValueError('Ombre port range')
    return 'http://127.0.0.1:' + str(port)


def owner_ticket(scope, expires=None):
    expires = int(expires or time.time() + 3600)
    stamp = str(expires)
    mac = hmac.new(credential(scope, 'owner').encode(), stamp.encode(), hashlib.sha256).hexdigest()
    return stamp + '.' + mac


def owner_valid(scope, value):
    try:
        stamp, _ = value.split('.', 1)
        return int(stamp) > time.time() and hmac.compare_digest(value, owner_ticket(scope, int(stamp)))
    except (ValueError, TypeError):
        return False


async def rpc(scope, method, params=None):
    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        response = await client.post(endpoint(scope) + '/mcp',
            headers={'Authorization': 'Bearer ' + credential(scope, 'mcp'),
                     'Accept': 'application/json, text/event-stream'},
            json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})
    response.raise_for_status()
    value = response.json()
    if value.get('error'):
        raise RuntimeError('Original Ombre protocol error')
    return value.get('result', {})


def text_result(value):
    if value.get('isError'):
        raise RuntimeError('Original Ombre tool failed')
    return '\n'.join(c['text'] for c in value.get('content', []) if c.get('type') == 'text')


async def call(scope, name, arguments=None):
    return await rpc(scope, 'tools/call', {'name': name, 'arguments': arguments or {}})


def prepare(scope):
    """Seed only missing owner config. Later native Dashboard edits persist."""
    directory = root() / scope_check(scope)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = directory / 'config.yaml'
    if not config.exists():
        base = 'http://127.0.0.1:3020/ombre-provider/' + scope + '/v1'
        value = {'transport': 'streamable-http', 'ai_name': 'GPT' if scope.endswith('gpt') else 'Claude',
                 'timezone': 'Asia/Shanghai', 'mcp_require_auth': True, 'mcp_auth_mode': 'hybrid',
                 'dehydration': {'base_url': base, 'model': 'lune-selected-model', 'api_format': 'openai_compat',
                                 'api_key': credential(scope, 'provider'), 'max_tokens': 4096},
                 'embedding': {'enabled': True, 'background_indexing': True, 'backend': 'api',
                               'base_url': base, 'model': 'BAAI/bge-small-zh-v1.5',
                               'api_key': credential(scope, 'provider')},
                 'surfacing': {'breath_max_results': 2}}
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as file:
            json.dump(value, file, ensure_ascii=False)
    # No ambient API keys, account sessions or inherited cloud destinations.
    env = {k: v for k, v in os.environ.items() if k in {'PATH', 'SYSTEMROOT', 'WINDIR', 'LANG', 'LC_ALL', 'TMPDIR'}}
    env.update(PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
        OMBRE_VAULT_DIR=str(directory), OMBRE_CONFIG_PATH=str(config), OMBRE_LOG_DIR=str(directory / '_logs'),
        OMBRE_TRANSPORT='streamable-http', OMBRE_BIND_HOST='127.0.0.1', OMBRE_BIND_ADDRESS='127.0.0.1',
        OMBRE_PORT=endpoint(scope).rsplit(':', 1)[1], OMBRE_MCP_REQUIRE_AUTH='true',
        OMBRE_MCP_TOKEN=credential(scope, 'mcp'), OMBRE_DASHBOARD_PASSWORD=credential(scope, 'dashboard'),
        OMBRE_HOOK_TOKEN=credential(scope, 'hook'), OMBRE_HOOK_SKIP='true')
    return env
