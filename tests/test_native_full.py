"""Native product features, using the unmodified original implementation."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_lune as fixtures
relay, loop = fixtures.relay, fixtures.loop
from backend.lune_memory import LatentEngine, MemoryStore
from backend.latent_process import close_native


class FullNativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="latent-full-")
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"LUNE_LATENT_FULL_DIR": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        fixtures.OwnerDataTests.setUp(self)
        self.addCleanup(lambda: fixtures.OwnerDataTests.tearDown(self))
        if not LatentEngine(relay.DB_PATH).installation():
            self.skipTest("original source required")
        with MemoryStore(relay.DB_PATH).db() as c:
            c.execute("UPDATE lune_memory_settings SET value=?,version=1", (json.dumps({"enabled": True, "auto_recall": True,
                "model_writes": True, "native_full": True, "embedding_route": "zero-dep"}),))

    def rpc(self, name, arguments=None, view="gpt", method="tools/call"):
        msg = {"jsonrpc": "2.0", "id": 1, "method": method}
        if method == "tools/call":
            msg["params"] = {"name": name, "arguments": arguments or {}}
        r = self.client.post("/lune/native/" + view + "/mcp", json=msg)
        self.assertEqual(r.status_code, 200, r.text)
        result = r.json()
        return result.get("result", result)

    def write(self, text="她周末在海边看到了蓝色风筝。", view="gpt"):
        result = self.rpc("latent_append", {"text": text, "current_state": "这件事已经结束。",
            "indexEvidence": [{"type": "event", "quote": text}, {"type": "state", "quote": "这件事已经结束。"}],
            "unresolvedOps": [{"action": "none"}]}, view)
        self.assertFalse(result.get("isError"), result)
        import re
        return re.search(r"recordId=([0-9a-f]{16})", json.dumps(result, ensure_ascii=False)).group(1)

    def test_native_tool_table_and_hidden_boundary(self):
        result = self.rpc("", method="tools/list")
        self.assertEqual({t["name"] for t in result["tools"]}, {"latent_session_start", "latent_search", "latent_append",
            "latent_supersede", "latent_correct", "latent_cleanup", "latent_unresolved", "latent_thread_close",
            "latent_fact_backfill", "latent_note_reply"})
        self.assertEqual(self.rpc("latent_passive_recall")["error"]["code"], -32601)
        self.assertEqual(self.client.get("/lune/native/status", headers={"Authorization": "Bearer wrong"}).status_code, 401)

    def test_native_append_preflight_search_restart_and_scope(self):
        preview = self.rpc("latent_append", {"mode": "preflight", "text": "她在海边看蓝色风筝。", "current_state": "已结束"})
        self.assertIn("preflightStatus", json.dumps(preview))
        rid = self.write()
        self.assertIn(rid, json.dumps(self.rpc("latent_search", {"query": "蓝色风筝", "queryVariant": "海边的风筝"})))
        other = json.dumps(self.rpc("latent_search", {"query": "蓝色风筝"}, "claude"), ensure_ascii=False)
        self.assertNotIn("她周末在海边看到了蓝色风筝。", other)
        self.assertNotIn("蓝色风筝", json.dumps(self.rpc("", view="group", method="tools/list")))

    def test_shared_is_readable_but_not_mutable_from_private(self):
        rid = self.write("她在共享空间约好了下周看银河。", "shared")
        result = self.rpc("latent_search", {"query": "下周看银河"})
        self.assertIn(rid, json.dumps(result))
        denied = self.rpc("latent_correct", {"quote": "她在共享空间约好了下周看银河。", "reason": "test"})
        self.assertTrue(denied["isError"], denied)
        self.assertIn(rid, json.dumps(self.rpc("latent_search", {"query": "下周看银河"}, "shared")))
        corrected = self.rpc("latent_correct", {"quote": "她在共享空间约好了下周看银河。", "reason": "这个约定没有发生。"}, "shared")
        self.assertFalse(corrected.get("isError"), corrected)
        self.assertNotIn("她在共享空间约好了下周看银河。", json.dumps(self.rpc("latent_search", {"query": "下周看银河"}), ensure_ascii=False))

    def test_notes_unresolved_thread_and_admin_views(self):
        self.write()
        note = self.client.post("/lune/native/gpt/admin/notes", json={"text": "请核对风筝的颜色。"})
        self.assertEqual(note.status_code, 200, note.text)
        pending = self.rpc("latent_session_start")
        self.assertIn("请核对风筝的颜色", json.dumps(pending, ensure_ascii=False))
        nid = note.json()["id"]
        self.assertFalse(self.rpc("latent_note_reply", {"id": nid, "decision": "declined", "reply": "先保留原始记录，等待新证据。"}).get("isError"))
        self.assertFalse(self.rpc("latent_unresolved", {"action": "open", "summary": "周末确定看展时间"}).get("isError"))
        self.assertFalse(self.rpc("latent_thread_close", {"window": 1, "topics": ["蓝色风筝"],
            "current_state": "本次聊天结束，周末计划尚未确定。", "unresolvedOps": [{"action": "none"}]}).get("isError"))
        for endpoint in ("days", "top", "facts/stats", "facts", "facts/random", "unresolved", "recalls", "thread", "milestones", "health", "notes"):
            from datetime import date
            r = self.client.get("/lune/native/gpt/admin/" + endpoint, params={"day": date.today().isoformat()} if endpoint == "facts" else {})
            self.assertEqual(r.status_code, 200, (endpoint, r.text))

    def test_native_cleanup_preview_and_delete(self):
        rid = self.write()
        preview = self.rpc("latent_cleanup", {"action": "preview", "recordId": rid})
        self.assertFalse(preview.get("isError"), preview)
        self.assertIn("confirmation", json.dumps(preview))
        import re
        token = re.search(r"确认令牌：([^\n]+)", preview["content"][0]["text"]).group(1)
        removed = self.rpc("latent_cleanup", {"action": "delete", "recordId": rid, "confirmation": token, "reason": "撤去虚构测试记录"})
        self.assertFalse(removed.get("isError"), removed)
        self.assertNotIn("她周末在海边看到了蓝色风筝。", json.dumps(self.rpc("latent_search", {"query": "蓝色风筝"}), ensure_ascii=False))

    def test_legacy_source_cannot_be_overwritten_by_native_tools(self):
        m = self.client.post("/lune/memories", json={"scope": "gpt", "title": "既有记忆", "content": "她喜欢在雨天喝桂花乌龙茶。"}).json()["memory"]
        self.assertIn("桂花乌龙", json.dumps(self.rpc("latent_search", {"query": "桂花乌龙茶"}), ensure_ascii=False))
        self.assertTrue(self.rpc("latent_correct", {"quote": m["content"], "reason": "test"})["isError"])
        self.client.delete("/lune/memories/" + m["id"], params={"version": 1})
        self.assertNotIn(m["content"], json.dumps(self.rpc("latent_search", {"query": "桂花乌龙茶"}), ensure_ascii=False))

    def test_original_fact_backfill_lifecycle_with_real_local_vectors(self):
        if not LatentEngine(relay.DB_PATH).passive_status()["assets_ready"]:
            self.skipTest("real local vectors required")
        store = MemoryStore(relay.DB_PATH)
        store.configure({"version": store.config()["version"], "embedding_route": "local"})
        corpus = Path(self.tmp.name) / "gpt" / "memory" / "timeline"
        corpus.mkdir(parents=True)
        file = corpus / "window_01_2026-10-20.md"
        file.write_text("## 2026-10-20\n她周末在海边看到了蓝色风筝。\n当下状态：那次旅行已经结束。", encoding="utf-8")
        result = self.rpc("latent_fact_backfill", {"action": "next"})
        self.assertFalse(result.get("isError"), result)
        text = result["content"][0]["text"]
        batch = json.loads(text[text.index("\n[") + 1:])
        submitted = self.rpc("latent_fact_backfill", {"action": "submit", "items": [{"block": batch[0]["block"],
            "facts": [{"fact": "她周末在海边看到了蓝色风筝。", "tag": "life", "kind": "event"}]}]})
        self.assertFalse(submitted.get("isError"), submitted)
        finished = self.rpc("latent_fact_backfill", {"action": "finish"})
        self.assertFalse(finished.get("isError"), finished)
        stats = self.client.get("/lune/native/gpt/admin/facts/stats")
        self.assertEqual(stats.status_code, 200, stats.text)
        self.assertIn("1", stats.text)

    def test_native_persona_is_complete_and_reloaded_in_real_request_builder(self):
        directory = Path(self.tmp.name) / "gpt"
        directory.mkdir(parents=True)
        file = directory / "persona.md"
        original = "  用户自己的完整文件。\n不强制预设人格。\n\n保留尾部空行。\n"
        file.write_text(original, encoding="utf-8")
        async def run():
            agent = loop.CURRENT_AGENT.set("gpt")
            try:
                messages, _ = await loop.build_messages("今天好呀", [], session_id="lune-gpt", use_context=False)
                self.assertIn(original, [m["content"] for m in messages])
                self.assertTrue(any(t["function"]["name"] == "latent_search" for t in loop.all_tools()))
                file.write_text(original + "本次确认的新一行。", encoding="utf-8")
                messages, _ = await loop.build_messages("再聊一句", [], session_id="lune-gpt", use_context=False)
                self.assertIn(original + "本次确认的新一行。", [m["content"] for m in messages])
            finally:
                loop.CURRENT_AGENT.reset(agent)
                from latent_process import close_native
                await close_native()
        asyncio.run(run())

    def test_native_supersede_history_and_correction(self):
        rid = self.write("她原来住在云港东湾。")
        changed = self.rpc("latent_supersede", {"supersedes": rid, "text": "她搬到了临川南坡。", "current_state": "当前住在临川南坡。",
            "indexEvidence": [{"type": "event", "quote": "她搬到了临川南坡。"}, {"type": "state", "quote": "当前住在临川南坡。"}],
            "unresolvedOps": [{"action": "none"}]})
        self.assertFalse(changed.get("isError"), changed)
        history = self.rpc("latent_search", {"query": "以前云港东湾搬到临川南坡的变迁"})
        self.assertIn("云港东湾", json.dumps(history, ensure_ascii=False))
        self.assertIn("临川南坡", json.dumps(history, ensure_ascii=False))
        corrected = self.rpc("latent_correct", {"quote": "她搬到了临川南坡。", "reason": "这条是测试中写错的。"})
        self.assertFalse(corrected.get("isError"), corrected)
        self.assertNotIn("她搬到了临川南坡。", json.dumps(self.rpc("latent_search", {"query": "以前临川南坡"}), ensure_ascii=False))

    def test_model_cancel_and_write_switch_are_enforced(self):
        msg = relay.save_message("in", "user", "这是当前回合。", {"api_session": "lune-gpt"})
        with MemoryStore(relay.DB_PATH).db() as c:
            c.execute("INSERT INTO lune_runs VALUES(?,?,?,?,?,?,?,?,?)", ("full-run", "gpt", "full-nonce", msg["id"], '["gpt"]', "cancelled", "", "2026-10-24", "2026-10-24"))
        request = {"room": "lune-gpt", "agent_id": "gpt", "run_id": "full-run", "message": {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "latent_append", "arguments": {"text": "取消后不得保存。", "current_state": "测试"}}}}
        self.assertEqual(self.client.post("/lune/assistant/native", json=request).status_code, 409)
        with MemoryStore(relay.DB_PATH).db() as c:
            c.execute("UPDATE lune_runs SET state='running' WHERE id='full-run'")
        store = MemoryStore(relay.DB_PATH)
        store.configure({"version": store.config()["version"], "model_writes": False})
        self.assertEqual(self.client.post("/lune/assistant/native", json=request).status_code, 403)


if __name__ == "__main__":
    unittest.main()
