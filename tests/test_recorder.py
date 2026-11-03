import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from trackio_lens.recorder import decode_event, event_stream

ROOT = Path(__file__).parents[1]


def event(sequence=0, step=0):
    return {
        "schema_version": 1,
        "run_id": "test",
        "sequence": sequence,
        "timestamp": "2026-01-01T00:00:00Z",
        "step": step,
        "metrics": {"loss": 0.5},
    }


def test_event_rejects_ambiguous_sequence_and_nonfinite_values(tmp_path):
    for value in [
        event(sequence=1),
        event(step=-1),
        {**event(), "metrics": {"loss": float("nan")}},
        {**event(), "run_id": "another"},
        {**event(), "sequence": False},
    ]:
        with pytest.raises((ValueError, TypeError)):
            decode_event(json.dumps(value), "test", 0, -1, -1)
    path = tmp_path / "events"
    path.write_text(json.dumps(event()))
    with pytest.raises(ValueError, match="Incomplete"):
        list(event_stream(path, "test"))


def clean_env():
    return {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "TRACKIO_DIR",
            "TRACKIO_SERVER_URL",
            "TRACKIO_SPACE_ID",
            "TRACKIO_BUCKET_ID",
        }
    }


def test_cpp_offline_roundtrip_and_replay_is_a_fresh_projection(tmp_path):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++17 compiler unavailable")
    executable = tmp_path / "writer"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            ROOT / "examples/cpp/record_metrics.cpp",
            "-o",
            executable,
        ],
        check=True,
    )
    source = tmp_path / "source"
    subprocess.run([executable, source], check=True)
    assert subprocess.run([executable, source], capture_output=True).returncode != 0
    before = (source / "metrics.jsonl").read_bytes()
    ids = []
    for index in range(2):
        report = tmp_path / f"report{index}.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "trackio_lens.recorder",
                "--events",
                source / "metrics.jsonl",
                "--manifest",
                source / "manifest.json",
                "--data-dir",
                tmp_path / "data",
                "--report",
                report,
            ],
            cwd=ROOT,
            env=clean_env(),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (result.stderr, report.read_text())
        record = json.loads(report.read_text())
        assert record["event_count"] == 5 and record["readback_matches"]
        ids.append(record["destination_run_id"])
    assert ids[0] != ids[1]
    assert before == (source / "metrics.jsonl").read_bytes()


def test_live_follow_waits_for_complete_lines_and_completion(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_bytes(b"")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"run_id": "test", "project": "live-test", "name": "live"})
    )
    report, done = tmp_path / "report.json", tmp_path / "done"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "trackio_lens.recorder",
            "--events",
            events,
            "--manifest",
            manifest,
            "--data-dir",
            tmp_path / "data",
            "--report",
            report,
            "--follow",
            "--done-file",
            done,
        ],
        cwd=ROOT,
        env=clean_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if (
                report.exists()
                and report.stat().st_size
                and json.loads(report.read_text()).get("status") == "recording"
            ):
                break
            assert process.poll() is None
            time.sleep(0.05)
        else:
            pytest.fail("Recorder did not become ready")
        line = json.dumps(event()).encode()
        with events.open("ab") as out:
            out.write(line[:15])
            out.flush()
            time.sleep(0.3)
            assert (
                process.poll() is None
            )  # The partial line is not ingested or rejected.
            out.write(line[15:] + b"\n")
            out.flush()
        done.write_text("producer ended")
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, (stderr, stdout)
        assert json.loads(report.read_text())["event_count"] == 1
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
