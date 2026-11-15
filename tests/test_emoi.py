"""Owner/auth, durable delivery, memory privacy, and adapter contract regressions."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import httpx

FIXTURE = tempfile.TemporaryDirectory(prefix="emoi-tests-")
os.environ.update(RELAY_SECRET="test-owner-secret-only", RELAY_DB=FIXTURE.name + "/relay.db",
                  RELAY_UPLOAD_DIR=FIXTURE.name + "/uploads", LOOP_CONFIG=FIXTURE.name + "/config.json",
                  LOOP_CACHE_DIR=FIXTURE.name + "/cache")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from fastapi.testclient import TestClient
from backend import app as relay
from backend.emoi import memory_context
from backend.workspace import whisper_context
import api_loop as loop
from emoi_anthropic import request_body


class BrainRouteTests(unittest.TestCase):
    def test_server_default_and_saved_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "brain_target"
            with patch.object(relay, "BRAIN_FILE", target), patch.dict(os.environ, {"RELAY_DEFAULT_BRAIN": "loop"}):
                self.assertEqual(relay.brain_target(), "loop")
                target.write_text("desktop", encoding="utf-8")
                self.assertEqual(relay.brain_target(), "desktop")
                target.write_text("loop", encoding="utf-8")
                self.assertEqual(relay.brain_target(), "loop")


class ModelConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config = patch.object(loop, "LOOP_CONFIG", Path(self.temp.name) / "config.json")
        config.start()
        self.addCleanup(config.stop)
        self.client = TestClient(loop.app)
        self.addCleanup(self.client.close)
        self.root = "/loop/model-connections"
        self.first = {"name": "聚梦", "url": "https://relay.example.invalid/v1", "key": "private-example-key",
                      "model": "provider/first", "protocol": "openai"}

    def test_model_catalog_relay_requires_owner(self):
        path = "/app/loop/model-connections/models"
        with TestClient(relay.app) as client, patch.object(relay, "loop_json", return_value={"models": []}) as proxy:
            self.assertEqual(client.post(path, json=self.first).status_code, 401)
            proxy.assert_not_called()
            authenticated = client.post(path, json=self.first, headers={"Authorization": "Bearer test-owner-secret-only"})
            self.assertEqual(authenticated.json(), {"models": []})
            proxy.assert_called_once_with("/loop/model-connections/models", method="POST", body=self.first)

    def test_ob_dashboard_and_three_private_space_connections(self):
        dashboard = "https://ob.example.invalid/dashboard"
        self.assertEqual(self.client.post("/loop/contact-ob/dashboard", json={"url": dashboard}).json(),
                         {"dashboard_url": dashboard})
        for invalid in ("javascript:alert(1)", "https://ob.example.invalid/mcp", "https://ob.example.invalid/?token=secret"):
            self.assertEqual(self.client.post("/loop/contact-ob/dashboard", json={"url": invalid}).status_code, 422)
        connections = {}
        async def fake_restart(name, entry):
            marker = name.removeprefix("ob-space-")
            server = SimpleNamespace(
                name=name, status="online", public=lambda: {"name": name},
                tools=[SimpleNamespace(name="breath_search"), SimpleNamespace(name="chat_append")],
                call=AsyncMock(return_value=SimpleNamespace(isError=False, content=[SimpleNamespace(type="text", text=marker)])),
            )
            connections[name] = server
            return server

        with patch.object(loop.mcp_manager, "servers", connections), patch.object(loop.mcp_manager, "restart", side_effect=fake_restart):
            for number in ("one", "two", "three"):
                key = "ob-space-" + number
                response = self.client.post("/loop/contact-ob/space", json={
                    "space": key, "url": f"https://{number}.ob.example.invalid/mcp", "authorization": "test-token",
                })
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn("test-token", response.text)
                self.assertEqual(response.json()["dashboard_url"], dashboard)
            rows = self.client.get("/loop/contact-memory-servers").json()["servers"]
            self.assertEqual([row["name"] for row in rows], list(loop.CONTACT_OB_SPACES))
            self.assertTrue(all(row["search"] and row["archive"] for row in rows))
            self.assertEqual(loop.mcp_manager.openai_tools(), [])
            duplicate = self.client.post("/loop/contact-ob/space", json={
                "space": "ob-space-three", "url": "https://two.ob.example.invalid/mcp/",
            })
            self.assertEqual(duplicate.status_code, 422)
            for number in ("one", "two", "three"):
                self.assertEqual(asyncio.run(loop.contact_ob("ob-space-" + number, "breath_search", {"query":"test"})), number)
            archive = self.client.post("/loop/contact-archive", json={
                "server":"ob-space-three", "conversation_id":"fixture", "messages":[{"text":"one"},{"text":"two"}],
            })
            self.assertTrue(archive.json()["ok"])
            self.assertEqual(connections["ob-space-three"].call.await_args.args[0], "chat_append")
            self.assertEqual(connections["ob-space-one"].call.await_count, 1)
            self.assertEqual(connections["ob-space-two"].call.await_count, 1)

    def test_ob_space_relay_requires_owner(self):
        route = "/app/loop/contact-ob/space"
        fixture = {"space":"ob-space-three","url":"https://third.example.invalid/mcp"}
        with TestClient(relay.app) as client, patch.object(relay, "loop_json", return_value={"servers":[]}) as proxy:
            self.assertEqual(client.post(route, json=fixture).status_code, 401)
            proxy.assert_not_called()
            result = client.post(route, json=fixture, headers={"Authorization":"Bearer test-owner-secret-only"})
            self.assertEqual(result.status_code, 200)
            proxy.assert_called_once_with("/loop/contact-ob/space", method="POST", body=fixture)

    def test_manage_named_connections_and_route_replies(self):
        saved = self.client.post(self.root, json=self.first)
        self.assertEqual(saved.status_code, 200, saved.text)
        first, = saved.json()["connections"]
        self.assertTrue(first["key_set"])
        self.assertNotIn(self.first["key"], saved.text)
        second = {**self.first, "name": "备用", "key": "other-key", "model": "provider/second"}
        rows = self.client.post(self.root, json=second).json()["connections"]
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])
        update = {**self.first, "id": first["id"], "name": "新名字", "key": ""}
        self.assertEqual(self.client.post(self.root, json=update).json()["connections"][0]["id"], first["id"])
        self.assertEqual(self.client.post(self.root, json={**update, "url":"https://other.example.invalid/v1"}).status_code, 422)

        message = {"contact_id": "contact-one", "name": "测试", "history": [{"author": "human", "text": "你好"}]}
        with patch.object(loop, "complete_chat", return_value={"text": "reply"}) as send:
            for row, key in zip(rows, (self.first["key"], second["key"])):
                result = self.client.post("/loop/contact-reply", json={**message, "route": row["id"]})
                self.assertEqual(result.json(), {"text": "reply"})
                self.assertEqual(send.await_args.args[0]["model"], row["model"])
                self.assertEqual(send.await_args.args[0]["key"], key)
            self.assertEqual(self.client.delete(self.root + "/" + first["id"]).status_code, 200)
            self.assertEqual(self.client.post("/loop/contact-reply", json={**message, "route": first["id"]}).status_code, 404)
            self.assertEqual(send.await_count, 2)

    def test_fetch_models_uses_saved_key_only_for_matching_address(self):
        first, = self.client.post(self.root, json=self.first).json()["connections"]
        payload = {**self.first, "id": first["id"], "key": ""}
        real_client = httpx.AsyncClient
        requests = []

        def catalog(request):
            requests.append(request)
            return httpx.Response(200, json={"data": [{"id": "second"}, {"id": "first"}, {"id": "first"}, {}]})

        with patch.object(loop.httpx, "AsyncClient", side_effect=lambda **kwargs:
                          real_client(transport=httpx.MockTransport(catalog), **kwargs)):
            result = self.client.post(self.root + "/models", json=payload)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual([row["id"] for row in result.json()["models"]], ["first", "second"])
            self.assertEqual(str(requests[0].url), self.first["url"] + "/models")
            self.assertEqual(requests[0].headers["Authorization"], "Bearer " + self.first["key"])
            changed = self.client.post(self.root + "/models", json={**payload, "url":"https://other.example.invalid/v1"})
            self.assertEqual(changed.status_code, 422)
            self.assertEqual(len(requests), 1)

    def test_anthropic_model_catalog_uses_service_cursor(self):
        real_client = httpx.AsyncClient
        requests = []

        def catalog(request):
            requests.append(request)
            if request.url.params.get("after_id") == "provider/first":
                return httpx.Response(200, json={"data": [{"id": "provider/second"}], "has_more": False})
            return httpx.Response(200, json={
                "data": [{"id": "provider/first", "display_name": "First"}],
                "has_more": True, "last_id": "provider/first",
            })

        payload = {**self.first, "url": "https://claude.example.invalid", "protocol": "anthropic"}
        with patch.object(loop.httpx, "AsyncClient", side_effect=lambda **kwargs:
                          real_client(transport=httpx.MockTransport(catalog), **kwargs)):
            result = self.client.post(self.root + "/models", json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["models"], [
            {"id": "provider/first", "name": "First"},
            {"id": "provider/second", "name": "provider/second"},
        ])
        self.assertEqual(requests[0].url.path, "/v1/models")
        self.assertEqual(requests[0].headers["x-api-key"], payload["key"])

    def test_contact_worldbook_matches_recent_messages_and_parses_media_intent(self):
        loop.save_config({"agents": {"gpt": self.first}})
        payload = {"route":"gpt", "contact_id":"contact-one", "name":"测试",
                   "profile":{"instructions":"用短句", "worldbook":"雨,雪\n关键词条目\n\n*\n常驻条目\n\n花\n无关条目",
                              "voice_connection":"test-voice"},
                   "history":[{"author":"human", "text":"外面下雨了"}]}
        with patch.object(loop, "complete_chat", return_value={"text":"[voice]\n我听到啦"}) as send:
            result = self.client.post("/loop/contact-reply", json=payload)
        self.assertEqual(result.json(), {"text":"我听到啦", "voice_reply":True})
        prompt = send.await_args.args[1][0]["content"]
        self.assertIn("用短句", prompt)
        self.assertIn("关键词条目", prompt)
        self.assertIn("常驻条目", prompt)
        self.assertNotIn("无关条目", prompt)

    def test_contact_subscription_does_not_change_legacy_gpt_configuration(self):
        loop.save_config({"agents": {"gpt": {**self.first, "connection_mode": "api", "subscription_model": "old-plan"}}})
        self.assertEqual(self.client.get(self.root).json()["subscription_model"], "old-plan")
        self.assertEqual(self.client.post(self.root + "/subscription", json={"model": "new-plan"}).status_code, 200)
        message = {"contact_id": "contact-one", "name": "测试", "history": [{"author": "human", "text": "你好"}]}
        with patch.object(loop, "plan_chat", return_value={"text": "plan reply"}) as plan, patch.object(
            loop, "complete_chat", return_value={"text":"API reply"}
        ) as api:
            self.assertEqual(self.client.post("/loop/contact-reply", json={**message, "route":"chatgpt-plan"}).json(),
                             {"text": "plan reply"})
            self.assertEqual(plan.await_args.args[0], {"model": "new-plan"})
            self.assertEqual(self.client.post("/loop/contact-reply", json={**message, "route":"gpt"}).json(),
                             {"text": "API reply"})
            self.assertEqual(api.await_args.args[0]["model"], self.first["model"])
        self.assertEqual(loop.load_config()["agents"]["gpt"]["subscription_model"], "old-plan")


class OwnerDataTests(unittest.TestCase):
    def setUp(self):
        relay.init_db()
        relay.emoi_runtime["init"]()
        relay.workspace_runtime["init"]()
        relay.checklist_runtime["init"]()
        relay.speech_runtime["init"]()
        with relay.db() as c:
            for table in ("messages", "emoi_runs", "emoi_memories", "emoi_memory_revisions", "emoi_imports", "emoi_workspace", "emoi_checklist_alarms", "emoi_speech"):
                c.execute("DELETE FROM " + table)
        self.context = TestClient(relay.app)
        self.client = self.context.__enter__()
        self.client.headers["Authorization"] = "Bearer test-owner-secret-only"

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def memory(self, scope, content=None):
        response = self.client.post("/emoi/memories", json={"scope": scope, "title": scope, "content": content or (scope + "_PRIVATE_MARKER")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["memory"]

    def test_auth_guards_private_reads_and_writes(self):
        for path in ("/emoi/rooms", "/emoi/export", "/emoi/memories", "/emoi/rooms/gpt/messages"):
            self.assertEqual(self.client.get(path, headers={"Authorization": "Bearer wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/emoi/import", json={}, headers={"Authorization": "Bearer wrong"}).status_code, 401)

    def test_memory_projection_obeys_private_and_group_scopes(self):
        for scope in ("shared", "gpt", "claude", "group"):
            self.memory(scope)
        for agent in ("gpt", "claude"):
            private = memory_context(relay.DB_PATH, "emoi-" + agent, agent, "")
            self.assertIn(agent + "_PRIVATE_MARKER", private)
            self.assertIn("shared_PRIVATE_MARKER", private)
            other = "claude" if agent == "gpt" else "gpt"
            self.assertNotIn(other + "_PRIVATE_MARKER", private)
            self.assertNotIn("group_PRIVATE_MARKER", private)
            group = memory_context(relay.DB_PATH, "emoi-group", agent, "")
            self.assertIn("group_PRIVATE_MARKER", group)
            self.assertNotIn("gpt_PRIVATE_MARKER", group)
            self.assertNotIn("claude_PRIVATE_MARKER", group)
        self.assertEqual(memory_context(relay.DB_PATH, "emoi-claude", "gpt", ""), "")

    def test_stale_memory_edit_conflicts_and_revision_survives(self):
        m = self.memory("gpt")
        body = {**m, "content": "corrected", "version": 1}
        self.assertEqual(self.client.patch("/emoi/memories/" + m["id"], json=body).status_code, 200)
        self.assertEqual(self.client.patch("/emoi/memories/" + m["id"], json={**body, "content": "stale"}).status_code, 409)
        self.assertEqual(self.client.get("/emoi/memories").json()["memories"][0]["content"], "corrected")
        with relay.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM emoi_memory_revisions").fetchone()[0], 1)

    def test_sql_pagination_is_room_scoped_beyond_latest_global_hundred(self):
        ids = []
        for i in range(65):
            ids.append(relay.save_message("in", "user", str(i), {"api_session": "emoi-gpt"})["id"])
        for i in range(140):
            relay.save_message("in", "user", "other", {"api_session": "emoi-claude"})
        first = self.client.get("/emoi/rooms/gpt/messages").json()
        self.assertEqual([m["id"] for m in first["messages"]], ids[-40:])
        older = self.client.get("/emoi/rooms/gpt/messages", params={"before": first["messages"][0]["id"]}).json()
        self.assertEqual([m["id"] for m in older["messages"]], ids[:25])
        self.assertFalse(older["has_more"])

    def test_import_deduplicates_without_triggering_generation(self):
        body = {"format": "emoi-v03", "data": {"messages": {"gpt": [{"role": "user", "text": "old record"}]}, "memories": [{"scope": "shared", "title": "demo", "content": "not real", "demo": True}]}}
        r = self.client.post("/emoi/import", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["messages"], 1)
        self.assertTrue(self.client.post("/emoi/import", json=body).json()["duplicate"])
        with relay.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM emoi_runs").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM emoi_memories").fetchone()[0], 0)

    def test_bad_import_fails_atomically(self):
        for body in ({"format": "emoi-v04", "data": []}, {"format": "emoi-v04", "messages": [7]}, {"format": "emoi-v04", "messages": [{"meta": []}]}):
            self.assertEqual(self.client.post("/emoi/import", json=body).status_code, 422)
        with relay.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    def test_backup_import_keeps_attachment_index_and_remaps_memory_source(self):
        original = relay.save_message("in", "user", "source", {"api_session": "emoi-gpt", "attachments": [{"url": "/relay/uploads/note.txt", "name": "note.txt", "mime": "text/plain", "size": 4}]})
        self.client.post("/emoi/memories", json={"scope": "gpt", "title": "source", "content": "saved", "source_message_id": original["id"]})
        backup = self.client.get("/emoi/export").json()
        self.assertEqual(self.client.post("/emoi/import", json=backup).status_code, 200)
        messages = self.client.get("/emoi/rooms/gpt/messages").json()["messages"]
        imported = next(m for m in messages if m["meta"].get("imported"))
        self.assertEqual(imported["meta"]["attachments"][0]["name"], "note.txt")
        sources = [m["source_message_id"] for m in self.client.get("/emoi/memories").json()["memories"]]
        self.assertIn(imported["id"], sources)

    def test_send_nonce_survives_retry_and_cancel_blocks_late_output(self):
        async def blocked_post(*args, **kwargs):
            await asyncio.Event().wait()
        with patch("backend.emoi.httpx.AsyncClient.post", blocked_post):
            body = {"text": "hello", "nonce": "unique-test-nonce-0001"}
            first = self.client.post("/emoi/rooms/gpt/send", json=body)
            self.assertEqual(first.status_code, 200, first.text)
            duplicate = self.client.post("/emoi/rooms/gpt/send", json=body).json()
            self.assertTrue(duplicate["duplicate"])
            self.assertEqual(duplicate["id"], first.json()["id"])
            self.assertEqual(self.client.post("/emoi/rooms/gpt/send", json={**body, "nonce": "another-test-nonce"}).status_code, 409)
            rid = first.json()["run"]["id"]
            self.assertEqual(self.client.post("/emoi/runs/" + rid + "/stop").json()["run"]["state"], "cancelled")
            self.assertEqual(self.client.post("/channel/out", json={"type": "reply", "run_id": rid, "agent_id": "gpt", "text": "late"}).status_code, 409)
            self.assertEqual(len(self.client.get("/emoi/rooms/gpt/messages").json()["messages"]), 1)

    def test_model_history_orders_user_before_first_group_reply(self):
        self.memory("gpt", "must not enter group")
        self.memory("shared", "allowed_shared")
        relay.save_message("in", "user", "PRIVATE_CHAT_MARKER", {"api_session": "emoi-gpt"})
        current = relay.save_message("in", "user", "CURRENT_GROUP_USER", {"api_session": "emoi-group"})
        relay.save_message("out", "reply", "FIRST_GROUP_REPLY", {"api_session": "emoi-group", "agent_id": "gpt", "run_id": "group-fixture"})
        async def build():
            a = loop.CURRENT_AGENT.set("claude")
            r = loop.CURRENT_RUN.set("group-fixture")
            try:
                return await loop.build_messages("CURRENT_GROUP_USER", [], before_id=current["id"], session_id="emoi-group")
            finally:
                loop.CURRENT_AGENT.reset(a)
                loop.CURRENT_RUN.reset(r)
                from latent_process import close_native
                await close_native()
        msgs, _ = asyncio.run(build())
        text = json.dumps(msgs)
        self.assertLess(text.index("CURRENT_GROUP_USER"), text.index("FIRST_GROUP_REPLY"))
        self.assertNotIn("PRIVATE_CHAT_MARKER", text)
        self.assertNotIn("must not enter group", text)
        self.assertIn("allowed_shared", text)

    def test_configs_keep_keys_server_side_and_agents_independent(self):
        with TestClient(loop.app) as client:
            for name in ("gpt", "claude"):
                r = client.post("/loop/agents", json={"agent": name, "url": "https://example.invalid/v1", "model": "model-" + name, "key": "fixture-key-" + name, "protocol": "openai"})
                self.assertEqual(r.status_code, 200, r.text)
            public = client.get("/loop/agents").json()
            self.assertNotIn("fixture-key", json.dumps(public))
            self.assertTrue(public["agents"]["claude"]["key_set"])
            for name in ("gpt", "claude"):
                t = loop.CURRENT_AGENT.set(name)
                try:
                    self.assertEqual(loop.main_chain()[0]["key"], "fixture-key-" + name)
                finally:
                    loop.CURRENT_AGENT.reset(t)

    def test_cancel_gate_prevents_subsequent_tool_execution(self):
        token = loop.CURRENT_RUN.set("missing-run")
        try:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(loop.Turn("emoi-gpt", dry=False).run_tool("attach_file", '{}'))
        finally:
            loop.CURRENT_RUN.reset(token)

    def test_emoi_file_tool_defaults_to_owner_upload_and_cache_roots(self):
        token = loop.CURRENT_AGENT.set("gpt")
        try:
            self.assertFalse(loop.attach_allowed(Path("/proc/self/environ")))
            self.assertFalse(loop.attach_allowed(Path(relay.DB_PATH)))
            self.assertTrue(loop.attach_allowed(Path(relay.UPLOAD_DIR) / "note.txt"))
        finally:
            loop.CURRENT_AGENT.reset(token)

    def record(self, kind="todo", scope="gpt", **kwargs):
        r = self.client.post("/emoi/workspace", json={"kind": kind, "scope": scope, "title": "entry", "content": scope + "_WORKSPACE", "data": {}, **kwargs})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["item"]

    def active_run(self, room="gpt"):
        with relay.db() as c:
            c.execute("INSERT INTO emoi_runs VALUES(?,?,?,?,?,?,?,?,?)", ("fixture-run", room, "fixture-nonce", 1, '["gpt"]', "running", "", "2026-10-23", "2026-10-23"))
        return {"agent_id": "gpt", "room": "emoi-" + room, "run_id": "fixture-run"}

    def test_workspace_versions_book_scope_and_deletion_cascade(self):
        book = self.record("book", "gpt", content="A paragraph")
        ann = self.record("annotation", "gpt", data={"book_id": book["id"], "quote": "paragraph"})
        moved = self.client.patch("/emoi/workspace/" + book["id"], json={**book, "scope": "group"})
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(self.client.patch("/emoi/workspace/" + book["id"], json=book).status_code, 409)
        rows = self.client.get("/emoi/workspace").json()["items"]
        self.assertEqual(next(r for r in rows if r["id"] == ann["id"])["scope"], "group")
        self.assertEqual(self.client.delete("/emoi/workspace/" + book["id"], params={"version": 1}).status_code, 409)
        self.assertEqual(self.client.delete("/emoi/workspace/" + book["id"], params={"version": 2}).status_code, 200)
        self.assertEqual(self.client.get("/emoi/workspace").json()["items"], [])

    def test_timed_checklist_rollover_delivery_and_retry(self):
        from datetime import datetime, timezone, timedelta
        clock = int(datetime.now(timezone.utc).timestamp() * 1000)
        today = datetime.fromtimestamp(clock / 1000, timezone.utc).date()
        yesterday = (today - timedelta(days=1)).isoformat()
        daily = self.record("todo", data={"owner":"user", "done":True, "cycle":"daily", "timezone":"UTC", "cycle_day":yesterday})
        once = self.record("todo", data={"owner":"user", "done":False, "cycle":"once", "timezone":"UTC", "cycle_day":yesterday})
        alarm = self.record("todo", data={"owner":"user", "done":False, "cycle":"timed", "timezone":"UTC", "cycle_day":yesterday, "trigger_at":clock+60_000, "alarm_room":"gpt"})
        self.assertEqual(self.client.post('/emoi/workspace',json={'kind':'todo','scope':'gpt','title':'wrong room','data':{'cycle':'timed','in_minutes':1,'alarm_room':'claude'}}).status_code,422)
        relative = self.record("todo", data={"owner":"user", "cycle":"timed", "timezone":"UTC", "in_minutes":30, "alarm_room":"gpt"})
        self.assertTrue(clock+29*60_000 < relative['data']['trigger_at'] < clock+31*60_000)
        self.assertNotIn('in_minutes', relative['data'])
        self.assertEqual(self.client.get('/emoi/checklist/alarms',headers={'Authorization':'Bearer wrong'}).status_code,401)
        called = []
        async def model(scope, prompt):
            called.append((scope,prompt))
            return {'text':json.dumps({'action':'say','text':'该看看这项清单了。'}),'usage':{'total_tokens':9}}
        asyncio.run(relay.checklist_runtime['tick'](clock_ms=clock+61_000,generate_fn=model))
        rows = {r['id']:r for r in self.client.get('/emoi/workspace').json()['items']}
        self.assertNotIn(once['id'],rows)
        self.assertFalse(rows[daily['id']]['data']['done'])
        self.assertIn(alarm['id'],rows)
        states = {r['todo_id']:r for r in self.client.get('/emoi/checklist/alarms').json()['items']}
        self.assertEqual(states[alarm['id']]['state'],'delivered')
        self.assertEqual(called[0][0],'gpt')
        self.assertIn(alarm['title'],called[0][1])
        with relay.db() as db:
            messages = db.execute("SELECT text,meta FROM messages WHERE json_extract(meta,'$.checklist_alarm')=?",(alarm['id'],)).fetchall()
        self.assertEqual(len(messages),1)
        self.assertEqual(messages[0]['text'],'该看看这项清单了。')
        asyncio.run(relay.checklist_runtime['tick'](clock_ms=clock+62_000,generate_fn=model))
        self.assertEqual(len(called),1)
        retry = self.record("todo", data={"owner":"user", "done":False, "cycle":"timed", "timezone":"UTC", "cycle_day":today.isoformat(), "trigger_at":clock+70_000, "alarm_room":"gpt"})
        async def broken(scope,prompt):
            raise RuntimeError('fixture model unavailable')
        asyncio.run(relay.checklist_runtime['tick'](clock_ms=clock+71_000,generate_fn=broken))
        states = {r['todo_id']:r for r in self.client.get('/emoi/checklist/alarms').json()['items']}
        self.assertEqual(states[retry['id']]['state'],'pending')
        asyncio.run(relay.checklist_runtime['tick'](clock_ms=clock+72_000,generate_fn=model))
        states = {r['todo_id']:r for r in self.client.get('/emoi/checklist/alarms').json()['items']}
        self.assertEqual(states[retry['id']]['state'],'delivered')
        self.assertEqual(states[retry['id']]['attempts'],2)
        cancelled = self.record("todo", data={"owner":"user", "done":False, "cycle":"timed", "timezone":"UTC", "cycle_day":today.isoformat(), "trigger_at":clock+80_000, "alarm_room":"gpt"})
        async def completed_during_generation(scope,prompt):
            row = next(r for r in self.client.get('/emoi/workspace').json()['items'] if r['id']==cancelled['id'])
            self.assertEqual(self.client.patch('/emoi/workspace/'+row['id'],json={**row,'data':{**row['data'],'done':True}}).status_code,200)
            return {'text':json.dumps({'action':'say','text':'Should never appear'})}
        asyncio.run(relay.checklist_runtime['tick'](clock_ms=clock+81_000,generate_fn=completed_during_generation))
        states = {r['todo_id']:r for r in self.client.get('/emoi/checklist/alarms').json()['items']}
        self.assertEqual(states[cancelled['id']]['state'],'cancelled')
        with relay.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM messages WHERE json_extract(meta,'$.checklist_alarm')=?",(cancelled['id'],)).fetchone()[0],0)

    def test_reading_anchors_replies_and_assistant_ownership(self):
        book = self.record("book", "gpt", content="First paragraph\n\nSecond paragraph", data={"progress": 0, "status": "reading"})
        data = {"book_id": book["id"], "quote": "Second", "para": 1, "start": 0, "end": 6, "color": "blue", "replies": []}
        self.assertEqual(self.client.post("/emoi/workspace", json={"kind": "annotation", "scope": "gpt", "title": "bad", "data": {**data, "start": 1}}).status_code, 422)
        note = self.record("annotation", "gpt", title="Second", content="My thought", data=data)
        ctx = self.active_run()
        ai_note = self.client.post("/emoi/assistant/workspace", json={**ctx, "action": "create", "kind": "annotation", "scope": "gpt", "title": "First", "content": "Another perspective", "data": {"book_id": book["id"], "quote": "First", "para": 0, "start": 0, "end": 5}})
        self.assertEqual(ai_note.status_code, 200, ai_note.text)
        self.assertEqual(ai_note.json()["item"]["author"], "gpt")
        def ai(**body):
            return self.client.post("/emoi/assistant/workspace", json={**ctx, **body, "action": "update", "id": note["id"], "version": note["version"]})
        reply = {"author": "gpt", "text": "I see the same passage differently", "at": "2026-10-25T12:00:00Z"}
        changed = ai(kind="annotation", scope="gpt", title=note["title"], content=note["content"], data={**data, "replies": [reply]})
        self.assertEqual(changed.status_code, 200, changed.text)
        updated = changed.json()["item"]
        self.assertEqual(updated["data"]["replies"], [reply])
        self.assertEqual(self.client.patch("/emoi/workspace/" + note["id"], json={**updated, "data": {**data, "replies": []}}).status_code, 422)
        self.assertEqual(self.client.patch("/emoi/workspace/" + note["id"], json={**updated, "data": {**data, "replies": [reply, {"author": "gpt", "text": "impersonation", "at": "now"}]}}).status_code, 422)
        owner_reply = {"author": "user", "text": "Thank you", "at": "2026-10-25T12:01:00Z"}
        self.assertEqual(self.client.patch("/emoi/workspace/" + note["id"], json={**updated, "data": {**data, "replies": [reply, owner_reply]}}).status_code, 200)
        self.assertEqual(ai(kind="annotation", scope="gpt", title="rewritten", content=note["content"], data={**data, "replies": [reply, owner_reply]}).status_code, 403)

    def test_workspace_assistant_scope_and_cancel_gate(self):
        for scope in ("shared", "gpt", "claude", "group"):
            self.record(scope=scope)
        ctx = self.active_run("group")
        def call(**body):
            return self.client.post("/emoi/assistant/workspace", json={**ctx, **body})
        r = call(action="list", kind="todo")
        self.assertEqual({i["scope"] for i in r.json()["items"]}, {"shared", "group"})
        private = next(i for i in self.client.get("/emoi/workspace").json()["items"] if i["scope"] == "gpt")
        self.assertEqual(call(**{**private, "action": "update", "scope": "group"}).status_code, 403)
        self.assertEqual(call(action="create", kind="todo", scope="claude", title="bad").status_code, 403)
        created = call(action="create", kind="todo", scope="group", title="saved", data={"owner": "gpt"})
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["item"]["author"], "gpt")
        with relay.db() as c:
            c.execute("UPDATE emoi_runs SET state='cancelled'")
        self.assertEqual(call(action="create", kind="todo", scope="group", title="late").status_code, 409)

    def test_whispers_are_only_projected_into_their_room(self):
        for scope in ("shared", "gpt", "claude", "group"):
            self.record("whisper", scope)
        private = whisper_context(relay.DB_PATH, "emoi-gpt", "gpt")
        group = whisper_context(relay.DB_PATH, "emoi-group", "gpt")
        self.assertIn("gpt_WORKSPACE", private)
        self.assertNotIn("claude_WORKSPACE", private)
        self.assertNotIn("group_WORKSPACE", private)
        self.assertIn("group_WORKSPACE", group)
        self.assertIn("shared_WORKSPACE", group)
        self.assertNotIn("gpt_WORKSPACE", group)
        self.assertEqual(whisper_context(relay.DB_PATH, "emoi-claude", "gpt"), "")

    def test_workspace_backup_remaps_book_and_annotation_and_rolls_back_bad_import(self):
        book = self.record("book", content="READING_MARKER")
        self.record("annotation", data={"book_id": book["id"], "quote": "READING"})
        backup = self.client.get("/emoi/export").json()
        r = self.client.post("/emoi/import", json=backup)
        self.assertEqual(r.status_code, 200, r.text)
        rows = self.client.get("/emoi/workspace").json()["items"]
        imported_book = next(x for x in rows if x["kind"] == "book" and x["author"] == "imported")
        imported_ann = next(x for x in rows if x["kind"] == "annotation" and x["author"] == "imported")
        self.assertNotEqual(imported_book["id"], book["id"])
        self.assertEqual(imported_ann["data"]["book_id"], imported_book["id"])
        self.assertTrue(self.client.post("/emoi/import", json=backup).json()["duplicate"])
        bad = {"format": "emoi-v04", "messages": [{"text": "ROLLBACK", "from": "human", "meta": {"api_session": "emoi-gpt"}}], "workspace": [{"id": "bad-ann", "kind": "annotation", "scope": "gpt", "title": "bad", "content": "", "data": {"book_id": "missing", "quote": "q"}}]}
        self.assertEqual(self.client.post("/emoi/import", json=bad).status_code, 422)
        with relay.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM messages WHERE text='ROLLBACK'").fetchone()[0], 0)

    def test_workspace_auth_validation_and_old_room_search(self):
        self.assertEqual(self.client.get("/emoi/workspace", headers={"Authorization": "Bearer wrong"}).status_code, 401)
        self.assertEqual(self.client.patch("/emoi/workspace/x", json=[]).status_code, 422)
        self.assertEqual(self.client.post("/emoi/assistant/workspace", json=[]).status_code, 422)
        self.assertEqual(self.client.post("/emoi/workspace", json={"kind": "event", "scope": "gpt", "title": "x", "data": {"date": "2026-02-30"}}).status_code, 422)
        old = relay.save_message("in", "user", "old SEARCH_MARKER", {"api_session": "emoi-gpt"})
        for i in range(110):
            relay.save_message("in", "user", "SEARCH_MARKER", {"api_session": "emoi-claude"})
        r = self.client.get("/emoi/rooms/gpt/search", params={"q": "search_marker"})
        self.assertEqual([x["id"] for x in r.json()["messages"]], [old["id"]])


class AnthropicContractTests(unittest.TestCase):
    def test_system_image_and_tool_result_conversion(self):
        messages = [{"role": "system", "content": "persona"}, {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}}]}, {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "function": {"name": "lookup", "arguments": '{"q":"x"}'}}]}, {"role": "tool", "tool_call_id": "c1", "content": "result"}]
        body = request_body({"model": "claude-fixture"}, messages, None, 100, .7, True)
        self.assertEqual(body["system"], "persona")
        self.assertEqual(body["messages"][0]["content"][0]["type"], "image")
        self.assertEqual(body["messages"][1]["content"][0]["input"], {"q": "x"})
        self.assertEqual(body["messages"][2]["content"][0]["tool_use_id"], "c1")


if __name__ == "__main__":
    unittest.main()
