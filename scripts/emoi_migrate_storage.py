"""Offline, loss-avoiding migration from legacy Luné paths to Émoi.

Run only with ALL old writers stopped, after taking a verified volume backup.
Never deletes the source database or vault.  No live migrations at startup.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

OLD_PREFIX = "lune_"
NEW_PREFIX = "emoi_"
ROOMS = {"lune-gpt": "emoi-gpt", "lune-claude": "emoi-claude", "lune-group": "emoi-group"}
TABLE = re.compile(r"^lune_[a-zA-Z0-9_]+$")
INDEX = re.compile(r"^lune_[a-zA-Z0-9_]+$")


def inspect(root: Path) -> dict:
    root = Path(root).resolve()
    old_db, new_db = root / "relay.db", root / "emoi.db"
    old_vault, new_vault = root / "lune-private", root / "emoi-private"
    return {
        "old_database_exists": old_db.is_file(),
        "new_database_exists": new_db.exists(),
        "old_vault_exists": old_vault.is_dir(),
        "new_vault_exists": new_vault.exists(),
    }


def migrate_sqlite(source: Path, target: Path) -> None:
    """Use sqlite backup snapshot + atomic replace; leave original as rollback."""
    if target.exists():
        raise FileExistsError("Émoi database already exists: refuse to overwrite")
    if not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".emoi-migration-", suffix=".db", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as original:
            with sqlite3.connect(tmp) as work:
                original.backup(work)
        with sqlite3.connect(tmp) as work:
            work.execute("PRAGMA foreign_keys=OFF")
            if work.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("legacy SQLite integrity check failed")
            tables = [row[0] for row in work.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )]
            planned = {t: NEW_PREFIX + t[len(OLD_PREFIX):] for t in tables if TABLE.fullmatch(t)}
            if set(planned.values()) & set(tables):
                raise RuntimeError("legacy and Émoi tables collide; manual review required")
            work.execute("BEGIN IMMEDIATE")
            for old, new in planned.items():
                work.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
            # SQLite does not support ALTER INDEX RENAME; recreate only named
            # legacy indexes, keeping the original column expressions.
            indexes = work.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            ).fetchall()
            for name, definition in indexes:
                if not INDEX.fullmatch(name):
                    continue
                renamed = NEW_PREFIX + name[len(OLD_PREFIX):]
                work.execute(f'DROP INDEX "{name}"')
                statement = re.sub(r"\b" + re.escape(name) + r"\b", renamed, definition, count=1)
                work.execute(statement)
            for table in ("messages", "emoi_runs", "emoi_memory_sessions"):
                if table not in set(tables) | set(planned.values()):
                    continue
                cols = {x[1] for x in work.execute(f'PRAGMA table_info("{table}")')}
                if "room" in cols:
                    for old, new in ROOMS.items():
                        work.execute(f'UPDATE "{table}" SET room=? WHERE room=?', (new, old))
            if "messages" in tables:
                for row_id, value in work.execute("SELECT id,meta FROM messages").fetchall():
                    if not value or "lune-" not in value:
                        continue
                    try:
                        meta = json.loads(value)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(meta, dict) or meta.get("api_session") not in ROOMS:
                        continue
                    meta["api_session"] = ROOMS[meta["api_session"]]
                    work.execute("UPDATE messages SET meta=? WHERE id=?",
                                 (json.dumps(meta, ensure_ascii=False), row_id))
            work.commit()
            if work.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Émoi SQLite integrity check failed")
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def migrate(root: Path, apply: bool = False) -> dict:
    root = Path(root).resolve()
    state = inspect(root)
    if not apply:
        return {"mode": "dry-run", **state}
    if state["new_database_exists"] and state["old_database_exists"]:
        raise FileExistsError("both legacy and Émoi database exist: no automatic overwrite")
    if state["new_vault_exists"] and state["old_vault_exists"]:
        raise FileExistsError("both legacy and Émoi vault exist: no automatic overwrite")
    if state["old_database_exists"]:
        migrate_sqlite(root / "relay.db", root / "emoi.db")
    if state["old_vault_exists"]:
        shutil.copytree(root / "lune-private", root / "emoi-private", copy_function=shutil.copy2)
    return {"mode": "applied", "source_preserved": True, **inspect(root)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Émoi offline storage migration")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="requires offline backup and stopped writers")
    args = parser.parse_args()
    print(json.dumps(migrate(args.data_dir, apply=args.apply), ensure_ascii=False))
