import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sync_upstream", Path(__file__).parents[1] / "scripts/sync_upstream.py"
)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def test_three_way_import_preserves_local_changes():
    base = b"start\nkeep\nmiddle\nend\n"
    local = b"lens\nkeep\nmiddle\nend\n"
    new = b"start\nkeep\nmiddle\nupstream\n"
    assert sync.merge_file(local, base, new) == (
        b"lens\nkeep\nmiddle\nupstream\n",
        False,
    )


def test_conflict_and_deletion_are_explicit():
    assert sync.merge_file(b"lens\n", b"base\n", b"upstream\n")[1]
    assert sync.merge_file(b"lens", b"base", None)[1]
    assert sync.merge_file(b"base", b"base", None) == (None, False)
    assert sync.merge_file(None, b"base", b"base") == (None, False)


def test_pin_matches_release_manifest():
    import json
    import tomllib

    root = Path(__file__).parents[1]
    version = json.loads((root / "upstream/source.json").read_text())["backend_version"]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert "trackio==" + version in project["project"]["dependencies"]
    assert (
        "trackio==" + version in (root / "requirements.lock").read_text().splitlines()
    )
