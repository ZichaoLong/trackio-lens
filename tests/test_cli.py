import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from trackio_lens.cli import build_parser
from trackio_lens.cli_text import configure
from trackio_lens.completion import candidates, install, script
from trackio_lens.config import private_json


def cli(*args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "trackio_lens.cli", *args],
        text=True,
        capture_output=True,
        env={**os.environ, "TRACKIO_LENS_LANG": "zh", **(env or {})},
    )


def test_language_help_errors_and_machine_output(tmp_path):
    assert "启动服务" in cli("--help").stdout
    assert "Start the managed service" in cli("--lang", "en", "--help").stdout
    assert "Machine-readable" in cli("status", "--lang", "en", "--help").stdout
    assert (
        "Start the managed service"
        in cli("--help", env={"TRACKIO_LENS_LANG": "en"}).stdout
    )
    failure = cli("update")
    assert failure.returncode == 2 and "缺少必需参数" in failure.stderr
    state, data = tmp_path / "state", tmp_path / "data"
    state.mkdir(mode=0o700)
    data.mkdir(mode=0o700)
    config = state / "instance.json"
    private_json(config, {"state_dir": state, "data_dir": data})
    chinese = cli("recording-info", "--config", str(config))
    english = cli("recording-info", "--lang", "en", "--config", str(config))
    assert json.loads(chinese.stdout) == json.loads(english.stdout)
    assert set(p.name for p in state.iterdir()) == {"instance.json"}


def test_completion_does_not_invoke_commands_or_read_state():
    configure([])
    parser = build_parser()
    assert "restart" in candidates(parser, ["re"])
    assert "--commit" in candidates(parser, ["update", "--"])
    assert candidates(parser, ["--lang", "en", "record", "--events", ""]) == [
        "__files__"
    ]
    assert candidates(parser, ["completion", ""]) == ["bash", "zsh", "fish", "install"]
    assert candidates(parser, ["--lang", ""]) == ["zh", "en"]
    assert candidates(parser, ["update", "--commit", ""]) == []
    assert (
        cli("__complete", "serve", "--config", "/nonexistent").stdout.strip()
        == "__files__"
    )


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_installed_completion_preserves_shell_config(tmp_path, shell):
    rc = tmp_path / (".bashrc" if shell == "bash" else ".zshrc")
    rc.write_text("# existing unrelated user setup\n")
    command = tmp_path / "command with spaces"
    result = install(command, shell, tmp_path)
    first = rc.read_text()
    install(command, shell, tmp_path)
    assert rc.read_text() == first
    assert first.startswith("# existing unrelated user setup\n")
    assert "PATH=" not in first
    if shutil.which(shell):
        subprocess.run([shell, "-n", result["completion_file"]], check=True)
    file = Path(result["completion_file"])
    file.write_text("unrelated")
    with pytest.raises(ValueError, match="unrelated"):
        install(command, shell, tmp_path)


def test_bash_and_zsh_complete_real_options(tmp_path):
    command = tmp_path / "trackio-lens"
    command.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m trackio_lens.cli "$@"\n')
    command.chmod(0o700)
    bash = tmp_path / "completion.bash"
    bash.write_text(script("bash", command))
    result = subprocess.check_output(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            'source "$1"; COMP_WORDS=(trackio-lens record --); COMP_CWORD=2; _trackio_lens_complete; printf "%s\\n" "${COMPREPLY[@]}"',
            "test",
            str(bash),
        ],
        text=True,
    )
    assert "--events" in result.splitlines() and "--commit" not in result.splitlines()
    if shutil.which("zsh"):
        zsh = tmp_path / "completion.zsh"
        zsh.write_text(script("zsh", command))
        result = subprocess.check_output(
            [
                "zsh",
                "-f",
                "-c",
                'compdef() {}; compadd() { print -l -- "${@:2}"; }; source "$1"; words=(trackio-lens record --); CURRENT=3; _trackio_lens_complete',
                "test",
                str(zsh),
            ],
            text=True,
        )
        assert "--events" in result.splitlines()

    if shutil.which("fish"):
        fish = tmp_path / "completion.fish"
        fish.write_text(script("fish", command))
        result = subprocess.check_output(
            [
                "fish",
                "--no-config",
                "-c",
                'source "$argv[1]"; complete -C "trackio-lens record --"',
                str(fish),
            ],
            text=True,
        )
        assert "--events" in result.splitlines()
        sample = tmp_path / "example.jsonl"
        sample.touch()
        result = subprocess.check_output(
            [
                "fish",
                "--no-config",
                "-c",
                'source "$argv[1]"; complete -C "$argv[2]"',
                str(fish),
                "trackio-lens record --events " + str(tmp_path) + "/example",
            ],
            text=True,
        )
        assert str(sample) in result


def test_explicit_bootstrap_and_interactive_admin_initialization(tmp_path):
    state = tmp_path / "bootstrap"
    result = cli("init", "--state-dir", str(state), "--bootstrap-account")
    assert result.returncode == 0
    handoff = json.loads((state / "initial-access.json").read_text())
    assert handoff["username"] == "admin"
    assert handoff["password"] not in result.stdout + result.stderr
    before = (state / "credentials.json").read_bytes()
    assert cli("init", "--state-dir", str(state), "--bootstrap-account").returncode == 2
    assert (state / "credentials.json").read_bytes() == before
    personal = tmp_path / "personal"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trackio_lens.cli",
            "init",
            "--state-dir",
            str(personal),
        ],
        input="my-own-name\nsynthetic personal password\nsynthetic personal password\n",
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (personal / "initial-access.json").exists()
    assert (
        json.loads((personal / "credentials.json").read_text())["username"]
        == "my-own-name"
    )
    assert "synthetic personal password" not in result.stdout + result.stderr
