"""Compatibility gate entry point; the installed checker shares this fixture."""

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "trackio_lens/writer_fixture.py"),
        run_name="__main__",
    )
