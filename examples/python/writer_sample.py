"""Copy into a project and replace this small sample with its uncommon feature.

Run through `trackio-lens check-writer --python ... --sample THIS_FILE`.
The checker supplies an isolated TRACKIO_DIR. Never hard-code a real destination.
"""

import sys

import trackio
from trackio.sqlite_storage import SQLiteStorage

project, name = "lens-project-sample", "sample"
if sys.argv[1] == "write":
    run = trackio.init(project=project, name=name, resume="never", embed=False,
                       auto_log_cpu=False, auto_log_gpu=False)
    run.log({"custom/score": 0.75}, step=3)
    run.finish()
elif sys.argv[1] == "verify":
    rows = SQLiteStorage.get_logs(project, name)
    assert len(rows) == 1 and rows[0]["step"] == 3 and rows[0]["custom/score"] == 0.75
else:
    raise ValueError("Expected write or verify")
