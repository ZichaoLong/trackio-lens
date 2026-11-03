# Trackio Lens

An independent Trackio frontend for viewing and comparing experiments on desktop and mobile.

Lens retains the complete [Trackio](https://github.com/gradio-app/trackio) frontend and uses the matching official Python backend in one authenticated ASGI process. It is an independent project, not an official Trackio distribution. The upstream MIT license is preserved in [LICENSE](LICENSE); original resources and source hashes are recorded in [upstream/source.json](upstream/source.json). Dependencies retain their respective licenses.

Start with [development](docs/development.md), [architecture and task navigation](docs/architecture.md), [instance operation](docs/operations.md), or [current delivery status](docs/status.md). Product behavior is defined in [docs/product.md](docs/product.md).

Install committed source with a stable Python 3.11+ interpreter and Node 22.13+:

```sh
./install.sh --python /absolute/path/to/python3
~/.local/bin/trackio-lens status
~/.local/bin/trackio-lens recording-info --json
```

The installer builds an isolated release and a systemd user service. `start`, `stop`,
`restart`, `enable` and `disable` manage that service from any directory. It never
installs into a training environment. Choose an administrator username and password
in the terminal. Explicit unattended installs use `--bootstrap-account` and require
personal credentials at first login. Administrators can create read-only viewers;
viewers change only their own passwords. See [operations](docs/operations.md) for
ports, existing instances, account recovery and deployment verification.
CLI help defaults to Chinese (`--lang en` selects English); installation provides
Bash, Zsh or Fish completion without changing PATH.
It also installs the small [use-trackio-lens](skills/use-trackio-lens/SKILL.md)
agent skill into `~/.agents/skills`; use `--no-skill` to skip it or `--skills-dir`
to choose another parent directory. The skill follows the active release through
updates and recovery. It applies when the user selects Lens and does not require
a personal experiment-management skill.
The interface supports Chinese and English. [Recording](docs/recording.md) covers
independent Python SDKs and C++ JSONL import; [updates](docs/updates.md) explains
the web and CLI update workflow.

For development, use Python 3.11+ and Node 22.13+:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-build-isolation --no-deps -e .
npm --prefix frontend ci
.venv/bin/python -m pytest -q
.venv/bin/ruff check trackio_lens scripts tests
npm --prefix frontend test
npm --prefix frontend run lint
.venv/bin/python scripts/build.py
```

`scripts/build.py` requires committed source. Use `--allow-dirty` only for local development; the release script rejects these builds. Keep instance configuration, credentials, data, backups, logs and screenshots outside this public checkout. [Operations](docs/operations.md) describes creating and deploying an instance. No external tunnel, domain or proxy is required.
