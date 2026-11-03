#!/usr/bin/env python3
"""Read-only check of an authenticated Lens viewer, assets and project API."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class CheckError(RuntimeError):
    pass


class _AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"] or "")
        elif tag == "link" and values.get("href"):
            rel = (values.get("rel") or "").lower()
            href = values["href"] or ""
            if "stylesheet" in rel or href.lower().split("?", 1)[0].endswith(".css"):
                self.assets.append(href)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _origin(parts: urllib.parse.SplitResult) -> tuple[str, str, int]:
    if parts.hostname is None:
        raise CheckError("URL has no hostname")
    default_port = 443 if parts.scheme == "https" else 80
    return parts.scheme, parts.hostname.lower(), parts.port or default_port


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_base_url(value: str, *, allow_remote: bool) -> str:
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in {"http", "https"}:
        raise CheckError("URL scheme must be http or https")
    if parts.username is not None or parts.password is not None:
        raise CheckError("URL user information is not allowed")
    if parts.query or parts.fragment:
        raise CheckError("URL query and fragment are not allowed")
    if parts.hostname is None:
        raise CheckError("URL has no hostname")
    try:
        _origin(parts)
    except ValueError as error:
        raise CheckError("URL port is invalid") from error
    if not allow_remote and not _is_loopback(parts.hostname):
        raise CheckError("non-loopback URL requires --allow-remote")
    return value.rstrip("/")


def _read_limited(response, limit: int = 2 * 1024 * 1024) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise CheckError("response exceeds size limit")
    return body


def _request(
    opener, request: urllib.request.Request, timeout: float
) -> tuple[int, bytes, str]:
    try:
        with opener.open(request, timeout=timeout) as response:
            return (
                response.status,
                _read_limited(response),
                response.headers.get("Content-Type", ""),
            )
    except urllib.error.HTTPError as error:
        raise CheckError(f"HTTP request failed with status {error.code}") from error
    except urllib.error.URLError as error:
        raise CheckError(
            f"HTTP request failed: {type(error.reason).__name__}"
        ) from error


def _project_names(payload: Any) -> list[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise CheckError("project API returned an unexpected JSON shape")
    data = payload["data"]
    if len(data) == 1 and isinstance(data[0], list):
        data = data[0]
    names: list[str] = []
    for item in data:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            value = item.get("name") or item.get("project")
            if isinstance(value, str):
                names.append(value)
    return sorted(set(names))


def check_server(
    base_url: str,
    *,
    timeout: float = 10.0,
    project: str | None = None,
    allow_remote: bool = False,
    credentials: Path | None = None,
) -> dict[str, Any]:
    base_url = _validate_base_url(base_url, allow_remote=allow_remote)
    headers = {}
    if credentials is not None:
        if credentials.is_symlink():
            raise CheckError("credential file cannot be a symlink")
        info = credentials.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise CheckError(
                "credential file must be owned by this account and mode 600"
            )
        token = json.loads(credentials.read_text()).get("api_token")
        if (
            not isinstance(token, str)
            or not token
            or not all(33 <= ord(character) <= 126 for character in token)
        ):
            raise CheckError("missing or invalid Lens program token")
        headers["X-Trackio-Lens-Token"] = token
    base_parts = urllib.parse.urlsplit(base_url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    status, homepage, content_type = _request(
        opener,
        urllib.request.Request(
            base_url + "/", headers={**headers, "Accept": "text/html"}
        ),
        timeout,
    )
    try:
        html = homepage.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CheckError("dashboard homepage is not UTF-8") from error
    if "trackio" not in html.lower():
        raise CheckError("dashboard homepage does not identify Trackio")

    parser = _AssetParser()
    parser.feed(html)
    asset_url = None
    asset_bytes = 0
    for candidate in parser.assets:
        resolved = urllib.parse.urljoin(base_url + "/", candidate)
        parts = urllib.parse.urlsplit(resolved)
        if parts.username is not None or parts.password is not None:
            continue
        if parts.scheme not in {"http", "https"} or _origin(parts) != _origin(
            base_parts
        ):
            continue
        asset_status, asset_body, _ = _request(
            opener, urllib.request.Request(resolved, headers=headers), timeout
        )
        if asset_status == 200 and asset_body:
            asset_url = parts.path
            asset_bytes = len(asset_body)
            break
    if asset_url is None:
        raise CheckError("no same-origin JavaScript or CSS asset could be loaded")

    api_request = urllib.request.Request(
        base_url + "/api/get_all_projects",
        data=b"{}",
        headers={
            **headers,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    api_status, api_body, _ = _request(opener, api_request, timeout)
    try:
        payload = json.loads(api_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CheckError("project API did not return valid JSON") from error
    projects = _project_names(payload)
    if project is not None and project not in projects:
        raise CheckError(f"requested project {project!r} was not listed")

    return {
        "ok": True,
        "base_url": base_url,
        "homepage_status": status,
        "homepage_bytes": len(homepage),
        "homepage_content_type": content_type.split(";", 1)[0],
        "asset_path": asset_url,
        "asset_bytes": asset_bytes,
        "project_api_status": api_status,
        "projects": projects,
        "requested_project": project,
        "requested_project_found": project is None or project in projects,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:7860")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--project")
    parser.add_argument(
        "--credentials", type=Path, help="Private Lens api-access.json file"
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow an explicitly supplied non-loopback dashboard URL.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = check_server(
            args.url,
            timeout=args.timeout,
            project=args.project,
            allow_remote=args.allow_remote,
            credentials=args.credentials,
        )
    except CheckError as error:
        report = {"ok": False, "error": str(error)}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
