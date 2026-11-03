"""Verify the actual running process after service installation or migration."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release import probe  # noqa: E402

from trackio_lens.config import private_path  # noqa: E402
from trackio_lens.upstream import read_build  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--config", type=Path, required=True)
args = parser.parse_args()
instance = json.loads(args.config.read_text())
access = Path(instance["state_dir"]) / "api-access.json"
private_path(access)
session = json.loads(access.read_text())
host = instance.get("host", "127.0.0.1")
host = "127.0.0.1" if host == "0.0.0.0" else "[::1]" if host == "::" else host
scheme = "https" if instance.get("ssl_certfile") else "http"
try:
    print(
        json.dumps(
            probe(
                f"{scheme}://{host}:{instance.get('port', 7860)}",
                read_build(args.root / "current/source/frontend/dist"),
                session,
            )
        )
    )
finally:
    session.clear()
