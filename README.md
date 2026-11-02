# Trackio Lens

An independent Trackio frontend for viewing and comparing experiments on desktop and mobile.

Lens retains the complete [Trackio](https://github.com/gradio-app/trackio) frontend and uses the matching official Python backend in one authenticated ASGI process. It is an independent project, not an official Trackio distribution. The upstream MIT license is preserved in [LICENSE](LICENSE); original resources and source hashes are recorded in [upstream/source.json](upstream/source.json). Dependencies retain their respective licenses.

Start with [development](docs/development.md), [architecture and task navigation](docs/architecture.md), [instance operation](docs/operations.md), or [current delivery status](docs/status.md). Product behavior is defined in [docs/product.md](docs/product.md).

Use Python 3.11+ and Node 22 (22.13+ for the upstream ESLint toolchain):

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
