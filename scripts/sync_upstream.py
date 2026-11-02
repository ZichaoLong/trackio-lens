"""Three-way import of official release sources, preserving Lens changes.

No working file is changed if any file conflicts. Resolve in the emitted private
staging tree, then copy the reviewed resolution back and update source.json.
"""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(clone, *args):
    return subprocess.check_output(["git", "-C", str(clone), *args])


def release(tag=None):
    suffix = "tags/" + tag.replace("@", "%40") if tag else "latest"
    request = urllib.request.Request(
        "https://api.github.com/repos/gradio-app/trackio/releases/" + suffix,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "trackio-lens"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if (
        data["draft"]
        or data["prerelease"]
        or not re.fullmatch(r"trackio@\d+\.\d+\.\d+", data["tag_name"])
    ):
        raise ValueError("Expected an official stable Trackio release")
    return data


def snapshot(clone, tag):
    paths = (
        git(
            clone,
            "ls-tree",
            "-r",
            "--name-only",
            tag,
            "trackio/frontend",
            "trackio/assets",
            "LICENSE",
        )
        .decode()
        .splitlines()
    )
    files, entries = {}, {}
    for path in paths:
        if path.startswith("trackio/frontend/"):
            target = "frontend/" + path.removeprefix("trackio/frontend/")
        elif path.startswith("trackio/assets/"):
            target = "upstream/assets/" + path.removeprefix("trackio/assets/")
        else:
            target = path
        data = git(clone, "show", tag + ":" + path)
        files[target] = data
        entries[target] = {"path": path, "sha256": hashlib.sha256(data).hexdigest()}
    return files, entries


def merge_file(local, base, incoming):
    if local == base or local == incoming:
        return incoming, False
    if incoming == base:
        return local, False
    if None in (local, base, incoming) or any(
        b"\0" in value for value in (local, base, incoming)
    ):
        return local, True
    with tempfile.TemporaryDirectory() as directory:
        files = [Path(directory) / name for name in ("local", "base", "upstream")]
        for path, data in zip(files, (local, base, incoming)):
            path.write_bytes(data)
        result = subprocess.run(
            ["git", "merge-file", "-p", *map(str, files)], capture_output=True
        )
        return result.stdout, result.returncode != 0


def sync(clone, tag):
    if git(ROOT, "status", "--porcelain").strip():
        raise SystemExit("Commit or stash work before syncing")
    published = release(tag)
    subprocess.run(["git", "-C", str(clone), "fetch", "origin", "tag", tag], check=True)
    old = json.loads((ROOT / "upstream/source.json").read_text())
    base, base_entries = snapshot(clone, old["commit"])
    if base_entries != old["files"]:
        raise ValueError("Recorded upstream baseline does not match source objects")
    incoming, entries = snapshot(clone, tag)
    commit = git(clone, "rev-parse", tag + "^{commit}").decode().strip()
    manifest = {
        **old,
        "tag": tag,
        "commit": commit,
        "backend_version": tag.split("@")[1],
        "release_url": published["html_url"],
        "files": entries,
    }
    merged, conflicts = {}, []
    for name in sorted(base.keys() | incoming.keys()):
        path = ROOT / name
        local = path.read_bytes() if path.exists() else None
        merged[name], conflict = merge_file(local, base.get(name), incoming.get(name))
        if conflict:
            conflicts.append(name)
    if conflicts:
        stage = Path(tempfile.mkdtemp(prefix="trackio-lens-upstream-"))
        for name, data in merged.items():
            if data is not None:
                path = stage / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        (stage / "upstream/source.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
        (stage / "conflicts.json").write_text(json.dumps(conflicts, indent=2) + "\n")
        raise SystemExit(
            f"Working tree unchanged. Review merge conflicts in {stage}: {', '.join(conflicts)}"
        )
    for name, data in merged.items():
        path = ROOT / name
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    (ROOT / "upstream/source.json").write_text(json.dumps(manifest, indent=2) + "\n")
    project = ROOT / "pyproject.toml"
    project.write_text(
        project.read_text().replace(
            "trackio==" + old["backend_version"],
            "trackio==" + manifest["backend_version"],
        )
    )
    print(
        "Imported",
        tag,
        commit,
        "— regenerate requirements.lock, review adapter and run all checks before committing/deploying.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clone", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(
            json.dumps(
                {
                    "current": json.loads((ROOT / "upstream/source.json").read_text())[
                        "tag"
                    ],
                    "latest": release()["tag_name"],
                }
            )
        )
    elif args.clone and args.tag:
        sync(args.clone.resolve(), args.tag)
    else:
        parser.error("Use --check, or --clone PATH --tag RELEASE")
