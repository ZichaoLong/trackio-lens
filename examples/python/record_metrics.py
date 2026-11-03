"""Run only after authorizing recording and setting the destination environment.

Use the training project's own Python/Trackio installation, never the Lens env.
"""

import os

if not os.environ.get("TRACKIO_DIR"):
    raise SystemExit("Set TRACKIO_DIR to a local Trackio data directory before importing Trackio")
if any(os.environ.get(k) for k in ("TRACKIO_SERVER_URL", "TRACKIO_SPACE_ID", "TRACKIO_BUCKET_ID")):
    raise SystemExit("Resolve conflicting remote destinations first")

import trackio  # noqa: E402

run = trackio.init(
    project="lens-python-demo",
    name="python-scalars",
    config={"source": "synthetic", "learning_rate": 0.01},
    resume="never",
    auto_log_cpu=False,
    auto_log_gpu=False,
    embed=False,
)
try:
    for step in range(5):
        run.log({"train/loss": 1.0 / (step + 1)}, step=step)
finally:
    trackio.finish()
