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
        project = "lens-compat-" + __import__("uuid").uuid4().hex[:10]
        fixture = Path(__file__).with_name("compatibility_fixture.py")

        def scenario(python, phase, name="writer"):
            subprocess.run(
                [str(python), str(fixture), phase, project, name],
                env=environment,
                check=True,
                stdout=log,
                stderr=log,
            )

        scenario(old_python, "seed")
        run(sys.executable, migrate)
        scenario(old_python, "append")
        scenario(old_python, "fresh", "new-after-migration")
        children = [
            subprocess.Popen(
                [
                    str(old_python),
                    str(fixture),
                    "concurrent",
                    project,
                    "parallel-" + str(index),
                ],
                env=environment,
                stdout=log,
                stderr=log,
            )
            for index in range(2)
        ]
        try:
            run(sys.executable, migrate)
            scenario(sys.executable, "verify", "writer")
            for child in children:
                if child.wait(timeout=60) != 0:
                    raise RuntimeError(
                        "Concurrent writer failed; inspect private compatibility log"
                    )
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)
        # Separate processes simulate repeated viewer opens and the fallback reader.
        for python in (sys.executable, old_python, sys.executable):
            if python == sys.executable:
                run(python, migrate)
            for name in ("writer", "new-after-migration", "parallel-0", "parallel-1"):
                scenario(python, "verify", name)
        for path in copy.glob("*.db"):
            with sqlite3.connect(path) as db:
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for (name, table), (columns, expected) in before.items():
            with sqlite3.connect(copy / name) as db:
                if table_digest(db, table, columns) != expected:
                    raise ValueError(
                        "Original data changed during writer compatibility check"
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
        "writer_dependencies": json.loads(
            subprocess.check_output(
                [
                    str(old_python),
                    "-c",
                    "import json; from importlib.metadata import version; print(json.dumps({p:version(p) for p in ['trackio','huggingface-hub','gradio-client','numpy','pillow']}))",
                ],
                text=True,
            )
        ),
        "new_backend": version(sys.executable),
        "databases": databases,
        "preserved_tables": len(before),
        "preserved_rows": sum(entry[1][1] for entry in before.values()),
        "integrity": "ok",
        "old_writer_append_after_migration": "passed",
        "new_reader_after_old_write": "passed",
        "data_location": "private copy only",
        "coverage": [
            "new-run-before-migration",
            "strict-resume-after-migration",
            "missing-strict-resume-rejected",
            "new-run-after-migration",
            "concurrent-independent-runs",
            "scalar-config-image-report-file-artifact",
            "repeated-new-reader-and-old-reader",
            "historical-data-preserved",
        ],
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
