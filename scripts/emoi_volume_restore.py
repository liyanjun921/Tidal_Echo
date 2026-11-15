"""Restore a trusted Émoi volume snapshot into an empty directory."""
import argparse
from pathlib import Path
import sqlite3
import sys
import tarfile


def restore(stream, target: Path):
    if any(target.iterdir()):
        raise SystemExit("恢复目标须是空数据卷")
    with tarfile.open(fileobj=stream, mode="r|gz") as archive:
        archive.extractall(target, filter="data")
    database = target / "emoi.db"
    if not database.is_file():
        raise SystemExit("归档中未找到 emoi.db")
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise SystemExit("数据库校验失败")
    print("EMOI_RESTORE=VERIFIED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    restore(sys.stdin.buffer, args.target.resolve())
