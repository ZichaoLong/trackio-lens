import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from trackio_lens import skills, update_worker
from trackio_lens.config import private_json

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import release  # noqa: E402


def artifact(root, name, *, legacy=False):
    candidate = root / name
    candidate.mkdir(mode=0o700)
    source = candidate / "source"
    package = source / skills.PACKAGE
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(name)
    manifest = {"source_commit": name}
    if not legacy:
        manifest["integration_skill"] = skills.source_manifest(source)
    dist = source / "frontend/dist"
    dist.mkdir(parents=True)
    (dist / "lens-build.json").write_text(json.dumps(manifest))
    return candidate


@pytest.fixture
def installation(tmp_path, monkeypatch):
    home, root = tmp_path / "home", tmp_path / "releases"
    home.mkdir()
    root.mkdir(mode=0o700)
    monkeypatch.setattr(Path, "home", lambda: home)
    return root, home / ".agents/skills" / skills.NAME


def test_default_entry_follows_update_and_verified_rollback(installation):
    root, entry = installation
    old, new = artifact(root, "old"), artifact(root, "new")
    skills.prepare(root)
    assert not entry.exists()  # Preparing never advertises an unverified build.
    for candidate in (old, new, old):
        release.switch(root, candidate)
        assert skills.sync(root, candidate)["installed"]
        assert entry.readlink() == skills.link_target(root)
        assert (entry / "SKILL.md").read_text() == candidate.name
    assert (root / "skill.json").stat().st_mode & 0o777 == 0o600


def test_custom_directory_and_opt_out_persist_across_publications(installation):
    root, entry = installation
    current = artifact(root, "installed")
    release.switch(root, current)
    skills.prepare(root)
    skills.sync(root, current)
    parent = root / "custom-skills"
    custom = parent / skills.NAME
    skills.prepare(root, directory=parent)
    assert entry.exists() and not custom.exists()
    skills.sync(root, current)
    assert not entry.is_symlink() and custom.is_symlink()
    skills.prepare(root, enabled=False)
    skills.sync(root, current)
    assert not custom.is_symlink()
    skills.prepare(root)  # An update must preserve opt-out.
    assert not skills.sync(root, current)["installed"]
    skills.prepare(root, enabled=True)
    skills.sync(root, current)
    assert entry.is_symlink()


@pytest.mark.parametrize("kind", ["file", "directory", "symlink"])
def test_existing_unrelated_skill_is_never_overwritten(installation, kind):
    root, entry = installation
    entry.parent.mkdir(parents=True)
    if kind == "file":
        entry.write_text("user content")
    elif kind == "directory":
        entry.mkdir()
        (entry / "SKILL.md").write_text("user content")
    else:
        entry.symlink_to(root / "another-installer")
    with pytest.raises(ValueError, match="unrelated skill"):
        skills.prepare(root)
    assert not (root / "skill.json").exists()
    assert entry.exists() or entry.is_symlink()


def test_invalid_parent_and_conflicting_flags_fail_before_publication(installation):
    root, _ = installation
    parent = root / "not-a-directory"
    parent.write_text("user content")
    with pytest.raises(ValueError, match="not a directory"):
        skills.prepare(root, directory=parent / "nested")
    with pytest.raises(ValueError, match="--no-skill"):
        skills.prepare(root, enabled=False, directory=root / "elsewhere")
    assert not (root / "skill.json").exists()


def test_legacy_rollback_withdraws_entry_and_upgrade_restores_it(installation):
    root, entry = installation
    new, legacy = artifact(root, "new"), artifact(root, "legacy", legacy=True)
    skills.prepare(root)
    for candidate, installed in ((new, True), (legacy, False), (new, True)):
        release.switch(root, candidate)
        assert skills.sync(root, candidate)["installed"] is installed
        assert entry.is_symlink() is installed


def test_manifest_checks_packaged_content_and_refuses_symlinks(installation):
    root, _ = installation
    current = artifact(root, "installed")
    assert skills.validate_release(current) == "installed"
    package = current / "source" / skills.PACKAGE
    (package / "SKILL.md").write_text("changed after build")
    with pytest.raises(ValueError, match="manifest"):
        skills.validate_release(current)
    (package / "external").symlink_to(root / "private")
    with pytest.raises(ValueError, match="symlinks"):
        skills.source_manifest(current / "source")


def test_failed_activation_restores_skill_with_service(installation, monkeypatch):
    root, entry = installation
    old, new = artifact(root, "old"), artifact(root, "new")
    (old / "verified.json").write_text("{}")
    skills.prepare(root)
    release.switch(root, old)
    skills.sync(root, old)
    monkeypatch.setattr(release, "systemctl", Mock())
    monkeypatch.setattr(release, "read_build", lambda path: {})
    monkeypatch.setattr(release, "probe", Mock(side_effect=[ValueError("bad"), {}]))
    with pytest.raises(RuntimeError, match="restored the verified"):
        release.activate(root, new, old, "synthetic.service", "http://unused", {})
    assert entry.resolve() == old / "source" / skills.PACKAGE


def test_first_failure_withdraws_entry_and_conflict_never_restarts(
    installation, monkeypatch
):
    root, entry = installation
    current = artifact(root, "installed")
    skills.prepare(root)
    release.switch(root, current)
    skills.sync(root, current)  # Interrupted installation left an owned entry.
    control = Mock()
    monkeypatch.setattr(release, "systemctl", control)
    monkeypatch.setattr(release, "read_build", lambda path: {})
    monkeypatch.setattr(release, "probe", Mock(side_effect=ValueError("bad")))
    with pytest.raises(RuntimeError, match="First activation failed"):
        release.activate(root, current, None, "synthetic.service", "http://unused", {})
    assert not entry.is_symlink()
    control.reset_mock()
    entry.write_text("replacement owned by user")
    with pytest.raises(ValueError, match="unrelated skill"):
        release.activate(root, current, None, "synthetic.service", "http://unused", {})
    control.assert_not_called()
    assert entry.read_text() == "replacement owned by user"


def test_interrupted_worker_repairs_skill_after_http_validation(installation):
    root, entry = installation
    current = artifact(root, "accepted")
    (current / "validation.json").write_text("{}")
    release.switch(root, current)
    skills.prepare(root)
    state, data = root / "state", root / "data"
    state.mkdir(mode=0o700)
    data.mkdir(mode=0o700)
    config = state / "instance.json"
    private_json(config, {"state_dir": state, "data_dir": data})
    private_json(state / "api-access.json", {"api_token": "synthetic"})
    publisher = Mock()
    publisher.read_build.return_value = {"source_commit": "accepted"}
    publisher.probe.return_value = {"source_commit": "accepted"}
    result = update_worker.recover(
        publisher,
        {"root": str(root), "config": str(config)},
        {"previous_release": str(root / "previous"), "commit": "accepted"},
        None,
    )
    assert result["integration_skill"]["installed"]
    publisher.probe.assert_called_once()
    publisher.activate.assert_not_called()
    assert entry.resolve() == current / "source" / skills.PACKAGE


def test_recovery_without_verified_fallback_withdraws_skill(installation, monkeypatch):
    root, entry = installation
    current = artifact(root, "unverified")
    release.switch(root, current)
    skills.prepare(root)
    skills.sync(root, current)
    state, data = root / "state", root / "data"
    state.mkdir(mode=0o700)
    data.mkdir(mode=0o700)
    config = state / "instance.json"
    private_json(config, {"state_dir": state, "data_dir": data})
    private_json(state / "api-access.json", {"api_token": "synthetic"})
    stop = Mock()
    monkeypatch.setattr(update_worker, "service_action", stop)
    publisher = Mock()
    publisher.read_build.return_value = {"source_commit": "unverified"}
    with pytest.raises(ValueError, match="kept closed"):
        update_worker.recover(
            publisher,
            {"root": str(root), "config": str(config)},
            {"previous_release": str(root / "missing"), "commit": "unverified"},
            None,
        )
    stop.assert_called_once_with(str(config), "stop")
    assert not entry.is_symlink()
