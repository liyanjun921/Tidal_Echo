"""Production Luné → original hidden Passive Recall → real local vectors."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_lune as fixtures
from backend import app as relay
from backend.lune_memory import LatentEngine, MemoryStore
from backend.latent_process import close_native


class NativePassiveTests(unittest.TestCase):
    setUp_base = fixtures.OwnerDataTests.setUp
    tearDown_base = fixtures.OwnerDataTests.tearDown

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="native-production-")
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"LUNE_PASSIVE_STATE_DIR": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.setUp_base()
        self.addCleanup(self.tearDown_base)
        self.engine = LatentEngine(relay.DB_PATH)
        self.store = MemoryStore(relay.DB_PATH)
        with self.store.db() as c:
            for table in ("lune_memory_details", "lune_memory_sessions", "lune_memory_loops"):
                c.execute("DELETE FROM " + table)
            c.execute("UPDATE lune_memory_settings SET value=?,version=1", ('{"enabled":true,"auto_recall":true,"model_writes":true}',))
        if not self.engine.passive_status()["assets_ready"]:
            self.skipTest("Install original Latent and run setup_latent.py --vectors; real local model required")

    def remember(self, content, scope="gpt", old=True):
        item = self.client.post("/lune/memories", json={"scope": scope, "title": "fixture", "content": content}).json()["memory"]
        if old:
            at = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
            with self.store.db() as c:
                c.execute("UPDATE lune_memories SET updated_at=?,created_at=? WHERE id=?", (at, at, item["id"]))
        return item

    def run_contexts(self, fn):
        async def run():
            try:
                return await fn()
            finally:
                await close_native()
        return asyncio.run(run())

    def test_hidden_entry_is_live_in_production_context_and_scoped(self):
        item = self.remember("她不喜欢太甜的饮料，常点无糖乌龙。")
        self.remember("她不喜欢太甜的饮料，常点无糖红茶。", "claude")
        async def run():
            result = await self.engine.context("lune-gpt", "gpt", "这杯喝着齁得慌，有没有清淡些的？", 10, "native-run")
            self.assertEqual(result["engine"], "latent", result)
            self.assertEqual(result["passive"]["entry"], "latent_passive_recall")
            self.assertTrue(result["passive"]["injected"], result)
            self.assertIn(item["id"], result["ids"])
            self.assertIn("无糖乌龙", result["passive_text"])
            self.assertNotIn("无糖红茶", result["passive_text"])
            return result
        self.run_contexts(run)

    def test_cooldown_duplicate_delivery_and_restart_persist(self):
        self.remember("她不喜欢太甜的饮料，常点无糖乌龙。")
        async def run():
            first = await self.engine.context("lune-gpt", "gpt", "我不想喝这么甜的饮料", 11, "first")
            retry = await self.engine.context("lune-gpt", "gpt", "我不想喝这么甜的饮料", 11, "first")
            self.assertTrue(first["passive"]["injected"], first)
            self.assertEqual(first["passive_text"], retry["passive_text"])
            await close_native()
            later = await self.engine.context("lune-gpt", "gpt", "我不想喝这么甜的饮料", 12, "later")
            self.assertEqual(later["passive"]["reason_codes"], ["fact_cooled"], later)
        self.run_contexts(run)

    def test_edit_delete_move_do_not_leave_native_fact_copy_visible(self):
        item = self.remember("她不喜欢太甜的饮料，常点无糖乌龙。", "shared")
        async def run():
            first = await self.engine.context("lune-claude", "claude", "我不想喝这么甜的饮料", 11, "first")
            self.assertTrue(first["passive"]["injected"], first)
            changed = self.client.patch("/lune/memories/" + item["id"], json={**item, "version": 1, "scope": "gpt", "content": "她现在很喜欢喝冰美式咖啡。"})
            self.assertEqual(changed.status_code, 200, changed.text)
            later = await self.engine.context("lune-claude", "claude", "冰美式咖啡", 12, "later")
            self.assertNotIn(item["id"], later["ids"])
            self.assertNotIn("冰美式", later["passive_text"])
            self.client.delete("/lune/memories/" + item["id"], params={"version": 2})
            deleted = await self.engine.context("lune-gpt", "gpt", "冰美式咖啡", 13, "deleted")
            self.assertNotIn(item["id"], deleted["ids"])
        self.run_contexts(run)

    def test_new_same_day_memory_and_low_information_stay_empty(self):
        self.remember("她不喜欢太甜的饮料，常点无糖乌龙。", old=False)
        async def run():
            same_day = await self.engine.context("lune-gpt", "gpt", "无糖乌龙", 11, "same-day")
            self.assertFalse(same_day["passive"]["injected"], same_day)
            filler = await self.engine.context("lune-gpt", "gpt", "嗯嗯", 12, "filler")
            self.assertEqual(filler["passive"]["reason_codes"], ["low_information"])
        self.run_contexts(run)

    def test_off_switch_no_native_injection_and_missing_assets_no_fake_fallback(self):
        self.remember("她不喜欢太甜的饮料，常点无糖乌龙。")
        async def run():
            self.store.configure({"version": 1, "auto_recall": False})
            off = await self.engine.context("lune-gpt", "gpt", "无糖乌龙", 11, "off")
            self.assertEqual(off["passive"]["status"], "disabled")
            self.assertFalse(off["passive_text"])
            self.store.configure({"version": 2, "auto_recall": True})
            with patch.dict(os.environ, {"LUNE_PASSIVE_MODEL_CACHE": "/missing-model-assets"}):
                failed = await self.engine.context("lune-gpt", "gpt", "无糖乌龙", 12, "missing")
            self.assertEqual(failed["passive"]["status"], "unavailable")
            self.assertNotIn("passive_text", failed)
        self.run_contexts(run)

    def test_production_request_contains_native_material_but_raw_history_does_not(self):
        item = self.remember("她不喜欢太甜的饮料，常点无糖乌龙。")
        msg = relay.save_message("in", "user", "我不想喝这么甜的饮料", {"api_session": "lune-gpt"})
        async def run():
            token = fixtures.loop.CURRENT_AGENT.set("gpt")
            try:
                messages, _ = await fixtures.loop.build_messages(msg["text"], [], before_id=msg["id"], session_id="lune-gpt")
                trace = fixtures.loop.CURRENT_MEMORY.get()
                self.assertEqual(trace["passive"]["entry"], "latent_passive_recall")
                self.assertTrue(trace["passive"]["injected"], trace)
                self.assertIn("〔历史证据〕", json.dumps(messages, ensure_ascii=False))
                self.assertNotIn("latent_passive_recall", [t["function"]["name"] for t in fixtures.loop.all_tools()])
                from lune_plan import response_body
                self.assertIn("〔历史证据〕", response_body("fixture", messages, None)["instructions"])
                from lune_anthropic import request_body
                self.assertIn("〔历史证据〕", json.dumps(request_body({"model": "fixture"}, messages, None, 1000, 0.7, True), ensure_ascii=False))
            finally:
                fixtures.loop.CURRENT_AGENT.reset(token)
                from latent_process import close_native as close_loop_native
                await close_loop_native()
        self.run_contexts(run)
        with self.store.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
        export = self.client.get("/lune/export").json()
        self.assertNotIn("〔历史证据〕", json.dumps(export["messages"], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
