"""Persistent opaque sessions, password verification and independent API access."""

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from collections import deque
from pathlib import Path

from .config import private_path

COOKIE = "trackio_lens_session"
TOKEN_HEADER = "x-trackio-lens-token"
CSRF_HEADER = "x-trackio-lens-csrf"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str, salt: str) -> str:
    return hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        n=2**15,
        r=8,
        p=1,
        maxmem=64 * 1024 * 1024,
    ).hex()


def initialize(state: Path, username: str = "admin") -> None:
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_path(state, directory=True)
    path = state / "credentials.json"
    if path.exists():
        raise ValueError("Credentials already exist; use reset-password to rotate")
    password, token, salt = (
        secrets.token_urlsafe(24),
        secrets.token_urlsafe(32),
        secrets.token_hex(16),
    )
    values = {
        "credentials.json": {
            "username": username,
            "salt": salt,
            "password_hash": password_hash(password, salt),
            "api_token_hash": digest(token),
        },
        "initial-access.json": {
            "username": username,
            "password": password,
            "api_token": token,
        },
    }
    for name, value in values.items():
        with (state / name).open("x") as out:
            (state / name).chmod(0o600)
            json.dump(value, out, indent=2)
            out.write("\n")
    with (state / "write-token").open("x") as out:
        (state / "write-token").chmod(0o600)
        out.write(secrets.token_urlsafe(32) + "\n")


class Auth:
    def __init__(self, state: Path, ttl: int):
        private_path(state, directory=True)
        self.credentials_path = state / "credentials.json"
        private_path(self.credentials_path)
        self.database = state / "sessions.sqlite3"
        self.ttl = ttl
        if self.database.exists():
            private_path(self.database)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, csrf TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL)"
            )
        self.database.chmod(0o600)
        self.attempts = deque()

    def connect(self):
        return sqlite3.connect(self.database, timeout=10)

    def credentials(self):
        private_path(self.credentials_path)
        return json.loads(self.credentials_path.read_text())

    def rate_limited(self) -> bool:
        now = time.monotonic()
        while self.attempts and self.attempts[0] < now - 300:
            self.attempts.popleft()
        if len(self.attempts) >= 20:
            return True
        self.attempts.append(now)
        return False

    def check_password(self, username: str, password: str) -> bool:
        c = self.credentials()
        match = hmac.compare_digest(
            password_hash(password, c["salt"]), c["password_hash"]
        )
        return match and hmac.compare_digest(username.encode(), c["username"].encode())

    def check_token(self, token: str) -> bool:
        return bool(token) and hmac.compare_digest(
            digest(token), self.credentials()["api_token_hash"]
        )

    def create_session(self):
        token, csrf, now = (
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(32),
            time.time(),
        )
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
            db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?)",
                (digest(token), csrf, now, now + self.ttl),
            )
        return token, csrf, now + self.ttl

    def session(self, token: str):
        if not token:
            return None
        with self.connect() as db:
            row = db.execute(
                "SELECT csrf, created, expires FROM sessions WHERE id = ?",
                (digest(token),),
            ).fetchone()
        if row and time.time() < min(row[2], row[1] + self.ttl):
            return {"csrf": row[0], "expires": min(row[2], row[1] + self.ttl)}
        return None

    def revoke(self, token: str | None = None):
        with self.connect() as db:
            if token is None:
                db.execute("DELETE FROM sessions")
            else:
                db.execute("DELETE FROM sessions WHERE id = ?", (digest(token),))
