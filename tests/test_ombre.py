"""Host trust boundaries, per-speaker isolation, and privacy of native UI routes."""
import json
import asyncio
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from tests import test_lune as fixtures
from backend import ombre_runtime as ob
from backend.lune_ombre import themed_html, context, init
from backend.lune_server import app


class OmbreBoundaryTests(unittest.TestCase):
    def test_opening_recall_is_independent_of_latent_enabled_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp + '/memory.db'
            from backend.lune_memory import init as memory_init
            memory_init(path)
            init(path)
            tool_result = {'content': [{'type': 'text', 'text': 'original recall'}]}
            with patch('backend.lune_ombre.ob.installed', return_value=True), \
                 patch('backend.lune_ombre.ob.rpc', new=AsyncMock(return_value={'tools': []})), \
                 patch('backend.lune_ombre.ob.call', new=AsyncMock(return_value=tool_result)) as call:
                first = asyncio.run(context(path, 'lune-gpt', 'gpt', '今天的海风'))
                self.assertEqual([c.args[1] for c in call.call_args_list], ['breath', 'breath_search'])
                self.assertIn('original recall', first['text'])
                from backend.lune_memory import LatentEngine
                LatentEngine(path).finish('lune-gpt', 'gpt', 1)
                call.reset_mock()
                asyncio.run(context(path, 'lune-gpt', 'gpt', '继续'))
                self.assertEqual([c.args[1] for c in call.call_args_list], ['breath_search'])
                self.assertEqual(call.call_args.args[2]['mode'], 'automatic')

    def test_room_and_speaker_select_distinct_stores(self):
        self.assertEqual(ob.scope_for('lune-gpt', 'gpt'), 'gpt')
        self.assertEqual(ob.scope_for('lune-group', 'gpt'), 'group_gpt')
        self.assertEqual(ob.scope_for('lune-group', 'claude'), 'group_claude')
        with self.assertRaises(ValueError):
            ob.scope_for('lune-claude', 'gpt')
        with self.assertRaises(ValueError):
            ob.endpoint('../gpt')
        self.assertEqual(len({ob.credential(s, 'mcp') for s in ob.SCOPES}), 4)

    def test_owner_cookie_expires_and_cannot_cross_scope_or_purpose(self):
        token = ob.owner_ticket('gpt')
        self.assertTrue(ob.owner_valid('gpt', token))
        self.assertFalse(ob.owner_valid('claude', token))
        self.assertFalse(ob.owner_valid('gpt', ob.owner_ticket('gpt', int(time.time()) - 1)))
        self.assertFalse(ob.owner_valid('gpt', token + 'x'))
        self.assertNotIn(os.environ['RELAY_SECRET'], token)

    def test_seeded_native_config_preserves_owner_edits_and_strips_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LUNE_OMBRE_DIR': tmp,
             'OPENAI_API_KEY': 'private-upstream-marker', 'HTTP_PROXY': 'private-proxy-marker'}):
            env = ob.prepare('gpt')
            self.assertNotIn('OPENAI_API_KEY', env)
            self.assertNotIn('RELAY_SECRET', env)
            self.assertNotIn('HTTP_PROXY', env)
            config = Path(tmp) / 'gpt/config.yaml'
            value = json.loads(config.read_text())
            self.assertTrue(value['embedding']['base_url'].startswith('http://127.0.0.1:3020/'))
            value['ai_name'] = 'owner edited'
            config.write_text(json.dumps(value))
            ob.prepare('gpt')
            self.assertEqual(json.loads(config.read_text())['ai_name'], 'owner edited')

    def test_html_keeps_original_controls_and_rebases_native_assets(self):
        html = themed_html('<html><head></head><body><a href="/onboarding">wizard</a><script>fetch("/api/buckets");const BASE=location.origin;</script></body></html>', 'gpt')
        self.assertIn('href="/ombre/gpt/onboarding"', html)
        self.assertIn('fetch("/ombre/gpt/api/buckets")', html)
        self.assertIn('wizard', html)
        self.assertIn('new Request', html)
        self.assertNotIn(os.environ['RELAY_SECRET'], html)

    def test_ui_cookie_and_proxy_are_guarded(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/ombre/gpt/').status_code, 401)
            self.assertEqual(client.post('/relay/lune/ombre/gpt/open').status_code, 401)
            with patch('backend.lune_ombre.ob.installed', return_value=True):
                r = client.post('/relay/lune/ombre/gpt/open', headers={'Authorization': 'Bearer test-owner-secret-only'})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertIn('HttpOnly', r.headers['set-cookie'])
                self.assertIn('Path=/ombre/gpt/', r.headers['set-cookie'])
                self.assertNotIn(os.environ['RELAY_SECRET'], r.text + r.headers['set-cookie'])
                self.assertEqual(client.get('/ombre/claude/').status_code, 401)
                self.assertEqual(client.post('/ombre/gpt/api/config', headers={'Origin': 'https://foreign.example'}, json={}).status_code, 403)

    def test_stopped_or_wrong_room_tool_call_cannot_reach_native_service(self):
        with TestClient(app) as client, patch('backend.lune_ombre.ob.rpc', new=AsyncMock()) as rpc:
            header = {'Authorization': 'Bearer test-owner-secret-only'}
            wrong = client.post('/relay/lune/assistant/ombre', headers=header, json={
                'agent_id': 'gpt', 'room': 'lune-claude', 'run_id': 'fake', 'name': 'ombre_hold', 'arguments': {}})
            self.assertEqual(wrong.status_code, 403)
            stopped = client.post('/relay/lune/assistant/ombre', headers=header, json={
                'agent_id': 'gpt', 'room': 'lune-gpt', 'run_id': 'nonexistent', 'name': 'ombre_hold', 'arguments': {}})
            self.assertEqual(stopped.status_code, 409)
            rpc.assert_not_called()

    def test_service_worker_never_caches_native_private_routes(self):
        sw = (Path(__file__).resolve().parents[1] / 'web/sw.js').read_text()
        self.assertIn('url.pathname.startsWith("/ombre/")', sw)


if __name__ == '__main__':
    unittest.main()
