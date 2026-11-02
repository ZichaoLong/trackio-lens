import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
spec = importlib.util.spec_from_file_location(
    "release", Path(__file__).parents[1] / "scripts/release.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_failed_release_restores_only_verified_authenticated_build(
    tmp_path, monkeypatch
):
    previous, candidate = tmp_path / "old", tmp_path / "new"
    previous.mkdir()
    candidate.mkdir()
    (previous / "verified.json").write_text("{}")
    commands = []
    monkeypatch.setattr(release, "systemctl", lambda *args: commands.append(args))
    monkeypatch.setattr(release, "read_build", lambda path: {})
    monkeypatch.setattr(
        release, "probe", Mock(side_effect=[RuntimeError("bad release"), {}])
    )
    with pytest.raises(RuntimeError, match="restored the verified authenticated"):
        release.activate(
            tmp_path, candidate, previous, "test.service", "http://unused", None
        )
    assert (tmp_path / "current").resolve() == previous
    assert commands == [
        ("restart", "test.service"),
        ("stop", "test.service"),
        ("start", "test.service"),
    ]


def test_first_failure_stays_closed(tmp_path, monkeypatch):
    candidate = tmp_path / "new"
    candidate.mkdir()
    commands = []
    monkeypatch.setattr(release, "systemctl", lambda *args: commands.append(args))
    monkeypatch.setattr(release, "read_build", lambda path: {})
    monkeypatch.setattr(release, "probe", Mock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError, match="old anonymous service was NOT restored"):
        release.activate(
            tmp_path, candidate, None, "test.service", "http://unused", None
        )
    assert commands == [("restart", "test.service"), ("stop", "test.service")]
