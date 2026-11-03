"""Synthetic SDK operations used by the cross-version gate; destination is a copy."""

import argparse
import json
import os
import tempfile
import warnings
from pathlib import Path


def exercise(phase, project, name):
    import trackio
    from trackio.sqlite_storage import SQLiteStorage

    options = dict(
        project=project, name=name, auto_log_cpu=False, auto_log_gpu=False, embed=False
    )
    if phase in {"seed", "fresh", "concurrent"}:
        with tempfile.TemporaryDirectory() as temporary:
            from PIL import Image

            root = Path(temporary)
            image = root / "image.png"
            Image.new("RGB", (8, 8), "blue").save(image)
            file = root / "synthetic.txt"
            file.write_text("public compatibility fixture\n")
            run = trackio.init(
                **options, config={"source": "synthetic", "lr": 0.1}, resume="never"
            )
            run.log(
                {
                    "loss": 1.0,
                    "sample": trackio.Image(str(image)),
                    "report": trackio.Markdown("# Public compatibility fixture"),
                },
                step=0,
            )
            trackio.save(str(file))
            run.log_artifact(file, name="fixture-file-" + name, type="fixture")
            run.finish()
    elif phase == "append":
        run = trackio.init(
            **options, config={"source": "synthetic", "lr": 0.1}, resume="must"
        )
        run.log({"loss": 0.5}, step=1)
        run.finish()
        try:
            trackio.init(**{**options, "name": "missing-strict-resume"}, resume="must")
        except ValueError:
            pass
        else:
            raise AssertionError("Strict resume silently created a missing run")
    elif phase == "verify":
        logs = SQLiteStorage.get_logs(project, name)
        assert logs and logs[0]["loss"] == 1.0
        assert "sample" in logs[0] and "report" in logs[0]
        if name == "writer":
            assert len(logs) == 2 and logs[-1]["step"] == 1 and logs[-1]["loss"] == 0.5
        else:
            assert len(logs) == 1
        assert SQLiteStorage.get_run_config(project, name)["source"] == "synthetic"
        assert SQLiteStorage.get_run_artifacts(project, name, None)["output"]
        manifest = SQLiteStorage.get_artifact_manifest(
            project, "fixture-file-" + name, "latest"
        )
        assert manifest and manifest["manifest"]
        # Also prove copied media/files remain present, rather than only their rows.
        root = Path(os.environ["TRACKIO_DIR"])
        from PIL import Image
        from trackio.cas import blob_path, hash_file

        image = root / "media" / logs[0]["sample"]["file_path"]
        with Image.open(image) as decoded:
            assert decoded.size == (8, 8) and decoded.getpixel((0, 0)) == (0, 0, 255)
        for entry in manifest["manifest"]:
            blob = blob_path(project, entry["digest"])
            assert hash_file(blob) == (entry["digest"], entry["size"])
        assert any(
            p.read_text() == "public compatibility fixture\n"
            for p in root.rglob("synthetic.txt")
        )
    else:
        SQLiteStorage.migrate_all_projects()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase", choices=["seed", "fresh", "concurrent", "append", "verify", "migrate"]
    )
    parser.add_argument("project")
    parser.add_argument("name", default="writer", nargs="?")
    args = parser.parse_args()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        exercise(args.phase, args.project, args.name)
        # SDK persistence warnings may otherwise be swallowed by finish().
        meaningful = [
            w for w in caught if issubclass(w.category, (UserWarning, RuntimeWarning))
        ]
        if meaningful:
            raise RuntimeError(
                "SDK emitted warnings: " + "; ".join(str(w.message) for w in meaningful)
            )
    print(json.dumps({"phase": args.phase, "ok": True}))
