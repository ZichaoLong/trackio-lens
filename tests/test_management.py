import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from trackio_lens.config import private_json
from trackio_lens.management import (
    install_command,
    recording_info,
    register_install,
    service_action,
)


@pytest.fixture
def managed(tmp_path):
    state, data, root = (tmp_path / name for name in ("state", "data", "releases"))
    for p in (state, data, root):
        p.mkdir(mode=0o700)
    config = state / "instance.json"
    private_json(config, {"state_dir": state, "data_dir": data})
    register_install(
        config, root, "trackio-lens.service", "/usr/bin/python3", "/usr/bin"
    )
    return config, root, data


def test_recording_discovery_needs_no_running_service_or_credentials(managed):
    config, _, data = managed
    info = recording_info(config)
    assert info["data_dir"] == str(data)
    assert info["environment"] == {
        "TRACKIO_DIR": str(data),
        "TRACKIO_STORAGE_MODE": "sqlite",
    }
    assert info["explicit_recording_authorization_required"]
    assert "token" not in json.dumps(info)


def test_discovery_locates_resources_in_the_selected_release(managed):
    config, root, _ = managed
    for name in ("previous", "updated"):
        source = root / name / "source"
        guide = source / "docs/recording.md"
        guide.parent.mkdir(parents=True)
        guide.write_text("installed guide")
        (root / "current").unlink(missing_ok=True)
        (root / "current").symlink_to(root / name)
        assert recording_info(config)["resources"] == {"recording_guide": str(guide)}


def test_service_control_refuses_unowned_unit(managed, tmp_path, monkeypatch):
    config, root, _ = managed
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    unit = tmp_path / ".config/systemd/user/trackio-lens.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("ExecStart=/unrelated/service\n")
    unit.chmod(0o600)
    runner = Mock()
    monkeypatch.setattr("trackio_lens.management.subprocess.run", runner)
    with pytest.raises(ValueError, match="ownership"):
        service_action(config, "stop")
    runner.assert_not_called()
    unit.write_text(f"ExecStart={root}/current/venv/bin/trackio-lens serve\n")
    service_action(config, "disable")
    assert runner.call_args.args[0] == [
        "systemctl",
        "--user",
        "disable",
        "trackio-lens.service",
    ]


def test_stable_command_preserves_arguments_and_refuses_unrelated_file(
    managed, tmp_path
):
    config, root, _ = managed
    command = tmp_path / "command with spaces"
    install_command(root, config, command)
    assert '"$@"' in command.read_text()
    assert command.stat().st_mode & 0o777 == 0o700
    install_command(root, config, command)
    command.write_text("unrelated")
    with pytest.raises(ValueError, match="unrelated"):
        install_command(root, config, command)
