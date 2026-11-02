"""Start a disposable, authenticated synthetic instance and run browser checks."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_check import check  # noqa: E402

from trackio_lens.auth import initialize  # noqa: E402


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, mode=0o700)
    state = output / "auth"
    initialize(state)
    subprocess.run(
        [sys.executable, "scripts/seed_demo.py", str(output / "data")],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = output / "instance.json"
    config.write_text(
        json.dumps(
            {
                "state_dir": str(state),
                "data_dir": str(output / "data"),
                "frontend_dir": str(Path("frontend/dist").resolve()),
                "port": port,
            }
        )
    )
    config.chmod(0o600)
    base = f"http://127.0.0.1:{port}"
    with (output / "server.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "trackio_lens.cli",
                "serve",
                "--config",
                str(config),
            ],
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Demo service exited")
                try:
                    if httpx.get(base + "/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            check(base, state / "initial-access.json", output / "browser", strict=True)
        finally:
            process.terminate()
            process.wait(timeout=15)


if __name__ == "__main__":
    os.umask(0o077)
    main()
