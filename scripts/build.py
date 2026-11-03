"""Build identity is derived from a committed tree, never a mutable label."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trackio_lens.skills import source_manifest  # noqa: E402


def build(root: Path, allow_dirty=False):
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root).strip()
    if status and not allow_dirty:
        raise SystemExit("Commit changes before building a release")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    source = json.loads((root / "upstream/source.json").read_text())
    subprocess.run(
        ["npm", "ci", "--no-audit", "--no-fund"], cwd=root / "frontend", check=True
    )
    subprocess.run(
        ["npm", "run", "build"],
        cwd=root / "frontend",
        check=True,
        env={**os.environ, "VITE_LENS_COMMIT": commit},
    )
    dist = root / "frontend/dist"
    (dist / "lens-locales.json").write_text(
        (root / "frontend/src/lib/zh.json").read_text()
    )
    assets = {
        str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(dist.rglob("*"))
        if p.is_file() and p.name != "lens-build.json"
    }
    manifest = {
        "source_commit": commit,
        "upstream_tag": source["tag"],
        "upstream_commit": source["commit"],
        "backend_version": source["backend_version"],
        "development_build": bool(status),
        "integration_skill": source_manifest(root),
        "assets": assets,
    }
    (dist / "lens-build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Local checks only; deployment rejects this manifest",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            build(Path(__file__).resolve().parents[1], args.allow_dirty), indent=2
        )
    )
