import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from check_viewer import CheckError, check_server  # noqa: E402


@pytest.fixture
def viewer(tmp_path):
    calls = []
    mode = {"redirect": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            calls.append(
                (self.command, self.path, self.headers.get("X-Trackio-Lens-Token"))
            )
            if self.headers.get("X-Trackio-Lens-Token") != "synthetic-token":
                self.send_response(401)
                self.end_headers()
                return
            if mode["redirect"]:
                self.send_response(302)
                self.send_header("Location", "/must-not-receive-token")
                self.end_headers()
                return
            content = {
                "/": b'<h1>Trackio</h1><script src="http://other.invalid/unsafe.js"></script><script src="/asset.js"></script>',
                "/asset.js": b"console.log('synthetic');",
                "/api/get_all_projects": b'{"data":["synthetic-project"]}',
            }
            self.send_response(200)
            self.end_headers()
            self.wfile.write(content[self.path])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    credential = tmp_path / "api-access.json"
    credential.write_text(json.dumps({"api_token": "synthetic-token"}))
    credential.chmod(0o600)
    try:
        yield f"http://127.0.0.1:{server.server_port}", credential, calls, mode
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_checker_authenticates_only_same_origin_reads(viewer):
    base, credential, calls, _ = viewer
    with pytest.raises(CheckError, match="401"):
        check_server(base)
    result = check_server(base, credentials=credential, project="synthetic-project")
    assert result["ok"] and result["requested_project_found"]
    assert calls[1:] == [
        ("GET", "/", "synthetic-token"),
        ("GET", "/asset.js", "synthetic-token"),
        ("POST", "/api/get_all_projects", "synthetic-token"),
    ]
    assert "synthetic-token" not in json.dumps(result)


def test_checker_refuses_redirects_without_forwarding_token(viewer):
    base, credential, calls, mode = viewer
    mode["redirect"] = True
    with pytest.raises(CheckError, match="302"):
        check_server(base, credentials=credential)
    assert len(calls) == 1


def test_checker_refuses_unsafe_credentials_and_urls_before_http(viewer, tmp_path):
    base, credential, calls, _ = viewer
    credential.chmod(0o644)
    with pytest.raises(CheckError, match="mode 600"):
        check_server(base, credentials=credential)
    credential.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(credential)
    with pytest.raises(CheckError, match="symlink"):
        check_server(base, credentials=link)
    for url in (
        base + "?token=private",
        "http://user:password@localhost",
        "http://remote.invalid",
    ):
        with pytest.raises(CheckError):
            check_server(url, credentials=credential)
    assert not calls
