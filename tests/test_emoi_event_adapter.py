"""No-network contract checks for Émoi's external wake injector."""
import os
import unittest
from unittest.mock import patch

from scripts import emoi_ingest_event as bridge


class BridgeContractTests(unittest.TestCase):
    def test_garden_v1_envelope(self):
        result = bridge.normalize({
            "version": 1, "type": "garden_wake",
            "reason": "game_turn_required", "message": "Turn available",
        })
        self.assertEqual(result["source"], "garden")
        self.assertEqual(result["type"], "garden.wake")
        self.assertTrue(result["event_id"].startswith("garden-"))
        self.assertEqual(result["priority"], 70)
        self.assertIn("Turn available", result["summary"])

    def test_bounded_garden_summary(self):
        result = bridge.normalize({
            "version": 1, "type": "garden_wake",
            "reason": "game_turn_required", "message": "a" * 1000,
        })
        self.assertLessEqual(len(result["summary"]), 600)

    def test_cyberboss_normalized_event(self):
        result = bridge.normalize({
            "source": "system",
            "event_id": "wechat-123",
            "type": "cyberboss.message.received",
            "summary": "An authorized test message",
            "priority": 60,
        })
        self.assertEqual(result["event_id"], "wechat-123")
        self.assertEqual(result["source"], "system")

    def test_rejects_unlisted_source_and_missing_id(self):
        for invalid in (
            {"source": "cyberboss", "event_id": "1", "type": "cyberboss.event", "summary": "x"},
            {"source": "system", "type": "cyberboss.event", "summary": "x"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                bridge.normalize(invalid)

    def test_validates_base_url_and_scope(self):
        env = {
            "EMOI_BASE_URL": "http://127.0.0.1:8088",
            "EMOI_SCOPE": "gpt",
            "EMOI_RELAY_SECRET": "test-only",
        }
        with patch.dict(os.environ, env):
            url, secret = bridge.endpoint()
            self.assertEqual(url, "http://127.0.0.1:8088/relay/lune/wren/gpt/events")
            self.assertEqual(secret, "test-only")
        with patch.dict(os.environ, {**env, "EMOI_BASE_URL": "http://example.com"}):
            with self.assertRaises(ValueError):
                bridge.endpoint()
        with patch.dict(os.environ, {**env, "EMOI_SCOPE": "other"}):
            with self.assertRaises(ValueError):
                bridge.endpoint()


if __name__ == "__main__":
    unittest.main()
