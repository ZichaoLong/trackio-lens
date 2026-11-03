"""Project JSONL → official local SDK. No HTTP, training imports, or SQL writes.

Every invocation creates a fresh projection. A failed or interrupted attempt is
never silently resumed: preserve the source, inspect the report, then explicitly
replay into another fresh run. Source time remains in JSONL; SDK time is import time.
"""

import argparse
import contextlib
import hashlib
import json
import math
import os
import tempfile
import time
import uuid
import warnings
from datetime import datetime
from pathlib import Path

MAX_EVENT_BYTES = 65536


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def decode_event(line, run_id, sequence, last_step, last_elapsed):
    value = json.loads(line)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Expected a schema_version 1 metric event")
    allowed = {
        "schema_version",
        "run_id",
        "sequence",
        "timestamp",
        "step",
        "metrics",
        "elapsed_seconds",
        "context",
    }
    if set(value) - allowed or value.get("run_id") != run_id:
        raise ValueError("Unexpected event fields or run identity")
    if type(value.get("sequence")) is not int or value["sequence"] != sequence:
        raise ValueError("Event sequence must be contiguous, starting at zero")
    step = value.get("step")
    if type(step) is not int or step < 0 or step < last_step:
        raise ValueError("Event step must be a nondecreasing nonnegative integer")
    stamp = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Source timestamps must include a timezone")
    elapsed = value.get("elapsed_seconds", last_elapsed)
    if (
        not number(elapsed)
        or elapsed < last_elapsed
        or ("elapsed_seconds" in value and elapsed < 0)
    ):
        raise ValueError("Invalid or decreasing elapsed time")
    metrics = value.get("metrics")
    if (
        not isinstance(metrics, dict)
        or not metrics
        or any(
            not isinstance(k, str) or not k or not number(v) for k, v in metrics.items()
        )
    ):
        raise ValueError("Metrics must be named finite scalar numbers")
    if {"step", "timestamp"} & metrics.keys():
        raise ValueError(
            "step and timestamp are reserved SDK fields; use namespaced metric keys"
        )
    context = value.get("context", {})
    if not isinstance(context, dict) or any(
        not k
        or not isinstance(k, str)
        or not (v is None or isinstance(v, (str, bool)) or number(v))
        for k, v in context.items()
    ):
        raise ValueError("Context must contain named finite scalar values")
    return value, elapsed


def event_stream(path, run_id, follow=False, done_file=None):
    sequence, last_step, last_elapsed = 0, -1, -1
    with path.open("rb") as source:
        identity = (os.fstat(source.fileno()).st_dev, os.fstat(source.fileno()).st_ino)
        while True:
            offset = source.tell()
            current = path.stat()
            if (current.st_dev, current.st_ino) != identity or current.st_size < offset:
                raise ValueError("Source event file was replaced or truncated")
            line = source.readline(MAX_EVENT_BYTES + 1)
            if len(line) > MAX_EVENT_BYTES:
                raise ValueError("Event exceeds the 64 KiB limit")
            complete = not follow or (done_file is not None and done_file.exists())
            if not line and complete:
                break
            if not line.endswith(b"\n"):
                if complete:
                    raise ValueError(
                        "Incomplete final event; preserve and repair the source record"
                    )
                source.seek(offset)
                time.sleep(0.2)
                continue
            event, last_elapsed = decode_event(
                line, run_id, sequence, last_step, last_elapsed
            )
            yield event
            sequence += 1
            last_step = event["step"]


def observation_digest(events):
    digest = hashlib.sha256()
    for event in events:
        update_digest(digest, event["step"], event["metrics"])
    return digest.hexdigest()


def update_digest(digest, step, metrics):
    # Both Trackio readers normalize stored integers/floats; compare their values.
    digest.update(
        json.dumps(
            [step, {k: float(v) for k, v in metrics.items()}],
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    )
    digest.update(b"\n")


def save_report(path, report):
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(report, out, indent=2, ensure_ascii=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def record(events, manifest_path, data_dir, report_path, follow=False, done_file=None):
    events, manifest_path, report_path = map(
        lambda p: Path(p).resolve(), (events, manifest_path, report_path)
    )
    manifest = json.loads(manifest_path.read_text())
    for key in ("run_id", "project", "name"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ValueError("Manifest needs nonempty run_id, project, and name")
    if not isinstance(manifest.get("config", {}), dict):
        raise ValueError("Manifest config must be an object")
    if any(
        os.environ.get(k)
        for k in ("TRACKIO_SERVER_URL", "TRACKIO_SPACE_ID", "TRACKIO_BUCKET_ID")
    ):
        raise ValueError(
            "Resolve remote destination variables before recording locally"
        )
    if "trackio" in __import__("sys").modules:
        raise RuntimeError(
            "Start a fresh recorder process so the destination precedes SDK import"
        )
    # Validate the complete offline source before creating any Trackio projection.
    if not follow:
        for _ in event_stream(events, manifest["run_id"]):
            pass
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x"):
        report_path.chmod(0o600)
    report = {
        "source_run_id": manifest["run_id"],
        "project": manifest["project"],
        "destination_name": manifest["name"] + "-projection-" + uuid.uuid4().hex[:12],
        "status": "starting",
        "event_count": 0,
        "last_sequence": None,
        "source_timestamps_preserved": False,
        "steps_preserved": True,
        "exactly_once": False,
        "workload_status": "not-determined-by-recorder",
    }
    save_report(report_path, report)
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ["TRACKIO_DIR"] = str(data_dir)
    os.environ["TRACKIO_STORAGE_MODE"] = "sqlite"
    expected = hashlib.sha256()
    try:
        with (
            warnings.catch_warnings(record=True) as caught,
            (report_path.with_suffix(".log")).open("x") as log,
            contextlib.redirect_stdout(log),
            contextlib.redirect_stderr(log),
        ):
            warnings.simplefilter("always")
            from importlib.metadata import version

            import trackio
            from trackio.sqlite_storage import SQLiteStorage

            report["sdk_version"] = version("trackio")
            run = trackio.init(
                project=manifest["project"],
                name=report["destination_name"],
                config={
                    **manifest.get("config", {}),
                    "lens_recording": {
                        "source_run_id": manifest["run_id"],
                        "source_time": "retained-in-jsonl",
                        "projection_time": "sdk-log-time",
                    },
                },
                resume="never",
                embed=False,
                auto_log_cpu=False,
                auto_log_gpu=False,
            )
            report.update(status="recording", destination_run_id=run.id)
            save_report(report_path, report)
            try:
                for event in event_stream(
                    events, manifest["run_id"], follow, done_file
                ):
                    run.log(event["metrics"], step=event["step"])
                    update_digest(expected, event["step"], event["metrics"])
                    report["event_count"] += 1
                    report["last_sequence"] = event["sequence"]
                    # This journal is progress, not a durable destination cursor.
                    if report["event_count"] % 100 == 0:
                        save_report(report_path, report)
            finally:
                run.finish()
            logs = SQLiteStorage.get_logs(
                manifest["project"], report["destination_name"]
            )
            actual = hashlib.sha256()
            for row in logs:
                update_digest(
                    actual,
                    row["step"],
                    {k: v for k, v in row.items() if k not in {"step", "timestamp"}},
                )
            report["warning_count"] = len(caught)
            report["readback_matches"] = (
                len(logs) == report["event_count"]
                and actual.hexdigest() == expected.hexdigest()
            )
            report["status"] = (
                "verified" if report["readback_matches"] and not caught else "uncertain"
            )
        save_report(report_path, report)
    except BaseException as error:
        report.update(
            status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
            error_type=type(error).__name__,
        )
        save_report(report_path, report)
        raise
    return report


def add_arguments(parser):
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="New private result file; never overwrites an attempt",
    )
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Follow complete lines until --done-file exists or interrupted",
    )
    parser.add_argument("--done-file", type=Path)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    args = parser.parse_args()
    if args.data_dir is None:
        parser.error("Standalone recorder requires --data-dir")
    result = record(
        args.events,
        args.manifest,
        args.data_dir,
        args.report,
        args.follow,
        args.done_file,
    )
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "verified" else 2)


if __name__ == "__main__":
    main()
