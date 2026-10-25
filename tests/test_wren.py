"""Exercise Room through its real authenticated routes and scheduler commit gate."""
import asyncio
from datetime import datetime, timezone, timedelta
import json
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend import lune_wren as w


class WrenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = self.tmp.name + '/room.sqlite'
        with w.connection(self.path) as db:
            db.executescript('''CREATE TABLE messages(id INTEGER PRIMARY KEY,ts TEXT,direction TEXT,kind TEXT,text TEXT,meta TEXT);
            CREATE TABLE lune_runs(id TEXT PRIMARY KEY,room TEXT,state TEXT,targets TEXT,message_id INTEGER);
            CREATE TABLE lune_workspace(id TEXT,kind TEXT,scope TEXT,title TEXT,content TEXT,data TEXT,deleted INTEGER,updated_at TEXT);''')
        w.init(self.path)
        app = FastAPI()
        def auth(request):
            if request.headers.get('authorization') != 'Bearer fixture':
                raise HTTPException(401)
        self.publish = AsyncMock()
        self.runtime = w.register(app, {'DB_PATH': self.path, 'check_auth': auth,
            'broadcast': self.publish, 'app_subs': set(), 'app_payload': lambda m: m,
            'push_to_all': AsyncMock(), 'notification_from_message': lambda m: m})
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(lambda: self.client.__exit__(None, None, None))
        self.client.headers['Authorization'] = 'Bearer fixture'
        self.mid = self.message('想继续做海边那本小书。')
        with w.connection(self.path) as db:
            db.execute("INSERT INTO lune_runs VALUES('run','gpt','running','[\"gpt\"]',?)", (self.mid,))

    def message(self, text, room='gpt'):
        with w.connection(self.path) as db:
            return db.execute("INSERT INTO messages(ts,direction,kind,text,meta) VALUES(?,'in','user',?,?)", (
                (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(), text,
                json.dumps({'api_session': 'lune-' + room}))).lastrowid

    def stopped(self):
        with w.connection(self.path) as db:
            db.execute("UPDATE lune_runs SET state='completed'")

    def tool(self, **value):
        return self.client.post('/lune/assistant/wren', json={'room': 'lune-gpt', 'agent_id': 'gpt', 'run_id': 'run', **value})

    def status(self, scope='gpt'):
        response = self.client.get('/lune/wren/' + scope)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def setting(self, **value):
        return self.client.patch('/lune/wren/gpt', json={'version': self.status()['settings']['version'], **value})

    def timer(self, kind='say', **extra):
        value = {'kind': kind, 'text': '记得看看那本小书。', 'due': time.time() + 60, 'nonce': 'fixture-nonce-' + str(time.time()), **extra}
        response = self.client.post('/lune/wren/gpt/timers', json=value)
        self.assertEqual(response.status_code, 200, response.text)
        with w.connection(self.path) as db:
            db.execute('UPDATE lune_wren_timers SET due=? WHERE id=?', (time.time() - 1, response.json()['id']))
        return response.json()

    def test_auth_and_real_active_agent_gate(self):
        self.assertEqual(self.client.get('/lune/wren/gpt', headers={'Authorization': ''}).status_code, 401)
        self.assertEqual(self.tool(action='read', agent_id='claude').status_code, 403)
        self.stopped()
        self.assertEqual(self.tool(action='read').status_code, 409)
        self.assertFalse(self.status()['settings']['enabled'])

    def test_quote_provenance_room_cutoff_and_idempotent_touch(self):
        args = dict(action='thought', source_id=self.mid, quote='海边那本小书', drive='craft', visibility='shared')
        first = self.tool(**args)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(self.tool(**args).json()['duplicate'])
        self.assertEqual(self.tool(**{**args, 'quote': '编造的引文'}).status_code, 422)
        other = self.message('海边那本小书', 'claude')
        self.assertEqual(self.tool(**{**args, 'source_id': other}).status_code, 422)
        value = self.status()
        self.assertEqual(len(value['thoughts']), 1)
        self.assertEqual(value['intent'], 'make')
        self.assertIn('海边那本小书', w.context(self.path, 'lune-gpt', 'gpt'))
        self.assertNotIn('海边那本小书', w.context(self.path, 'lune-claude', 'claude'))

    def test_unknown_visibility_private_has_no_owner_presence_or_context(self):
        response = self.tool(action='thought', source_id=self.mid, quote='海边那本小书', drive='craft', visibility='typo')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.status()['thoughts'], [])
        self.assertEqual(self.status()['intent'], 'quiet')
        self.assertNotIn('海边那本小书', w.context(self.path, 'lune-gpt', 'gpt'))
        mine = self.tool(action='read').json()['thoughts']
        self.assertEqual(len(mine), 1)
        tid = mine[0]['id']
        self.tool(action='satisfy', id=tid)
        self.tool(action='satisfy', id=tid)
        self.assertEqual(self.tool(action='read').json()['thoughts'][0]['fed'], 1)
        self.assertEqual(self.status()['events'], [])

    def test_thoughts_decay_promote_retire_and_have_hard_cap(self):
        args = dict(action='thought', source_id=self.mid, quote='海边那本小书', drive='craft', visibility='shared')
        tid = self.tool(**args).json()['id']
        for _ in range(2):
            with w.connection(self.path) as db:
                db.execute('UPDATE lune_wren_thoughts SET updated=updated-301')
            self.tool(**args)
        self.assertEqual(self.status()['thoughts'][0]['state'], 'fixation')
        for i in range(8):
            with w.connection(self.path) as db:
                db.execute('UPDATE lune_runs SET id=?', ('r' + str(i),))
            self.tool(action='satisfy', id=tid, run_id='r' + str(i))
        self.assertEqual(self.status()['thoughts'], [])
        with w.connection(self.path) as db:
            for i in range(205):
                text = '片段' + str(i)
                db.execute('UPDATE messages SET text=? WHERE id=?', (text, self.mid))
                w.record_thought(db, 'gpt', {'source_id': self.mid, 'quote': text, 'drive': 'curiosity'}, time.time())
            self.assertEqual(db.execute('SELECT count(*) FROM lune_wren_thoughts').fetchone()[0], 200)
        sample = {'state': 'flit', 'strength': .4, 'updated': 0}
        self.assertAlmostEqual(w.thought_view(sample, 21600)['strength'], .2)

    def test_settings_version_validation_quiet_and_fatigue_gate(self):
        self.assertEqual(self.setting(idle_min=1000, idle_max=100).status_code, 422)
        self.assertEqual(self.setting(timezone='not/a/zone').status_code, 422)
        old = self.status()['settings']['version']
        baseline = {k: 0 for k in w.DRIVES}
        baseline['fatigue'] = .8
        baseline['craft'] = 1
        self.assertEqual(self.setting(baseline=baseline).status_code, 200)
        self.assertEqual(self.status()['intent'], 'rest')
        self.assertEqual(self.client.patch('/lune/wren/gpt', json={'version': old}).status_code, 409)
        cfg = self.status()['settings']
        self.assertTrue(w.quiet(cfg, datetime(2026, 1, 1, 18, tzinfo=timezone.utc).timestamp()))
        self.assertFalse(w.quiet(cfg, datetime(2026, 1, 1, 6, tzinfo=timezone.utc).timestamp()))

    def test_followup_cancelled_by_any_new_human_message_and_no_group(self):
        self.setting(enabled=True)
        first = self.tool(action='followup', text='接着聊书', minutes=30)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.tool(action='followup', text='接着聊书', minutes=30).json()['id'], first.json()['id'])
        self.message('换个话题')
        self.assertEqual(self.status()['timers'][0]['state'], 'cancelled')
        with w.connection(self.path) as db:
            with self.assertRaises(HTTPException):
                w.create_timer(db, 'group_gpt', {'text': 'x', 'due': time.time()+60, 'nonce': 'group-timer'}, time.time(), followup=True)

    def test_anchor_is_durable_not_reset_by_refresh_or_drives(self):
        one = self.status()['clock']
        self.tool(action='thought', source_id=self.mid, quote='海边', drive='craft', visibility='shared')
        self.assertEqual(self.status()['clock'], one)
        w.init(self.path)
        self.assertEqual(self.status()['clock'], one)
        self.message('新的话')
        self.assertNotEqual(self.status()['clock']['user_id'], one['user_id'])

    def test_say_bypasses_model_atomic_ledger_and_no_duplicate_after_restart(self):
        self.timer()
        self.stopped()
        with patch.object(w, 'generate', new=AsyncMock()) as generate:
            self.assertEqual(asyncio.run(self.runtime['tick']('gpt')), 'say')
            w.init(self.path)
            asyncio.run(self.runtime['tick']('gpt'))
            generate.assert_not_called()
        value = self.status()
        self.assertEqual(value['events'][0]['body'], '记得看看那本小书。')
        with w.connection(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM messages WHERE direction='out'").fetchone()[0], 1)
        self.assertEqual(self.publish.await_count, 1)

    def test_explicit_reminder_runs_while_auto_off_and_usage_is_real(self):
        self.timer('remind')
        self.stopped()
        result = {'text': '{"action":"note","text":"在房间留个手记"}', 'usage': {'prompt_tokens': 25}}
        with patch.object(w, 'generate', new=AsyncMock(return_value=result)) as generate:
            self.assertEqual(asyncio.run(self.runtime['tick']('gpt')), 'note')
            self.assertEqual(generate.await_count, 1)
        self.assertEqual(self.status()['events'][0]['usage'], {'prompt_tokens': 25})
        self.assertEqual(self.status()['timers'][0]['state'], 'done')
        self.assertEqual(self.publish.await_count, 0)

    def test_busy_and_daily_budget_never_call_model(self):
        self.timer('remind')
        with patch.object(w, 'generate', new=AsyncMock()) as generate:
            self.assertEqual(asyncio.run(self.runtime['tick']('gpt')), 'deferred')
            self.stopped()
            self.setting(daily_limit=1)
            with w.connection(self.path) as db:
                db.execute("INSERT INTO lune_wren_events VALUES('spent','gpt','wake','failed','','{}',NULL,'',?,?)", (time.time(), time.time()))
            self.assertEqual(asyncio.run(self.runtime['tick']('gpt')), 'budget')
            generate.assert_not_called()

    def test_human_preempts_generation_no_stale_delivery_and_no_auto_retry(self):
        self.timer('remind')
        self.stopped()
        async def generate(*args):
            self.message('我回来了')
            await asyncio.sleep(.3)
            return {'text': '{"action":"say","text":"旧草稿"}'}
        with patch.object(w, 'generate', new=generate):
            self.assertEqual(asyncio.run(self.runtime['tick']('gpt')), 'interrupted')
        self.assertEqual(self.publish.await_count, 0)
        self.assertEqual(self.status()['timers'][0]['state'], 'interrupted')
        with patch.object(w, 'generate', new=AsyncMock()) as generate:
            asyncio.run(self.runtime['tick']('gpt'))
            generate.assert_not_called()

    def test_invalid_output_fails_visible_no_fallback_or_raw_markers(self):
        self.timer('remind')
        self.stopped()
        with patch.object(w, 'generate', new=AsyncMock(return_value={'text': 'not JSON [PRIVATE]'})):
            self.assertEqual(asyncio.run(self.runtime['tick']('gpt')), 'failed')
        value = self.status()
        self.assertEqual(value['events'][0]['state'], 'failed')
        self.assertNotIn('[PRIVATE]', json.dumps(value))
        self.assertEqual(self.publish.await_count, 0)

    def test_timer_validation_versions_repeat_skips_missed_deliveries(self):
        self.assertEqual(self.client.post('/lune/wren/gpt/timers', json={'kind':'note','text':'x','due':time.time()+60,'nonce':'bad-kind'}).status_code, 422)
        timer = self.timer(repeat_seconds=86400)
        self.stopped()
        with w.connection(self.path) as db:
            db.execute('UPDATE lune_wren_timers SET due=due-259200 WHERE id=?', (timer['id'],))
        asyncio.run(self.runtime['tick']('gpt'))
        current = self.status()['timers'][0]
        self.assertEqual(current['state'], 'pending')
        self.assertGreater(current['due'], time.time())
        self.assertEqual(self.client.patch('/lune/wren/gpt/timers/'+timer['id'], json={'version':timer['version']}).status_code, 409)
        self.assertEqual(self.client.patch('/lune/wren/gpt/timers/'+timer['id'], json={'version':current['version']}).status_code, 200)


if __name__ == '__main__':
    unittest.main()
