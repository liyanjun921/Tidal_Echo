"""Real native Ombre HTTP/MCP + Luné model loop; synthetic providers only."""
import asyncio
import io
import json
import os
from pathlib import Path
import sys
import time
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from backend import ombre_runtime as ob

BASE = 'http://127.0.0.1:8089'
called = set()


def native(name, args=None, scope='gpt'):
    result = asyncio.run(ob.call(scope, name, args))
    text = ob.text_result(result)
    called.add(name)
    return text


with httpx.Client(base_url=BASE, timeout=90, trust_env=False,
                  headers={'Authorization': 'Bearer fixture-owner-secret'}) as client:
    def get(path):
        r = client.get('/ombre/gpt' + path)
        r.raise_for_status()
        return r.json()

    status = client.get('/relay/lune/ombre/status').json()
    assert status['installed'] and all(r['running'] and len(r['tools']) == 16 for r in status['scopes']), status
    assert client.get('/ombre/gpt/').status_code == 401
    opened = client.post('/relay/lune/ombre/gpt/open', json={})
    opened.raise_for_status()
    page = client.get(opened.json()['url'])
    assert page.status_code == 200 and 'Ombre' in page.text and 'const prefix="/ombre/gpt"' in page.text
    assert client.get('/ombre/claude/api/buckets').status_code == 401
    for path in ['/api/buckets', '/api/config', '/api/network', '/api/status', '/api/settings/you', '/api/settings/them', '/api/import/status', '/api/embedding/info']:
        get(path)

    sent = client.post('/relay/lune/rooms/gpt/send', json={'text': 'OMBRE_WRITE_TRIGGER 请记住我们周日去海边看蓝色风筝。', 'nonce': uuid.uuid4().hex}).json()
    for _ in range(300):
        room = client.get('/relay/lune/rooms/gpt/messages').json()
        run = next(r for r in room['runs'] if r['id'] == sent['run']['id'])
        if run['state'] not in {'pending', 'running'}:
            assert run['state'] == 'completed', run
            break
        time.sleep(.1)
    else:
        raise AssertionError('Ombre model tool turn timed out')
    assert 'OMBRE_PRIVATE_MARKER' in native('breath_search', {'query': 'OMBRE_PRIVATE_MARKER', 'max_results': 2})
    for scope in ('claude', 'group_gpt', 'group_claude'):
        # A no-hit explanation legitimately echoes the query. Check the actual
        # stored body and vault, rather than mistaking that echo for a leak.
        result = native('breath_search', {'query': 'OMBRE_PRIVATE_MARKER'}, scope=scope)
        assert '用户说我们周日去海边看蓝色风筝。' not in result, (scope, result)
        client.post('/relay/lune/ombre/' + scope + '/open', json={}).raise_for_status()
        other = client.get('/ombre/' + scope + '/api/buckets')
        other.raise_for_status()
        assert other.json() == [], (scope, other.text)
    buckets = get('/api/buckets')
    marker = next((b for b in buckets if 'Ombre真实工具接线' in b['name']), None)
    assert marker, {'missing_written_title': buckets}
    native('hold', {'content': '另一件独立的经历：我今天读完了一本关于山野植物的书。', 'title': '山野植物', 'valence': .6, 'arousal': .3})
    native('grow', {'content': '第一行原文证据\n第二行不同原文', 'items': [
        {'title': '测试独立事件甲', 'content': '这是一段用于合成测试的独立记录甲。', 'source_ranges': [[1, 1]], 'domain': ['工作'], 'tags': ['甲'], 'valence': .5, 'arousal': .3},
        {'title': '测试独立事件乙', 'content': '这是另一段用于合成测试的独立记录乙。', 'source_ranges': [[2, 2]], 'domain': ['学习'], 'tags': ['乙'], 'valence': .7, 'arousal': .2}]})
    native('hold', {'content': '想到海边时，我有一种很轻快的期待。', 'feel': True, 'source_bucket': marker['id']})
    native('breath')
    native('breath_advanced', {'catalog': True})
    native('feel', {'query': '海边'})
    native('trace', {'bucket_id': marker['id'], 'arousal': .65})
    native('anchor', {'bucket_id': marker['id']})
    native('release', {'bucket_id': marker['id']})
    native('plan', {'content': '测试承诺：下次带上风筝。', 'related_bucket': marker['id']})
    native('I', {'content': '我发现自己愿意耐心核对证据。', 'aspect': 'values'})
    native('I', {'read': True})
    native('dream')
    native('pulse')
    native('letter_write', {'author': 'ai', 'ai_name': 'GPT', 'user_name': '合成用户', 'title': 'LOCKED_TITLE_MARKER', 'content': 'LOCKED_BODY_MARKER', 'lock_type': 'timed', 'unlock_date': '2099-01-01'})
    letter = next(b for b in get('/api/buckets') if b.get('type') == 'letter')
    assert 'LOCKED_BODY_MARKER' not in json.dumps(get('/api/bucket/' + letter['id']))
    assert 'LOCKED_BODY_MARKER' in native('letter_read', {'author': 'ai', 'limit': 1})
    native('letter_lock_update', {'letter_id': letter['id'], 'lock_type': 'none'})
    assert 'LOCKED_BODY_MARKER' in json.dumps(get('/api/bucket/' + letter['id']))
    for name in ('you', 'them'):
        state = get('/api/settings/' + name)
        payload = {'enabled': True, 'state_revision': state['state_revision']}
        r = client.post('/ombre/gpt/api/settings/' + name, json=payload)
        r.raise_for_status()
    tools = asyncio.run(ob.rpc('gpt', 'tools/list'))['tools']
    assert len(tools) == 18
    optional = {t['name'] for t in tools} - ob.BASE_TOOLS
    for name in optional:
        native(name)
    for name in ('you', 'them'):
        state = get('/api/settings/' + name)
        r = client.post('/ombre/gpt/api/settings/' + name, json={'enabled': False, 'state_revision': state['state_revision']})
        r.raise_for_status()
    assert len(asyncio.run(ob.rpc('gpt', 'tools/list'))['tools']) == 16
    assert ob.BASE_TOOLS <= called, ob.BASE_TOOLS - called
    exported = client.get('/ombre/gpt/api/export')
    exported.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert any('manifest' in name for name in archive.namelist()), archive.namelist()
        assert any('sources/' in name for name in archive.namelist()), archive.namelist()
    restore = client.post('/ombre/gpt/api/migrate/upload', content=exported.content, headers={'Content-Type': 'application/zip'})
    restore.raise_for_status()
    parsed = get('/api/migrate/status')
    assert parsed['phase'] == 'parsed' and parsed['integrity_verified'], parsed
    applied = client.post('/ombre/gpt/api/migrate/apply', json={
        'job_id': parsed['job_id'], 'decisions': {marker['id']: 'overwrite'}})
    assert applied.status_code == 202, applied.text
    for _ in range(300):
        progress = get('/api/migrate/status')
        if progress['phase'] in {'done', 'error'}:
            assert progress['phase'] == 'done', progress
            break
        time.sleep(.1)
    else:
        raise AssertionError('native backup restore did not finish')
    assert 'OMBRE_PRIVATE_MARKER' in json.dumps(get('/api/bucket/' + marker['id']))
    imported = json.dumps({'items': [{'name': '独立导入验收', 'content': 'OMBRE_IMPORT_MARKER 这条是所有者导入的原文。',
        'domain': ['日常'], 'tags': ['导入'], 'valence': .5, 'arousal': .2}]}, ensure_ascii=False).encode()
    preview = client.post('/ombre/gpt/api/import/preflight?filename=synthetic.json', content=imported,
        headers={'Content-Type': 'application/json'})
    preview.raise_for_status()
    assert preview.json()['can_start'], preview.text
    started = client.post('/ombre/gpt/api/import/upload?filename=synthetic.json', content=imported,
        headers={'Content-Type': 'application/json'})
    started.raise_for_status()
    for _ in range(300):
        progress = get('/api/import/status')
        if progress.get('status') in {'completed', 'error'}:
            assert progress['status'] == 'completed', progress
            break
        time.sleep(.1)
    else:
        raise AssertionError('native history import did not finish')
    assert 'OMBRE_IMPORT_MARKER' in native('breath_search', {'query': 'OMBRE_IMPORT_MARKER'})
    malformed = client.post('/ombre/gpt/api/migrate/upload', content=b'not-a-zip', headers={'Content-Type': 'application/zip'})
    assert malformed.status_code >= 400
    # dream has intentionally digested this memory. Re-enable its surfacing
    # through the original trace tool before testing automatic injection.
    native('trace', {'bucket_id': marker['id'], 'digested': False, 'dont_surface': False})
    recalled = client.post('/relay/lune/rooms/gpt/send', json={
        'text': '周日去海边看蓝色风筝这件事你想起了吗？', 'nonce': uuid.uuid4().hex}).json()
    for _ in range(300):
        room = client.get('/relay/lune/rooms/gpt/messages').json()
        run = next(r for r in room['runs'] if r['id'] == recalled['run']['id'])
        if run['state'] not in {'pending', 'running'}:
            assert run['state'] == 'completed', run
            break
        time.sleep(.1)
    else:
        raise AssertionError('automatic recall turn did not finish')
    records = [json.loads(line) for line in Path(os.environ['LUNE_TEST_REQUESTS']).read_text().splitlines()]
    assert any(any(t['function']['name'] == 'ombre_hold' for t in r.get('tools', [])) for r in records)
    assert any(any(c.get('function', {}).get('name') == 'ombre_hold' for m in r.get('messages', [])
        for c in m.get('tool_calls', [])) and any(m.get('role') == 'tool' and
        'content' in json.loads(m.get('content', '{}')) and not json.loads(m['content']).get('isError')
        for m in r.get('messages', [])) for r in records)
    assert any('OMBRE_PRIVATE_MARKER' in m.get('content', '') and 'Ombre 临时历史背景' in m.get('content', '')
        for r in records for m in r.get('messages', []) if m.get('role') == 'system')
    assert not any('Ombre 临时历史背景' in m['text'] for m in room['messages'])
    print('Ombre E2E PASS: all 16 native tools, optional You/Them gates, original Dashboard/API proxy, model tool write and automatic recall, four-scope isolation, letter lock, evidence backup restore and native import')
