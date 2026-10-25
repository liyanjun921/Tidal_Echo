"""Native still-true lifecycle plus Luné's evidence, scope and receipt boundaries."""
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tests import test_lune as fixtures
from backend import app as relay,lune_living_context as living
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'examples'))
import lune_claude as cli


class NativeLivingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patch=patch.dict(os.environ,{'LUNE_LIVING_CONTEXT_DIR':self.tmp.name+'/state'})
        self.patch.start();self.path=self.tmp.name+'/db';living.init(self.path)
        self.store=living.store(self.path,'gpt')
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def day(self,value):return patch.object(living,'now',return_value=datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('Asia/Shanghai')))

    def test_today_rollover_review_day_grace_archive_and_tombstone_are_distinct(self):
        with self.day('2026-10-25T23:50:00'),self.store.use('Asia/Shanghai') as native:
            native.ts.set_items([('晚饭','已经吃过'),('出门','明天准备出门')])
            native.lc.set_item('家人来访','妈妈这阵子在这里，准备下周回去',2)
        with self.day('2026-10-26T00:01:00'):
            value=living.view(self.path,'gpt');self.assertEqual(value['today'],{})
            self.assertEqual(len(value['fresh']),1)
        with self.day('2026-10-27T23:59:00'):self.assertEqual(len(living.view(self.path,'gpt')['fresh']),1)
        with self.day('2026-10-28T00:00:00'):
            value=living.view(self.path,'gpt');self.assertEqual(value['stale'][0]['expired_days'],1)
            self.assertIn('准备下周回去',value['stale'][0]['value'])
        with self.day('2026-11-03T12:00:00'):self.assertEqual(len(living.view(self.path,'gpt')['stale']),1)
        with self.day('2026-11-04T12:00:00'):
            value=living.view(self.path,'gpt');self.assertEqual(value['fresh']+value['stale'],[])
            self.assertEqual(value['archive'][0]['archive_reason'],'expired')
            with self.store.use('Asia/Shanghai') as native:
                self.assertIn('不代表事情已结束',native.lc.render_pending_block('api'))
                native.lc.mark_synced('api')
                self.assertEqual(native.lc.pending_items('api'),[])
                self.assertTrue(native.lc.pending_items('sdk'))
                native.lc.mark_synced('sdk');self.assertEqual(native.lc.load()['dropped'],[])

    def test_actual_timezone_controls_day_boundary(self):
        with self.store.use('Asia/Shanghai') as native:native.ts.set_item('今日','有事实')
        before=datetime(2026,10,25,16,1,tzinfo=ZoneInfo('UTC'))
        with patch.object(living,'now',side_effect=lambda zone:before.astimezone(ZoneInfo(zone))):
            with self.store.use('Asia/Shanghai') as native:self.assertEqual(native.ts.today(),'2026-10-26')
            with self.store.use('America/New_York') as native:self.assertEqual(native.ts.today(),'2026-10-25')

    def test_undo_restores_only_this_turn_and_keeps_a_later_overwrite(self):
        with self.store.use('Asia/Shanghai') as native:
            native.lc.set_item('来访','正在来访')
            native.lc.set_item('来访','准备离开',source_turn='a',source_session='lune-gpt')
            result=native.lc.undo_turn_writes('a','lune-gpt');self.assertEqual(result['restored'],1)
            self.assertEqual(native.lc.get_items()[0][0]['value'],'正在来访')
            native.lc.set_item('来访','准备离开',source_turn='a2',source_session='lune-gpt')
            native.lc.set_item('来访','确实已经回去了',source_turn='b',source_session='lune-gpt')
            self.assertEqual(native.lc.undo_turn_writes('a2','lune-gpt')['skipped'],1)
            self.assertEqual(native.lc.get_items()[0][0]['value'],'确实已经回去了')

    def test_stateless_requests_always_receive_the_current_complete_snapshot(self):
        with self.store.use('Asia/Shanghai') as native:native.lc.set_item('申请季','这阵子准备材料')
        one=living.projection(self.path,'lune-gpt','gpt');two=living.projection(self.path,'lune-gpt','gpt')
        self.assertIn('这阵子准备材料',one['text']);self.assertEqual(one['text'],two['text'])
        with self.store.use('Asia/Shanghai') as native:native.lc.drop_item('申请季')
        after=living.projection(self.path,'lune-gpt','gpt')['text']
        self.assertNotIn('这阵子准备材料',after)
        self.assertIn('未列出的旧项不再作为当前事实',after)
        self.assertEqual(one['status'],'ready')

    def test_persistent_session_receipts_commit_after_send_and_reinject_after_compact(self):
        text=living.projection(self.path,'lune-gpt','gpt')['text'];payload=[{'role':'system','content':text}]
        first=living.SessionHints(self.path,'gpt','s1')
        self.assertIn('<state_snapshot',first.prepare(payload)[0]['content'])
        unsent=living.SessionHints(self.path,'gpt','s1');self.assertIn('<state_snapshot',unsent.prepare(payload)[0]['content'])
        first.sent()
        same=living.SessionHints(self.path,'gpt','s1');self.assertNotIn('<state_snapshot',same.prepare(payload)[0]['content'])
        same.compacted();again=living.SessionHints(self.path,'gpt','s1')
        self.assertIn('<state_snapshot',again.prepare(payload)[0]['content'])
        self.assertIn('<state_snapshot',living.SessionHints(self.path,'gpt','s2').prepare(payload)[0]['content'])
        mirror=(self.store.hs.TRANSCRIPTS/'living-s1.jsonl').read_text()
        self.assertNotIn('今天',mirror)

    def test_missing_hint_mirror_does_not_suppress_needed_context(self):
        payload=[{'role':'system','content':living.projection(self.path,'lune-gpt','gpt')['text']}]
        receipt=living.SessionHints(self.path,'gpt','mirror');receipt.prepare(payload);receipt.sent()
        (self.store.hs.TRANSCRIPTS/'living-mirror.jsonl').unlink()
        self.assertIn('<state_snapshot',living.SessionHints(self.path,'gpt','mirror').prepare(payload)[0]['content'])

    def test_corrupt_state_is_preserved_instead_of_being_replaced_with_empty_state(self):
        target=Path(self.store.lc.PATH);target.write_text('broken original')
        with self.assertRaisesRegex(RuntimeError,'保留原文件'):living.view(self.path,'gpt')
        self.assertEqual(target.read_text(),'broken original')

    def test_four_stores_do_not_share_mutable_module_paths_or_facts(self):
        for scope in living.ob.SCOPES:
            with living.store(self.path,scope).use('Asia/Shanghai') as native:native.ts.set_item('范围',scope)
        for scope in living.ob.SCOPES:self.assertEqual(living.view(self.path,scope)['today']['范围']['v'],scope)


class OwnerLivingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.patch=patch.dict(os.environ,{'LUNE_LIVING_CONTEXT_DIR':self.tmp.name});self.patch.start()
        fixtures.OwnerDataTests.setUp(self)
        with relay.db() as db:
            db.execute('DELETE FROM lune_living_settings');db.execute('DELETE FROM lune_living_events')
    def tearDown(self):fixtures.OwnerDataTests.tearDown(self);self.patch.stop();self.tmp.cleanup()
    def get(self):return self.client.get('/lune/living/gpt').json()
    def test_owner_version_nonce_and_scope_are_checked(self):
        self.assertEqual(self.client.get('/lune/living/gpt',headers={'Authorization':'Bearer wrong'}).status_code,401)
        old=self.get();body={'name':'ctx_set','arguments':{'key':'来访','value':'准备下周回家'},'version':old['version'],'nonce':'owner-nonce-1234'}
        self.assertEqual(self.client.post('/lune/living/gpt/write',json=body).status_code,200)
        self.assertTrue(self.client.post('/lune/living/gpt/write',json=body).json()['duplicate'])
        self.assertEqual(self.client.post('/lune/living/gpt/write',json={**body,'arguments':{'key':'其他','value':'不应保存'}}).status_code,409)
        self.assertEqual(self.client.post('/lune/living/gpt/write',json={**body,'nonce':'owner-newnonce-1234'}).status_code,409)
        self.assertEqual(self.client.get('/lune/living/claude').json()['fresh'],[])
        cfg=self.get()['settings']
        self.assertEqual(self.client.patch('/lune/living/gpt/settings',json={'version':cfg['version'],'timezone':'badzone'}).status_code,422)

    def test_model_cannot_write_without_actual_current_evidence_or_cross_room(self):
        msg=relay.save_message('in','user','妈妈准备下周回家，现在还在我这里。',{'api_session':'lune-gpt'})
        with relay.db() as db:db.execute("INSERT INTO lune_runs VALUES('real-run','gpt','nonce',?,?,'running','','now','now')",(msg['id'],json.dumps(['gpt'])))
        body={'room':'lune-gpt','agent_id':'gpt','run_id':'real-run','name':'ctx_set','arguments':{'key':'妈妈来访','value':'妈妈还在这里，下周准备回家','quote':'妈妈准备下周回家，现在还在我这里。'}}
        self.assertEqual(self.client.post('/lune/assistant/living',json={**body,'room':'lune-claude'}).status_code,403)
        self.assertEqual(self.client.post('/lune/assistant/living',json={**body,'arguments':{**body['arguments'],'quote':'已经回家了'}}).status_code,422)
        self.assertEqual(self.client.post('/lune/assistant/living',json=body).status_code,200)
        self.assertEqual(self.get()['fresh'][0]['value'],'妈妈还在这里，下周准备回家')
        self.assertEqual(self.get()['events'][0]['source_id'],msg['id'])
        self.assertTrue(self.client.post('/lune/assistant/living',json=body).json()['duplicate'])
        with relay.db() as db:db.execute("UPDATE lune_runs SET state='cancelled' WHERE id='real-run'")
        self.assertEqual(self.client.post('/lune/assistant/living',json=body).status_code,409)
        value=self.get();undo=self.client.post('/lune/living/gpt/undo',json={'run_id':'real-run','version':value['version']})
        self.assertEqual(undo.json()['restored'],1);self.assertEqual(self.get()['fresh'],[])


class PersistentCliHintsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.frames=root/'frames.jsonl'
        self.env=patch.dict(os.environ,{
            'LUNE_LIVING_CONTEXT_DIR':str(root/'living'),
            'LUNE_CLAUDE_DIR':str(root/'claude'),
            'RELAY_DB':str(root/'db'),
            'RELAY_SECRET':'synthetic-only-owner',
            'LUNE_TEST_CLI_FRAMES':str(self.frames),
            'LUNE_CLAUDE_COMMAND':json.dumps([sys.executable,str(Path(__file__).resolve().parent/'claude_cli_fixture.py')])})
        self.env.start();living.init(str(root/'db'))
        self.session=cli.Session('claude')
    async def asyncTearDown(self):
        await self.session.close();self.env.stop();self.tmp.cleanup()

    async def test_real_cli_input_receipts_compaction_change_and_resume(self):
        def messages(text):return [{'role':'system','content':'固定人格'},
            {'role':'system','content':living.projection(os.environ['RELAY_DB'],'lune-claude','claude')['text']},
            {'role':'user','content':text}]
        async def send(text):
            result=await self.session.chat(messages(text),[], 'lune-claude','r1','sonnet',2,None,lambda:None,None)
            self.assertEqual(result['text'],'FIXTURE_CLAUDE_REPLY')
        def markers():
            return [str(row['message']['content']).count('<state_snapshot kind=') for row in map(json.loads,self.frames.read_text().splitlines())]
        await send('first');self.assertEqual(markers(),[2])
        await send('same');self.assertEqual(markers(),[2,0])
        await send('COMPACT_CLI_TRIGGER');self.assertEqual(markers(),[2,0,0])
        await send('after compact');self.assertEqual(markers(),[2,0,0,2])
        with living.store(os.environ['RELAY_DB'],'claude').use('Asia/Shanghai') as native:
            native.ts.set_item('今晚','已经吃过晚饭')
        await send('changed');self.assertEqual(markers(),[2,0,0,2,1])
        await self.session.close();self.session=cli.Session('claude')
        await send('resumed');self.assertEqual(markers(),[2,0,0,2,1,0])
