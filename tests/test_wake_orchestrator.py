"""Durable wake inbox contract tests."""
import sqlite3
import unittest

from backend import lune_wake as wake


class WakeInboxTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        wake.init(self.db)
        self.addCleanup(self.db.close)

    def enqueue(self, event_id, *, source='garden', priority=50, now=1000, ttl_seconds=3600, not_before=None):
        return wake.enqueue(
            self.db, 'gpt', source, event_id, 'garden.thread.reply',
            'Garden 有一条新回复。', resource_ref='thread:123',
            priority=priority, now=now, not_before=not_before, ttl_seconds=ttl_seconds,
        )

    def test_deduplication_is_scope_and_source_scoped_and_does_not_overwrite(self):
        first = self.enqueue('event-1')
        original = self.db.execute('SELECT summary FROM lune_wake_inbox WHERE id=?', (first['id'],)).fetchone()
        again = wake.enqueue(self.db, 'gpt', 'garden', 'event-1', 'garden.thread.reply',
                             '不同正文不覆盖原始事件', now=1001)
        other_source = self.enqueue('event-1', source='gmail')
        other_scope = wake.enqueue(self.db, 'claude', 'garden', 'event-1', 'garden.thread.reply',
                                   '另一空间的事件', now=1001)
        self.assertFalse(first['duplicate'])
        self.assertTrue(again['duplicate'])
        self.assertNotEqual(first['id'], other_source['id'])
        self.assertNotEqual(first['id'], other_scope['id'])
        self.assertEqual(original['summary'], 'Garden 有一条新回复。')

    def test_priority_claim_and_token_bound_finish(self):
        low = self.enqueue('low', priority=10)
        high = self.enqueue('high', priority=90)
        claimed = wake.claim_due(self.db, 'gpt', 1000)
        self.assertEqual(claimed['id'], high['id'])
        self.assertFalse(wake.finish(self.db, claimed['id'], 'wrong-token', 'message', now=1001))
        self.assertTrue(wake.finish(self.db, claimed['id'], claimed['claim_token'], 'trace', now=1001))
        next_item = wake.claim_due(self.db, 'gpt', 1002)
        self.assertEqual(next_item['id'], low['id'])

    def test_retry_is_bounded_and_delayed(self):
        item = self.enqueue('retry-me')
        first = wake.claim_due(self.db, 'gpt', 1000)
        self.assertTrue(wake.abort(self.db, first['id'], first['claim_token'], now=1000))
        row = self.db.execute('SELECT state,not_before,attempts FROM lune_wake_inbox WHERE id=?', (item['id'],)).fetchone()
        self.assertEqual(row['state'], 'pending')
        self.assertEqual(row['not_before'], 1300)
        self.assertIsNone(wake.claim_due(self.db, 'gpt', 1299))
        second = wake.claim_due(self.db, 'gpt', 1300)
        self.assertEqual(second['attempts'], 2)
        wake.abort(self.db, second['id'], second['claim_token'], now=1300)
        third = wake.claim_due(self.db, 'gpt', 1600)
        self.assertEqual(third['attempts'], 3)
        wake.abort(self.db, third['id'], third['claim_token'], now=1600)
        state = self.db.execute('SELECT state FROM lune_wake_inbox WHERE id=?', (item['id'],)).fetchone()['state']
        self.assertEqual(state, 'failed')

    def test_self_commitment_replaces_old_pending_commitment(self):
        first = wake.schedule_commitment(self.db, 'gpt', 'wake-1', 60, '继续读刚才的书。', now=1000)
        second = wake.schedule_commitment(self.db, 'gpt', 'wake-2', 90, '之后继续整理笔记。', now=1100)
        states = {row['id']: row['state'] for row in self.db.execute('SELECT id,state FROM lune_wake_inbox')}
        self.assertEqual(states[first['id']], 'cancelled')
        self.assertEqual(states[second['id']], 'pending')
        self.assertEqual(second['not_before'], 1100 + 90 * 60)

    def test_expiry_and_restart_recovery_are_explicit(self):
        expired = self.enqueue('expires', now=1000, ttl_seconds=60)
        self.assertIsNone(wake.peek_due(self.db, 'gpt', 1061))
        self.assertEqual(self.db.execute('SELECT state FROM lune_wake_inbox WHERE id=?', (expired['id'],)).fetchone()['state'], 'expired')
        pending = self.enqueue('interrupted', now=2000)
        claimed = wake.claim_due(self.db, 'gpt', 2000)
        self.assertEqual(claimed['id'], pending['id'])
        wake.recover(self.db, now=2001)
        row = self.db.execute('SELECT state,last_error FROM lune_wake_inbox WHERE id=?', (pending['id'],)).fetchone()
        self.assertEqual(row['state'], 'interrupted')
        self.assertIn('不自动重放', row['last_error'])

    def test_invalid_sources_priorities_and_commitment_ranges_are_rejected(self):
        with self.assertRaises(ValueError):
            wake.enqueue(self.db, 'gpt', 'unknown', 'x', 'test.event', 'summary', now=1000)
        with self.assertRaises(ValueError):
            wake.enqueue(self.db, 'gpt', 'garden', 'x', 'test.event', 'summary', priority=101, now=1000)
        with self.assertRaises(ValueError):
            wake.schedule_commitment(self.db, 'gpt', 'wake', 10, '太快了', now=1000)


if __name__ == '__main__':
    unittest.main()
