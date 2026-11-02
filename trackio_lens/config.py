"""Instance configuration. Paths and credentials never belong in a release."""

import json
import os
from dataclasses import dataclass
from pathlib import Path


def private_path(path: Path, *, directory: bool = False) -> None:
    if path.is_symlink():
        raise ValueError(f"Private path must not be a symlink: {path}")
    st = path.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError(
            f"Private path must be owned by this account and mode {'700' if directory else '600'}: {path}"
        )
    if directory != path.is_dir():
        raise ValueError(f"Unexpected path type: {path}")


@dataclass(frozen=True)
class Config:
    state_dir: Path
    data_dir: Path
    frontend_dir: Path
    host: str = "127.0.0.1"
    port: int = 7860
    session_ttl_seconds: int = 60 * 60 * 24 * 30
    cookie_secure: bool = False
    ssl_certfile: str | None = None
    ssl_keyfile: str | None = None

    @classmethod
    def read(cls, path: Path, frontend_dir: Path | None = None):
        private_path(path)
        raw = json.loads(path.read_text())
        for key in ("state_dir", "data_dir", "frontend_dir"):
            if key in raw:
                raw[key] = Path(raw[key]).expanduser().absolute()
        if frontend_dir:
            raw["frontend_dir"] = frontend_dir.resolve()
        elif "frontend_dir" in raw:
            raw["frontend_dir"] = raw["frontend_dir"].resolve()
        config = cls(**raw)
        if not 1 <= config.port <= 65535 or config.session_ttl_seconds <= 0:
            raise ValueError("Invalid port or session TTL")
        for path in (config.state_dir, config.data_dir):
            private_path(path, directory=True)
        return config
