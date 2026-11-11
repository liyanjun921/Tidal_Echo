"""Regression tests for offline Émoi migration; never touch real user data."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.emoi_migrate_storage import migrate, migrate_sqlite


class MigrationTests(unittest.TestCase):
    def test_legacy_data_and_vault_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / "relay.db"
            with sqlite3.connect(old) as db:
                db.executescript("""
                CREATE TABLE messages(id INTEGER PRIMARY KEY,meta TEXT, text TEXT);
                CREATE TABLE lune_memories(id TEXT PRIMARY KEY,content TEXT);
                CREATE TABLE lune_runs(id TEXT PRIMARY KEY,room TEXT);
                CREATE TABLE lune_memory_sessions(room TEXT, agent TEXT);
                CREATE INDEX lune_runs_room ON lune_runs(room);
                """)
                db.execute("INSERT INTO messages VALUES(?,?,?)",
                           (5, json.dumps({"api_session": "lune-gpt", "nonce": "n"}), "private text"))
                db.execute("INSERT INTO lune_memories VALUES('abc','original memory')")
                db.execute("INSERT INTO lune_runs VALUES('run','lune-claude')")
                db.execute("INSERT INTO lune_memory_sessions VALUES('lune-group','gpt')")
            (root / "lune-private").mkdir()
            (root / "lune-private" / "note.md").write_text("private original", encoding="utf-8")
            before = migrate(root)
            self.assertEqual(before["mode"], "dry-run")
            self.assertFalse((root / "emoi.db").exists())
            result = migrate(root, apply=True)
            self.assertTrue(result["source_preserved"])
            self.assertTrue(old.exists())
            self.assertTrue((root / "lune-private" / "note.md").exists())
            self.assertEqual((root / "emoi-private" / "note.md").read_text(encoding="utf-8"), "private original")
            with sqlite3.connect(root / "emoi.db") as db:
                self.assertEqual(db.execute("SELECT content FROM emoi_memories").fetchone()[0], "original memory")
                self.assertEqual(db.execute("SELECT room FROM emoi_runs").fetchone()[0], "emoi-claude")
                self.assertEqual(db.execute("SELECT room FROM emoi_memory_sessions").fetchone()[0], "emoi-group")
                self.assertEqual(json.loads(db.execute("SELECT meta FROM messages WHERE id=5").fetchone()[0])["api_session"], "emoi-gpt")
                indexes = {x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
                self.assertIn("emoi_runs_room", indexes)
                self.assertNotIn("lune_runs_room", indexes)
            with self.assertRaises(FileExistsError):
                migrate(root, apply=True)

    def test_collision_is_rejected_and_target_not_created(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with sqlite3.connect(root / "relay.db") as db:
                db.execute("CREATE TABLE lune_t(id TEXT)")
                db.execute("CREATE TABLE emoi_t(id TEXT)")
            with self.assertRaises(RuntimeError):
                migrate_sqlite(root / "relay.db", root / "emoi.db")
            self.assertFalse((root / "emoi.db").exists())


if __name__ == "__main__":
    unittest.main()
