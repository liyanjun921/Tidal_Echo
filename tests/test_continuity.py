"""Source evidence, idle preemption, Duet privacy, durable unlock and CLI protocol."""
import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend import lune_continuity as c

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
import lune_claude as cli

class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = self.tmp.name + '/db.sqlite'
        with c.connection(self.path) as db:
            db.executescript('CREATE TABLE messages(id INTEGER PRIMARY KEY,ts TEXT,direction TEXT,kind TEXT,text TEXT,meta TEXT); CREATE TABLE lune_runs(id TEXT PRIMARY KEY,room TEXT,state TEXT);')
        c.init(self.path)
        app = FastAPI()
        def auth(request):
            if request.headers.get('authorization') != 'Bearer synthetic-owner':
                raise HTTPException(401)
        self.runtime = c.register(app, {'DB_PATH': self.path, 'check_auth': auth})
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(lambda: self.client.__exit__(None, None, None))
        self.client.headers['Authorization'] = 'Bearer synthetic-owner'

    def message(self, text='下次想接着聊海边的那件事。', room='gpt'):
        with c.connection(self.path) as db:
            return db.execute('INSERT INTO messages(ts,direction,kind,text,meta) VALUES(?,?,?,?,?)',
                ((datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(), 'in', 'user', text, json.dumps({'api_session': 'lune-'+room}))).lastrowid

    def round(self, delay=3600, room='gpt'):
        r = self.client.post('/lune/duet', json={'room':room,'label':'同一段时间，各自独白','nonce':os.urandom(12).hex(),'lock_seconds':delay})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_thread_has_real_evidence_and_only_reconnects_once(self):
        mid = self.message()
        raw = json.dumps({'threads':[{'source_id':mid,'quote':'海边的那件事','text':'还想接着聊海边的事。'}]}, ensure_ascii=False)
        with patch.object(c, 'generate', new=AsyncMock(return_value=raw)) as generate:
            self.assertEqual(asyncio.run(c.make_threads(self.path, 'gpt','gpt')), 'ready')
            self.assertEqual(asyncio.run(c.make_threads(self.path, 'gpt','gpt')), 'unchanged')
            self.assertEqual(generate.await_count, 1)
        next_id = self.message('回来了')
        self.assertIn('海边', c.thread_context(self.path,'lune-gpt','gpt',next_id))
        self.assertEqual(c.thread_context(self.path,'lune-claude','claude',next_id), '')
        third_id = self.message('说新事情')
        self.assertEqual(c.thread_context(self.path,'lune-gpt','gpt',third_id), '')
        with c.connection(self.path) as db:
            db.execute('UPDATE lune_continuity_settings SET value=?', (json.dumps({'threads_enabled':False,'idle_seconds':1800}),))
        self.assertEqual(c.thread_context(self.path,'lune-gpt','gpt',next_id), '')

    def test_pass_is_durable_and_invalid_evidence_never_commits(self):
        mid = self.message()
        with patch.object(c,'generate', new=AsyncMock(return_value='PASS')):
            self.assertEqual(asyncio.run(c.make_threads(self.path,'gpt','gpt')), 'pass')
        self.assertEqual(c.thread_context(self.path,'lune-gpt','gpt'), '')
        with self.assertRaises(ValueError):
            c.validate_threads(json.dumps({'threads':[{'source_id':mid,'quote':'不存在的原话','text':'编造'}]}), c.transcript(self.path,'gpt'))

    def test_busy_and_unchanged_rooms_do_not_call_a_model(self):
        self.message()
        with c.connection(self.path) as db:
            db.execute("INSERT INTO lune_runs VALUES('active','gpt','running')")
        with patch.object(c,'generate',new=AsyncMock()) as generate:
            self.assertEqual(asyncio.run(c.make_threads(self.path,'gpt','gpt')), 'deferred')
            generate.assert_not_called()

    def test_new_real_turn_cancels_background_before_commit(self):
        self.message()
        async def generate(*args):
            with c.connection(self.path) as db:
                db.execute("INSERT INTO lune_runs VALUES('active','gpt','pending')")
            await asyncio.sleep(5)
            return 'PASS'
        with patch.object(c,'generate',new=generate), self.assertRaises(HTTPException):
            asyncio.run(c.make_threads(self.path,'gpt','gpt'))
        with c.connection(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM lune_idle_threads').fetchone()[0],0)

    def test_duet_never_exposes_author_body_until_both_ready_and_unlocked(self):
        r = self.round()
        written = self.client.post('/lune/duet/'+r['id']+'/write', json={'body':'PRIVATE_USER_DIARY_MARKER'})
        self.assertNotIn('PRIVATE_USER_DIARY_MARKER', written.text)
        with c.connection(self.path) as db:
            db.execute("INSERT INTO lune_duet_entries VALUES(?,'assistant',?,'ready','')",(r['id'],'PRIVATE_ASSISTANT_DIARY_MARKER'))
        self.assertNotIn('PRIVATE_USER_DIARY_MARKER',self.client.get('/lune/duet').text)
        self.assertEqual(c.duet_context(self.path,'lune-gpt','gpt'),'')
        self.assertNotIn('PRIVATE_ASSISTANT_DIARY_MARKER',json.dumps(c.round_view(self.path,r['id'])))
        with c.connection(self.path) as db:
            db.execute('UPDATE lune_duet_rounds SET unlock_at=0')
        self.assertIn('PRIVATE_USER_DIARY_MARKER',self.client.get('/lune/duet').text)
        self.assertIn('PRIVATE_ASSISTANT_DIARY_MARKER',c.duet_context(self.path,'lune-gpt','gpt'))
        self.assertEqual(c.duet_context(self.path,'lune-claude','claude'),'')
        self.assertEqual(c.duet_context(self.path,'lune-group','gpt'),'')

    def test_unlock_notifications_are_once_each_and_survive_restart(self):
        r=self.round(0)
        with c.connection(self.path) as db:
            db.executemany("INSERT INTO lune_duet_entries VALUES(?,?,?,'ready','')",[(r['id'],a,a+' diary') for a in ('user','assistant')])
        for _ in range(3): c.unlock_notifications(self.path)
        c.init(self.path)
        with c.connection(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM lune_duet_notifications').fetchone()[0],2)
        c.acknowledge_assistant(self.path,'lune-gpt','gpt')
        self.assertEqual(c.duet_context(self.path,'lune-gpt','gpt'),'')
        self.assertTrue(self.client.get('/lune/duet').json()['notifications'])

    def test_duet_drafts_cannot_be_rewritten_and_empty_snapshot_stays_empty(self):
        r=self.round(0)
        self.message('NEW_AFTER_SNAPSHOT')
        self.assertEqual(c.transcript(self.path,'gpt',r['cutoff']),[])
        self.client.post('/lune/duet/'+r['id']+'/write',json={'body':'first'})
        self.assertEqual(self.client.post('/lune/duet/'+r['id']+'/write',json={'body':'changed'}).status_code,409)
        self.assertTrue(c.round_view(self.path,r['id'])['locked'])
        self.assertEqual(self.client.post('/lune/duet',json={'room':'group','label':'bad','nonce':'123456789012'}).status_code,422)

    def test_reply_only_acknowledges_the_notices_it_received(self):
        def ready():
            r = self.round(0)
            with c.connection(self.path) as db:
                db.executemany("INSERT INTO lune_duet_entries VALUES(?,?,?,'ready','')", [(r['id'], a, a+' diary') for a in ('user','assistant')])
            return r['id']
        first = ready()
        _, delivered = c.duet_delivery(self.path, 'lune-gpt', 'gpt')
        self.assertEqual(delivered, [first])
        second = ready()
        c.unlock_notifications(self.path)
        c.acknowledge_assistant(self.path, 'lune-gpt', 'gpt', delivered)
        self.assertEqual(c.duet_delivery(self.path, 'lune-gpt', 'gpt')[1], [second])
        c.acknowledge_assistant(self.path, 'lune-claude', 'claude', [second])
        self.assertEqual(c.duet_delivery(self.path, 'lune-gpt', 'gpt')[1], [second])

    def test_diary_generation_uses_no_partner_draft_or_other_room(self):
        self.message('ALLOWED_CHAT')
        self.message('OTHER_ROOM_PRIVATE',room='claude')
        r=self.round()
        self.client.post('/lune/duet/'+r['id']+'/write',json={'body':'PARTNER_DRAFT_PRIVATE'})
        with patch.object(c,'generate',new=AsyncMock(return_value='独立日记正文')) as generate:
            self.client.post('/lune/duet/'+r['id']+'/generate').raise_for_status()
            for _ in range(100):
                rows=self.client.get('/lune/duet').json()['rounds'][0]['entries']
                if any(x['author']=='assistant' and x['state']=='ready' for x in rows):break
            else:self.fail('diary did not finish')
            prompt=generate.call_args.args[1]
            self.assertIn('ALLOWED_CHAT',prompt)
            self.assertNotIn('PARTNER_DRAFT_PRIVATE',prompt)
            self.assertNotIn('OTHER_ROOM_PRIVATE',prompt)

class ClaudeBridgeTests(unittest.TestCase):
    def test_persistent_process_reused_and_background_process_is_separate(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{
            'RELAY_DB':tmp+'/db','RELAY_SECRET':'synthetic','LUNE_CLAUDE_DIR':tmp+'/cli',
            'OPENAI_API_KEY':'blocked','ANTHROPIC_API_KEY':'blocked',
            'LUNE_CLAUDE_COMMAND':json.dumps([sys.executable,str(Path(__file__).with_name('claude_cli_fixture.py'))])}):
            async def run():
                session=cli.Session('claude')
                messages=[{'role':'system','content':'完整自定义人格\n逐字保留。'},{'role':'user','content':'first'}]
                try:
                    result=await session.chat(messages,[],'lune-claude','run','sonnet',1,None,lambda:None,None)
                    first_pid=session.proc.pid
                    self.assertEqual(result['text'],'FIXTURE_CLAUDE_REPLY')
                    self.assertEqual(result['thinking'],'')
                    messages[-1]['content']='second'
                    await session.chat(messages,[],'lune-claude','run2','sonnet',1,None,lambda:None,None)
                    self.assertEqual(session.proc.pid,first_pid)
                    self.assertEqual(session.state['usage']['input_tokens'],101)
                    pool=cli.Pool()
                    self.assertEqual((await pool.generate(messages,'sonnet'))['text'],'SYNTHETIC_BACKGROUND_DIARY')
                    self.assertEqual(session.proc.pid,first_pid)
                    messages[-1]['content']='FAIL_CLI_TRIGGER'
                    with self.assertRaises(cli.ClaudeError):
                        await session.chat(messages,[],'lune-claude','run3','sonnet',1,None,lambda:None,None)
                    self.assertIsNone(session.proc)
                finally:
                    await session.close()
            asyncio.run(run())

    def test_scopes_and_api_credentials_are_separate(self):
        self.assertEqual(cli.scope_for('lune-claude'),'claude')
        self.assertEqual(cli.scope_for('lune-group'),'group_claude')
        with self.assertRaises(cli.ClaudeError):cli.scope_for('lune-gpt')
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'x','OPENAI_API_KEY':'y','RELAY_SECRET':'z','ANTHROPIC_BASE_URL':'cloud'}):
            value=cli.cli_env()
        self.assertFalse(any(k in value for k in ('ANTHROPIC_API_KEY','OPENAI_API_KEY','RELAY_SECRET','ANTHROPIC_BASE_URL')))


class ForgeHostTests(unittest.TestCase):
    setUp = ContinuityTests.setUp
    message = ContinuityTests.message
    # Reuse only the isolated fixture setup, not all parent test methods.
    def test_original_forge_preserves_thinking_and_swaps_only_after_archive(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        from backend.lune_memory import LatentEngine
        if not LatentEngine(self.path).installation():
            self.skipTest('original Latent source required')
        order=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length=int(self.headers['Content-Length']);body=json.loads(self.rfile.read(length))
                order.append('checkpoint')
                payload=json.dumps({'jsonrpc':'2.0','id':body.get('id'),'result':{'content':[{'type':'text','text':'saved'}]}}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(payload)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        env={'RELAY_DB':self.path,'RELAY_SECRET':'synthetic-owner','LUNE_CLAUDE_DIR':self.tmp.name+'/cli',
             'CLAUDE_CONFIG_DIR':self.tmp.name+'/official-cli','RELAY_URL':'http://127.0.0.1:'+str(server.server_port)+'/relay',
             'LUNE_CLAUDE_COMMAND':json.dumps([sys.executable,str(Path(__file__).with_name('claude_cli_fixture.py'))])}
        self.message('等待续接的真实合成对话',room='claude')
        with patch.dict(os.environ,env):
            async def run():
                p=cli.Pool();s=p.get('lune-claude')
                messages=[{'role':'system','content':'完整人格原文'},{'role':'user','content':'hello'}]
                try:
                    await s.chat(messages,[],'lune-claude','run','sonnet',1,None,lambda:None,None)
                    old=s.proc;old_sid=s.state['session_id']
                    directory=Path(env['CLAUDE_CONFIG_DIR'])/'projects'/'fixture';directory.mkdir(parents=True)
                    transcript=directory/(old_sid+'.jsonl')
                    events=[]
                    for i in range(24):
                        is_user=i%2==0
                        content='synthetic body '+str(i)+' x'*3000 if is_user else [{'type':'thinking','thinking':'OPAQUE_THINKING_KEEP','signature':'SIGNED_OPAQUE'},{'type':'text','text':'synthetic reply'}]
                        events.append({'type':'user' if is_user else 'assistant','uuid':str(i),'parentUuid':str(i-1) if i else None,
                            'sessionId':old_sid,'timestamp':'2026-01-01T10:00:00Z','message':{'role':'user' if is_user else 'assistant','content':content,**({'usage':{'input_tokens':180000}} if i==23 else {})}})
                    transcript.write_text('\n'.join(json.dumps(e) for e in events))
                    s.state['usage']={'input_tokens':180000}
                    async def fail_prepare(room):raise RuntimeError('archive failed')
                    await p.maintain(self.path,fail_prepare)
                    self.assertIs(s.proc,old)
                    self.assertEqual(s.state['session_id'],old_sid)
                    async def interrupted_prepare(room):
                        with c.connection(self.path) as db:
                            db.execute("INSERT INTO lune_runs VALUES('new-turn','claude','pending')")
                        await asyncio.sleep(5)
                    await asyncio.wait_for(p.maintain(self.path,interrupted_prepare), 2)
                    self.assertIs(s.proc,old)
                    self.assertIsNone(old.returncode)
                    with c.connection(self.path) as db:
                        db.execute("DELETE FROM lune_runs WHERE id='new-turn'")
                    async def prepare(room):order.append('archive')
                    await p.maintain(self.path,prepare)
                    self.assertEqual(p.maintenance_state['claude']['state'],'forged',p.maintenance_state)
                    self.assertNotEqual(s.proc.pid,old.pid)
                    self.assertIsNotNone(old.returncode)
                    self.assertTrue(transcript.exists())
                    rewritten=directory/(s.state['session_id']+'.jsonl')
                    value=rewritten.read_text()
                    self.assertIn('OPAQUE_THINKING_KEEP',value)
                    self.assertIn('SIGNED_OPAQUE',value)
                    chain=[json.loads(line) for line in value.splitlines()]
                    self.assertIsNone(chain[0]['parentUuid'])
                    self.assertEqual(order,['archive','checkpoint'])
                    await s.chat(messages,[],'lune-claude','next','sonnet',1,None,lambda:None,None)
                finally:
                    await p.close()
            asyncio.run(run())

if __name__=="__main__": unittest.main()
