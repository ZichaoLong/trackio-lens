"""Online SQLite snapshots followed by immutable media; no writer is stopped."""

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def backup(source: Path, destination: Path):
    if destination.exists():
        raise ValueError("Backup destination must be new")
    destination.mkdir(parents=True, mode=0o700)
    databases = list(source.rglob("*.db"))
    for path in databases:
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (
            sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as src,
            sqlite3.connect(target) as dst,
        ):
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed")
        target.chmod(0o600)
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("Backup source may not contain symlinks")
        if (
            not path.is_file()
            or path in databases
            or path.name.endswith(("-wal", "-shm", "-journal"))
        ):
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(path, target)
        target.chmod(0o600)
    (destination.parent / (destination.name + ".backup.json")).write_text(
        json.dumps(
            {
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "databases": len(databases),
                "consistency": "Each database is transaction-consistent. Independent databases have separate snapshot times. Immutable assets copied after databases.",
            },
            indent=2,
        )
        + "\n"
    )
    return len(databases)


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(
        "Databases backed up:",
        backup(args.source.resolve(), args.destination.resolve()),
    )
