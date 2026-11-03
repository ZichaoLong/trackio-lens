import json
import sys

from trackio_lens.config import private_json
from trackio_lens.management import register_install
from trackio_lens.writers import check


def test_real_sdk_check_cache_sample_and_registration(tmp_path):
    state, data, root = [tmp_path / n for n in ("state", "data", "release")]
    for directory in (state, data, root):
        directory.mkdir(mode=0o700)
    (data / "do-not-touch").write_bytes(b"production placeholder")
    config = state / "instance.json"
    private_json(config, {"state_dir": state, "data_dir": data})
    register_install(config, root, "test.service", sys.executable, "/usr/bin")
    first = check(config, sys.executable, register_writer=True)
    assert first["status"] == "passed" and not first["cached"] and first["registered"]
    second = check(config, sys.executable)
    assert second["cached"] and second["report"] == first["report"]
    assert list(data.iterdir()) == [data / "do-not-touch"]
    assert (data / "do-not-touch").read_bytes() == b"production placeholder"
    management = json.loads((state / "management.json").read_text())
    assert management["writer_pythons"] == [sys.executable]
    assert check(config, sys.executable, unregister=True)["status"] == "unregistered"
    assert json.loads((state / "management.json").read_text())["writer_pythons"] == []
