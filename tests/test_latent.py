"""Real pinned Latent engine integration; no model or embedding API is called."""
import asyncio
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_lune as fixtures
from backend.lune_memory import LatentEngine, MemoryStore
from backend import app as relay


class LatentTests(unittest.TestCase):
    setUp_base = fixtures.OwnerDataTests.setUp
    tearDown = fixtures.OwnerDataTests.tearDown
    memory = fixtures.OwnerDataTests.memory

    def setUp(self):
        self.setUp_base()
        self.store = MemoryStore(relay.DB_PATH)
        self.engine = LatentEngine(relay.DB_PATH)
        with self.store.db() as c:
            for table in ("lune_memory_details", "lune_memory_loops", "lune_memory_sessions"):
                c.execute("DELETE FROM " + table)
            c.execute("UPDATE lune_memory_settings SET value=?,version=1", ('{"enabled":true,"auto_recall":true,"model_writes":true}',))

    def enabled(self):
        if not self.engine.installation():
            self.skipTest("Set LUNE_LATENT_SOURCE to the checkout verified by scripts/setup_latent.py")

    def search(self, query, view="gpt"):
        return self.client.post("/lune/memory/search", json={"view": view, "query": query})

    def edit(self, m, action="edit", content="新内容", **kw):
        return self.client.patch("/lune/memories/" + m["id"], json={**m, "content": content, "change_type": action, **kw})

    def active(self, text="记住：我喜欢雨夜读书。", room="gpt", agent="gpt"):
        msg = relay.save_message("in", "user", text, {"api_session": "lune-" + room})
        with self.store.db() as c:
            c.execute("INSERT INTO lune_runs VALUES(?,?,?,?,?,?,?,?,?)", ("memory-run", room, "memory-nonce", msg["id"], json.dumps([agent]), "running", "", "2026-10-24", "2026-10-24"))
        return {"agent_id": agent, "room": "lune-" + room, "run_id": "memory-run"}

    def test_owner_routes_require_auth_and_settings_version(self):
        for path in ("/lune/memory/status", "/lune/memory/check", "/lune/memory/search", "/lune/memory/loops", "/lune/assistant/memory"):
            response = self.client.request("GET" if path.endswith("status") else "POST", path, json={}, headers={"Authorization": "Bearer wrong"})
            self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.client.patch("/lune/memory/settings", json={"version": 1, "auto_recall": False}).status_code, 200)
        self.assertEqual(self.client.patch("/lune/memory/settings", json={"version": 1, "enabled": False}).status_code, 409)

    def test_real_engine_scope_filtering_happens_before_worker(self):
        self.enabled()
        for scope in ("shared", "gpt", "claude", "group"):
            self.memory(scope, "雨夜读书_" + scope)
        for view in ("gpt", "claude", "group"):
            response = self.search("雨夜读书", view)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual({r["scope"] for r in response.json()["matches"]}, {"shared", view})
        snapshot = self.engine.snapshot("group")
        self.assertNotIn("雨夜读书_gpt", json.dumps(snapshot, ensure_ascii=False))
        self.assertNotIn("雨夜读书_claude", json.dumps(snapshot, ensure_ascii=False))

    def test_real_engine_change_history_and_correction(self):
        self.enabled()
        first = self.memory("gpt", "住在云港，喜欢云港的海风。")
        second = self.edit(first, "change", "搬到了临川南坡。", current_state="现在住在临川南坡").json()["memory"]
        self.assertEqual(second["supersedes"], first["id"])
        self.assertNotIn(first["id"], [r["id"] for r in self.search("云港").json()["matches"]])
        self.assertIn(first["id"], [r["id"] for r in self.search("以前云港").json()["matches"]])
        corrected = self.edit(second, "correct", "实际住在临川北坡。", reason="南坡是误记")
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertNotIn(second["id"], [r["id"] for r in self.search("以前临川南坡").json()["matches"]])
        self.assertEqual(len(self.client.get("/lune/memories").json()["memories"]), 1)

    def test_real_engine_owner_edit_delete_and_range_move_no_stale_copy(self):
        self.enabled()
        m = self.memory("shared", "喜欢银色手链。"); original = m["id"]
        m = self.edit(m, content="喜欢蓝色围巾。", scope="gpt").json()["memory"]
        self.assertNotIn(original, [r["id"] for r in self.search("蓝色围巾", "claude").json()["matches"]])
        self.assertIn(original, [r["id"] for r in self.search("蓝色围巾").json()["matches"]])
        self.assertEqual(self.client.delete("/lune/memories/" + original, params={"version": m["version"]}).status_code, 200)
        self.assertNotIn(original, [r["id"] for r in self.search("蓝色围巾").json()["matches"]])

    def test_delete_current_fact_removes_linked_history_from_recall(self):
        m = self.memory("gpt", "旧住址")
        m = self.edit(m, "change", "新住址").json()["memory"]
        result = self.client.delete("/lune/memories/" + m["id"], params={"version": m["version"]})
        self.assertEqual(result.json()["deleted_records"], 2)
        self.assertEqual(self.engine.snapshot("gpt"), [])

    def test_worker_does_not_receive_application_keys_or_call_network(self):
        self.enabled()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "private-fixture", "MEMORY_EMBED_PROVIDER": "cloud", "PYTHONPATH": "/wrong"}):
            result = self.client.post("/lune/memory/check")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["ok"])

    def test_real_no_hit_and_unavailable_are_distinct(self):
        self.enabled()
        self.memory("gpt", "喜欢雨夜读书。")
        absent = self.search("ZXQVV998877")
        self.assertEqual(absent.status_code, 200, absent.text)
        self.assertEqual(absent.json()["matches"], [])
        with patch.dict(os.environ, {"LUNE_LATENT_SOURCE": "/missing-latent"}):
            self.assertEqual(self.search("雨夜").status_code, 503)
            self.assertEqual(self.client.get("/lune/memory/status").json()["engine"], "basic")

    def test_model_write_requires_current_source_and_only_current_room(self):
        context = self.active()
        for quote in ("编造的事实", ""):
            self.assertEqual(self.client.post("/lune/assistant/memory", json={**context, "action": "remember", "quote": quote}).status_code, 422)
        result = self.client.post("/lune/assistant/memory", json={**context, "action": "remember", "quote": "我喜欢雨夜读书。", "scope": "shared"})
        self.assertEqual(result.status_code, 200, result.text)
        item = result.json()["memory"]
        self.assertEqual(item["scope"], "gpt")
        self.assertEqual(item["content"], "我喜欢雨夜读书。")
        foreign = self.memory("claude", "秘密")
        self.assertEqual(self.client.post("/lune/assistant/memory", json={**context, "action": "correct", "id": foreign["id"], "version": 1, "quote": "我喜欢雨夜读书。"}).status_code, 403)

    def test_model_cannot_write_without_explicit_request_or_after_cancel(self):
        context = self.active("我喜欢下雨。")
        self.assertEqual(self.client.post("/lune/assistant/memory", json={**context, "action": "remember", "quote": "我喜欢下雨。"}).status_code, 403)
        with self.store.db() as c:
            c.execute("UPDATE lune_runs SET state='cancelled'")
        self.assertEqual(self.client.post("/lune/assistant/memory", json={**context, "action": "remember", "quote": "我喜欢下雨。"}).status_code, 409)

    def test_unresolved_is_separate_versioned_and_scope_safe(self):
        context = self.active("记下未完事项：周五一起看展。")
        result = self.client.post("/lune/assistant/memory", json={**context, "action": "unresolved_open", "quote": "周五一起看展。"})
        self.assertEqual(result.status_code, 200, result.text)
        item = result.json()["item"]
        self.assertEqual(self.store.loops(["claude"]), [])
        self.assertEqual(self.client.post("/lune/memory/loops", json={**item, "status": "closed", "version": 0}).status_code, 409)
        self.assertEqual(self.client.post("/lune/memory/loops", json={**item, "status": "closed"}).status_code, 200)
        self.assertEqual(self.store.loops(), [])

    def test_request_only_context_and_persona_are_separate(self):
        self.enabled()
        self.memory("gpt", "周五一起看画展。")
        msg = relay.save_message("in", "user", "周五画展", {"api_session": "lune-gpt"})
        async def build():
            token = fixtures.loop.CURRENT_AGENT.set("gpt")
            try:
                return await fixtures.loop.build_messages("周五画展", [], before_id=msg["id"], session_id="lune-gpt")
            finally:
                fixtures.loop.CURRENT_AGENT.reset(token)
        messages, _ = asyncio.run(build())
        self.assertIn("周五一起看画展", json.dumps(messages, ensure_ascii=False))
        self.assertIn("记忆协议", messages[1]["content"])
        with self.store.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)

    def test_in_flight_owner_edit_invalidates_snapshot(self):
        m = self.memory("gpt", "旧词")
        async def changed(payload):
            self.store.save(("gpt", "gpt", "新词", None), {"version": 1}, m["id"])
            return {"matches": [], "text": "stale", "weights": {}}
        with patch.object(self.engine, "worker", changed):
            with self.assertRaisesRegex(RuntimeError, "memory_changed"):
                asyncio.run(self.engine.retrieve("gpt", "旧词"))

    def test_disable_auto_recall_still_allows_explicit_search(self):
        self.enabled()
        self.memory("gpt", "喜欢雨夜读书。")
        self.store.configure({"version": 1, "auto_recall": False})
        result = asyncio.run(self.engine.retrieve("gpt", "雨夜", operation="context"))
        self.assertEqual(result["matches"], [])
        self.assertTrue(self.search("雨夜").json()["matches"])

    def test_backup_preserves_changes_and_unresolved_with_remapped_ids(self):
        m = self.memory("gpt", "以前喜欢银手链")
        latest = self.edit(m, "change", "现在喜欢蓝围巾").json()["memory"]
        self.client.post("/lune/memory/loops", json={"scope": "gpt", "summary": "去看展"})
        backup = self.client.get("/lune/export").json()
        result = self.client.post("/lune/import", json=backup)
        self.assertEqual(result.status_code, 200, result.text)
        rows = self.store.list(True)
        imported = next(r for r in rows if r["author"] == "imported" and r["status"] == "current")
        self.assertNotEqual(imported["id"], latest["id"])
        old = next(r for r in rows if r["id"] == imported["supersedes"])
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(old["superseded_by"], imported["id"])
        self.assertEqual(len(self.store.loops()), 2)

    def test_basic_mode_also_excludes_retracted_or_superseded_facts(self):
        m = self.memory("gpt", "错的事实")
        self.edit(m, "correct", "正确事实")
        text = fixtures.memory_context(relay.DB_PATH, "lune-gpt", "gpt", "")
        self.assertNotIn("错的事实", text)
        self.assertIn("正确事实", text)

    def test_moving_fact_does_not_reveal_private_history(self):
        m = self.memory("gpt", "私人旧住址")
        m = self.edit(m, "change", "新公开资料").json()["memory"]
        result = self.edit(m, content="新公开资料", scope="shared")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIsNone(result.json()["memory"]["supersedes"])
        snapshot = self.engine.snapshot("claude")
        self.assertNotIn("私人旧住址", json.dumps(snapshot, ensure_ascii=False))
        backup = self.client.get("/lune/export").json()
        self.assertEqual(self.client.post("/lune/import", json=backup).status_code, 200)

    def test_bad_backup_does_not_partially_import(self):
        m = self.memory("gpt", "现有记录")
        backup = self.client.get("/lune/export").json()
        backup["memories"][0]["supersedes"] = m["id"]
        self.assertEqual(self.client.post("/lune/import", json=backup).status_code, 422)
        self.assertEqual(len(self.store.list()), 1)


if __name__ == "__main__":
    unittest.main()
