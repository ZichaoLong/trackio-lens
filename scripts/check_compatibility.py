"""Check migration and an older local recording SDK on a private COPY only."""

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from backup import backup


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def table_digest(connection, table, columns):
    fields = ", ".join(map(quoted, columns))
    digest = hashlib.sha256()
    count = 0
    for row in connection.execute(
        f"SELECT {fields} FROM {quoted(table)} ORDER BY {fields}"
    ):
        digest.update(repr(row).encode())
        count += 1
    return digest.hexdigest(), count


def check(source, output, old_python):
    output.mkdir(parents=True, mode=0o700)
    copy = output / "data"
    databases = backup(source.resolve(), copy)
    before = {}
    for path in copy.glob("*.db"):
        with sqlite3.connect(path) as db:
            for (table,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ):
                columns = [
                    row[1] for row in db.execute(f"PRAGMA table_info({quoted(table)})")
                ]
                before[path.name, table] = (columns, table_digest(db, table, columns))
    environment = {
        **os.environ,
        "TRACKIO_DIR": str(copy),
        "TRACKIO_STORAGE_MODE": "sqlite",
    }
    environment.pop("TRACKIO_SERVER_URL", None)
    environment.pop("TRACKIO_SPACE_ID", None)
    migrate = "from trackio.sqlite_storage import SQLiteStorage; SQLiteStorage.migrate_all_projects()"
    with (output / "compatibility.log").open("w") as log:

        def run(python, code):
            subprocess.run(
                [str(python), "-c", code],
                env=environment,
                check=True,
                stdout=log,
                stderr=log,
            )

        run(sys.executable, migrate)
        for (name, table), (columns, expected) in before.items():
            with sqlite3.connect(copy / name) as db:
                if table_digest(db, table, columns) != expected:
                    raise ValueError(
                        "Migration changed historical data; inspect private copy"
                    )
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        if (copy / "lens-compat.db").exists():
            raise ValueError(
                "Reserved synthetic project lens-compat already exists in source"
            )
        code = 'import trackio; r=trackio.init(project="lens-compat",name="older-writer",auto_log_gpu=False,auto_log_cpu=False);r.log({"loss":1.0},step=0);r.finish()'
        run(old_python, code)
        run(sys.executable, migrate)
        run(
            old_python,
            code.replace('name="older-writer",', 'name="older-writer",resume="allow",')
            .replace("1.0", "0.5")
            .replace("step=0", "step=1"),
        )
        with sqlite3.connect(copy / "lens-compat.db") as db:
            assert db.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 2
        run(
            sys.executable,
            'from trackio.sqlite_storage import SQLiteStorage; logs=SQLiteStorage.get_logs("lens-compat","older-writer"); assert len(logs)==2 and logs[-1]["loss"]==0.5',
        )

    def version(python):
        return subprocess.check_output(
            [
                str(python),
                "-c",
                "from importlib.metadata import version; print(version('trackio'))",
            ],
            text=True,
        ).strip()

    report = {
        "old_backend": version(old_python),
        "new_backend": version(sys.executable),
        "databases": databases,
        "preserved_tables": len(before),
        "preserved_rows": sum(entry[1][1] for entry in before.values()),
        "integrity": "ok",
        "old_writer_append_after_migration": "passed",
        "new_reader_after_old_write": "passed",
        "data_location": "private copy only",
    }
    (output / "compatibility.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--old-python", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.source, args.output.resolve(), args.old_python)))
