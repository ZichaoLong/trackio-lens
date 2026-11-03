import json
import subprocess
import time
from unittest.mock import Mock

import pytest

from trackio_lens import update_worker, updates
from trackio_lens.config import private_json
from trackio_lens.management import register_install


@pytest.fixture
def managed(tmp_path):
    state, data, root = (tmp_path / name for name in ("state", "data", "root"))
    for directory in (state, data, root):
        directory.mkdir(mode=0o700)
    config = state / "instance.json"
    private_json(config, {"state_dir": state, "data_dir": data})
    register_install(config, root, "lens-test.service", "/usr/bin/python3", "/usr/bin")
    release = root / "release"
    release.mkdir()
    (root / "current").symlink_to(release)
    return config, root


@pytest.mark.parametrize(
    "value",
    [
        "file:///private/source",
        "https://user:secret@host/repo",
        "https://host/repo?token=secret",
        "--upload-pack=evil",
        "https://host/repo\ncommand",
        "ssh://user@host/repo",
    ],
)
def test_rejects_local_or_credential_bearing_repository(value):
    with pytest.raises(ValueError):
        updates.repository_url(value)


def test_selected_commit_is_fixed_and_only_one_worker_can_start(managed, monkeypatch):
    config, _ = managed
    sha = "a" * 40
    runner = Mock(
        return_value=subprocess.CompletedProcess([], 0, sha + "\trefs/heads/main\n", "")
    )
    monkeypatch.setattr(updates.subprocess, "run", runner)
    checked = updates.check(config)
    assert checked["checked"]["commit"] == sha
    with pytest.raises(ValueError, match="exact commit"):
        updates.start(config, "b" * 40)
    result = updates.start(config, sha)
    args = runner.call_args.args[0]
    assert args[:2] == ["systemd-run", "--user"]
    assert result["operation"]["commit"] == sha
    assert "previous_release" not in result["operation"]
    with pytest.raises(ValueError, match="running"):
        updates.start(config, sha)
    assert sum(call.args[0][0] == "systemd-run" for call in runner.call_args_list) == 1


def test_dead_worker_requires_recovery_before_retry(managed, monkeypatch):
    config, _ = managed
    directory = updates.update_dir(config)
    operation = {
        "id": "a" * 32,
        "phase": "switching",
        "unit": "lens-update-test.service",
        "commit": "b" * 40,
        "started": 0,
        "updated": time.time() - 60,
    }
    private_json(directory / "current.json", {"id": operation["id"]})
    private_json(directory / (operation["id"] + ".json"), operation)
    monkeypatch.setattr(
        updates.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 0, "inactive\n", "")),
    )
    assert updates.status(config)["operation"]["phase"] == "interrupted"
    with pytest.raises(ValueError, match="recovery"):
        updates.start(config, "b" * 40)


def test_build_failure_keeps_current_release_and_records_failure(managed, monkeypatch):
    config, root = managed
    previous = (root / "current").resolve()
    directory = updates.update_dir(config)
    identifier, sha = "a" * 32, "b" * 40
    operation = {
        "id": identifier,
        "phase": "starting",
        "action": "update",
        "commit": sha,
        "repository": "https://github.com/example/repo.git",
        "previous_release": str(previous),
    }
    private_json(directory / (identifier + ".json"), operation)
    monkeypatch.setattr(update_worker.subprocess, "run", Mock())
    monkeypatch.setattr(
        update_worker.subprocess, "check_output", Mock(return_value=sha)
    )

    def fail(args, progress):
        assert args.source.parent == directory
        progress("building")
        raise RuntimeError("test build failure")

    monkeypatch.setattr(
        update_worker,
        "publisher",
        lambda _: type("Publisher", (), {"publish": staticmethod(fail)})(),
    )
    with pytest.raises(RuntimeError, match="build failure"):
        update_worker.execute(config, identifier)
    assert (root / "current").resolve() == previous
    saved = json.loads((directory / (identifier + ".json")).read_text())
    assert saved["phase"] == "failed" and saved["failure_phase"] == "building"


def test_repository_change_discards_checked_commit(managed, monkeypatch):
    config, _ = managed
    directory = updates.update_dir(config)
    private_json(directory / "checked.json", {"commit": "a" * 40})
    state = updates.set_repository(config, "git@github.com:example/lens.git")
    assert state["checked"] is None
    assert state["repository"] == "git@github.com:example/lens.git"
