"""Trust boundaries for native emotional state, owner projections and model calls."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock,patch

from tests import test_lune as fixtures
from backend import app as relay,xinchao_runtime as xc
from backend.lune_ombre import context as memory_context,init as ombre_init
from backend.lune_memory import init as memory_init
from backend.lune_xinchao import context,acknowledge,init
from backend.lune_continuity import connection


class XinchaoConfigurationTests(unittest.TestCase):
    def test_owner_edits_preserved_and_children_cannot_inherit_secrets(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'LUNE_XINCHAO_DIR':tmp,'OPENAI_API_KEY':'never-in-child','HTTP_PROXY':'never-in-child'}):
            cfg=xc.save_config('gpt',{'agent_name':'自己的称呼'},0)
            env=xc.prepare('gpt')
            self.assertEqual(env['AGENT_NAME'],'自己的称呼')
            self.assertEqual(xc.config('gpt')['version'],1)
            for key in ['RELAY_SECRET','OPENAI_API_KEY','HTTP_PROXY']:self.assertNotIn(key,env)
            self.assertEqual(env['MODEL_ENABLED'],'false')
            self.assertTrue(env['MODEL_BASE_URL'].startswith('http://127.0.0.1:3020/'))
            self.assertEqual((Path(tmp)/'gpt/lune-config.json').stat().st_mode & 0o777,0o600)
            with self.assertRaises(ValueError):xc.save_config('gpt',{},0)
            with self.assertRaises(ValueError):xc.save_config('gpt',{'interaction_rules':{'shy':['[']}},1)
            self.assertEqual(xc.config('gpt'),cfg)
            self.assertEqual(len({xc.credential(s,'service') for s in xc.SCOPES}),4)
            self.assertNotEqual(xc.credential('gpt','service'),xc.credential('gpt','provider'))

    def test_recall_uses_current_advanced_tool_and_keeps_the_original_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=tmp+'/memory.db';memory_init(path);ombre_init(path)
            result={'content':[{'type':'text','text':'the original memory'}]}
            with patch('backend.lune_ombre.ob.installed',return_value=True),patch('backend.lune_ombre.ob.rpc',new=AsyncMock(return_value={'tools':[]})),patch('backend.lune_ombre.ob.call',new=AsyncMock(return_value=result)) as call,patch.object(xc,'installed',return_value=True),patch.object(xc,'request',new=AsyncMock(return_value={'emotion':{'valence':.6,'arousal':.4}})):
                value=asyncio.run(memory_context(path,'lune-gpt','gpt','原话查询',False,'actual-run'))
            self.assertEqual(value['status'],'ready')
            self.assertEqual(call.call_args.args[1],'breath_advanced')
            self.assertEqual(call.call_args.args[2],{'query':'原话查询','max_results':2,'mode':'automatic','valence':.6,'arousal':.4})

    def test_only_exact_same_scope_notices_are_acknowledged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=tmp+'/db';init(path)
            with connection(path) as db:
                for scope in ['gpt','group_gpt','claude']:
                    db.execute("INSERT INTO lune_xinchao_bridge VALUES(?,?,?,'private','pending',0)",(scope,'delivery-same','self_signal'))
                db.execute("INSERT INTO lune_xinchao_bridge VALUES('gpt','delivery-new','self_signal','private','pending',1)")
            acknowledge(path,'lune-gpt','gpt',['delivery-same'])
            with connection(path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM lune_xinchao_bridge WHERE state='seen'").fetchone()[0],1)
                self.assertEqual(db.execute("SELECT state FROM lune_xinchao_bridge WHERE id='delivery-new'").fetchone()[0],'pending')


class XinchaoOwnerBoundaryTests(unittest.TestCase):
    setUp=fixtures.OwnerDataTests.setUp
    tearDown=fixtures.OwnerDataTests.tearDown

    def test_auth_and_no_owner_route_to_black_box_or_raw_state(self):
        self.assertEqual(self.client.get('/lune/xinchao/gpt/status',headers={'Authorization':'Bearer wrong'}).status_code,401)
        for page in ['state','box','black-box','pending']:
            self.assertEqual(self.client.get('/lune/xinchao/gpt/view/'+page).status_code,404)
        self.assertEqual(self.client.post('/lune/xinchao/gpt/bridge',json={'reason':'self_signal'}).status_code,422)
        self.assertEqual(self.client.get('/lune/xinchao/unknown/status').status_code,422)

    def test_stopped_runs_and_other_speakers_cannot_write_or_read_private_tools(self):
        value={'agent_id':'gpt','room':'lune-gpt','run_id':'absent','name':'xinchao_box','arguments':{'action':'list'}}
        with patch.object(xc,'installed',return_value=True),patch.object(xc,'call',new=AsyncMock()) as call:
            self.assertEqual(self.client.post('/lune/assistant/xinchao',json=value).status_code,409)
            self.assertEqual(self.client.post('/lune/assistant/xinchao',json={**value,'room':'lune-claude'}).status_code,403)
        call.assert_not_awaited()

    def test_event_uses_canonical_user_evidence_instead_of_model_invented_exchange(self):
        msg=relay.save_message('in','user','实际说过的话',{'api_session':'lune-gpt'})
        with relay.db() as db:db.execute("INSERT INTO lune_runs VALUES('real-run','gpt','nonce',?,?,'running','','now','now')",(msg['id'],json.dumps(['gpt'])))
        with patch.object(xc,'installed',return_value=True),patch.object(xc,'call',new=AsyncMock(return_value={'content':[]})) as call:
            res=self.client.post('/lune/assistant/xinchao',json={'agent_id':'gpt','room':'lune-gpt','run_id':'real-run','name':'xinchao_event','arguments':{'event_id':'made-up','session_id':'other-room','exchange':'编造的亲密对话'}})
            self.assertEqual(res.status_code,200,res.text)
            args=call.call_args.args[2]
            self.assertEqual(args['exchange'],'她说：实际说过的话')
            self.assertEqual(args['session_id'],'lune-gpt')
            self.assertEqual(args['event_id'],'tool:real-run:gpt')
