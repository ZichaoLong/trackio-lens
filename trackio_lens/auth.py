"""Persistent opaque sessions, password verification and independent API access."""

import fcntl
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path

from .config import private_json, private_path

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


def validate_account(username, password, *, administrator=False):
    if (
        not isinstance(username, str)
        or not username.strip()
        or len(username) > 80
        or any(ord(c) < 32 or ord(c) == 127 for c in username)
    ):
        raise ValueError("Username must contain between 1 and 80 characters")
    if not isinstance(password, str) or not password:
        raise ValueError("Enter a password")
    if not administrator and not 14 <= len(password) <= 256:
        raise ValueError("Use a password or passphrase of 14 to 256 characters")


def initialize(
    state: Path, username: str = "admin", password: str | None = None
) -> None:
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_path(state, directory=True)
    path = state / "credentials.json"
    if path.exists():
        raise ValueError("Credentials already exist; use reset-password to rotate")
    bootstrap = password is None
    password = secrets.token_urlsafe(24) if password is None else password
    validate_account(username, password, administrator=True)
    token, salt = secrets.token_urlsafe(32), secrets.token_hex(16)
    values = {
        "credentials.json": {
            "username": username,
            "salt": salt,
            "password_hash": password_hash(password, salt),
            "api_token_hash": digest(token),
            "needs_setup": bootstrap,
            "schema": 2,
            "viewers": {},
        },
        "initial-access.json": {
            "username": username,
            "password": password,
        },
        "api-access.json": {"api_token": token},
    }
    if not bootstrap:
        del values["initial-access.json"]
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
        # Legacy sessions remain in their own table for an authenticated fallback.
        # They are never interpreted as a new user session or assigned a role.
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, csrf TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS user_sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL)"
            )
        self.database.chmod(0o600)
        self.attempts = deque()
        self.account_attempts = {}
        self.attempt_lock = threading.Lock()
        self.separate_access_files()

    @contextmanager
    def account_lock(self):
        path = self.credentials_path.parent / ".account.lock"
        if path.exists() or path.is_symlink():
            private_path(path)
        with path.open("a") as lock:
            path.chmod(0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def separate_access_files(self):
        """Migrate the original handoff without rotating any credential/session."""
        with self.account_lock():
            state = self.credentials_path.parent
            initial = state / "initial-access.json"
            if not initial.exists():
                return
            private_path(initial)
            values = json.loads(initial.read_text())
            token = values.get("api_token")
            if token and self.check_token(token):
                access = state / "api-access.json"
                if not access.exists():
                    private_json(access, {"api_token": token})
                private_path(access)
                if json.loads(access.read_text()).get("api_token") != token:
                    raise ValueError("Program credential files disagree")
                del values["api_token"]
                private_json(initial, values)

    @staticmethod
    def users(credentials):
        # The single administrator retains the original top-level hash. An older
        # verified release can authenticate only that administrator, never viewers.
        return {"owner": credentials, **credentials.get("viewers", {})}

    @staticmethod
    def public(user_id, user):
        return {
            "user_id": user_id,
            "username": user["username"],
            "role": "admin" if user_id == "owner" else "viewer",
            "enabled": user.get("enabled", True),
            "needs_setup": user.get("needs_setup", False),
        }

    def account(self, user_id="owner"):
        user = self.users(self.credentials()).get(user_id)
        if user is None:
            raise PermissionError("Account is unavailable")
        return self.public(user_id, user)

    @staticmethod
    def matches(user, password):
        return isinstance(password, str) and hmac.compare_digest(
            password_hash(password, user["salt"]), user["password_hash"]
        )

    def login(self, username, password):
        with self.account_lock():
            credentials = self.credentials()
            selected = next(
                (
                    (uid, u)
                    for uid, u in self.users(credentials).items()
                    if u["username"] == username
                ),
                None,
            )
            # Unknown usernames still pay one password hash; no enumeration API.
            user = selected[1] if selected else credentials
            valid = self.matches(user, password)
            if selected and valid and user.get("enabled", True):
                return self.create_session(selected[0])
            self.failed_attempt(username)
            return None

    def change_account(
        self,
        username,
        password,
        current_password=None,
        renew_session=False,
        user_id="owner",
    ):
        with self.account_lock():
            credentials = self.credentials()
            user = self.users(credentials).get(user_id)
            if not user or not user.get("enabled", True):
                raise PermissionError("Account is unavailable")
            if current_password is not None and not self.matches(
                user, current_password
            ):
                self.failed_attempt(user["username"])
                raise PermissionError("Current password is incorrect")
            username = user["username"] if username is None else username
            if user_id != "owner" and username != user["username"]:
                raise PermissionError(
                    "Only the administrator can change their username"
                )
            if password is not None and not isinstance(password, str):
                raise ValueError("Enter a password")
            if not password:
                if user.get("needs_setup") or user_id != "owner":
                    raise ValueError("Set a new personal password before continuing")
                # Validate username without replacing the existing password hash.
                validate_account(username, "unused-validation-placeholder")
            else:
                validate_account(username, password, administrator=user_id == "owner")
            if user.get("needs_setup") and current_password is not None:
                if self.matches(user, password):
                    raise ValueError(
                        "Choose a different password from the temporary password"
                    )
                if user_id == "owner" and username.strip() == user["username"]:
                    raise ValueError("Choose your own administrator username")
            if any(
                uid != user_id
                and u["username"].casefold() == username.strip().casefold()
                for uid, u in self.users(credentials).items()
            ):
                raise ValueError("Username is already in use")
            if not password and username.strip() == user["username"]:
                raise ValueError("No account changes")
            user.update(
                username=username.strip(), revoked_before=time.time(), needs_setup=False
            )
            if password:
                user["salt"] = secrets.token_hex(16)
                user["password_hash"] = password_hash(password, user["salt"])
            private_json(self.credentials_path, credentials)
            self.revoke(user_id=user_id)
            if user_id == "owner":
                (self.credentials_path.parent / "initial-access.json").unlink(
                    missing_ok=True
                )
            return self.create_session(user_id) if renew_session else None

    def list_users(self):
        return [
            self.public(uid, user)
            for uid, user in self.users(self.credentials()).items()
        ]

    def manage_viewer(self, values, current_password):
        with self.account_lock():
            credentials = self.credentials()
            if not self.matches(credentials, current_password):
                self.failed_attempt(credentials["username"])
                raise PermissionError("Current password is incorrect")
            viewers = credentials.setdefault("viewers", {})
            action = values.get("action")
            if action == "create":
                username, password = values.get("username"), values.get("password")
                validate_account(username, password)
                username = username.strip()
                if any(
                    u["username"].casefold() == username.casefold()
                    for u in self.users(credentials).values()
                ):
                    raise ValueError("Username is already in use")
                if len(viewers) >= 1000:
                    raise ValueError("Account limit reached")
                user_id = secrets.token_hex(16)
                salt = secrets.token_hex(16)
                viewers[user_id] = {
                    "username": username,
                    "salt": salt,
                    "password_hash": password_hash(password, salt),
                    "needs_setup": True,
                    "enabled": True,
                }
            else:
                user_id = values.get("user_id")
                if not isinstance(user_id, str) or user_id not in viewers:
                    raise ValueError("Select an existing viewer account")
                user = viewers[user_id]
                if action == "set-enabled" and type(values.get("enabled")) is bool:
                    user["enabled"] = values["enabled"]
                elif action == "reset-password":
                    password = values.get("password")
                    validate_account(user["username"], password)
                    user["salt"] = secrets.token_hex(16)
                    user["password_hash"] = password_hash(password, user["salt"])
                    user["needs_setup"] = True
                else:
                    raise ValueError("Unsupported account action")
                user["revoked_before"] = time.time()
            credentials["schema"] = 2
            private_json(self.credentials_path, credentials)
            self.revoke(user_id=user_id)
            return self.public(user_id, viewers[user_id])

    def rotate_api_token(self):
        with self.account_lock():
            token = secrets.token_urlsafe(32)
            c = self.credentials()
            c["api_token_hash"] = digest(token)
            private_json(
                self.credentials_path.parent / "api-access.json", {"api_token": token}
            )
            private_json(self.credentials_path, c)

    def connect(self):
        return sqlite3.connect(self.database, timeout=10)

    def credentials(self):
        private_path(self.credentials_path)
        value = json.loads(self.credentials_path.read_text())
        if value.get("schema", 1) not in {1, 2}:
            raise ValueError("Unsupported account storage version")
        if "owner" in value.get("viewers", {}):
            raise ValueError("Invalid account storage")
        value.setdefault(
            "needs_setup",
            (self.credentials_path.parent / "initial-access.json").exists(),
        )
        return value

    def failed_attempt(self, username):
        now = time.monotonic()
        key = digest(str(username).casefold())
        with self.attempt_lock:
            self.attempts.append(now)
            # The global budget limits new buckets; prune old identities as well.
            self.account_attempts = {
                k: q
                for k, q in self.account_attempts.items()
                if q and q[-1] > now - 300
            }
            self.account_attempts.setdefault(key, deque()).append(now)

    def rate_limited(self, username=None) -> bool:
        now = time.monotonic()
        with self.attempt_lock:
            queues = [
                self.attempts,
                self.account_attempts.get(digest(str(username).casefold()), deque()),
            ]
            for queue in queues:
                while queue and queue[0] < now - 300:
                    queue.popleft()
            return len(queues[0]) >= 200 or len(queues[1]) >= 20

    def check_password(self, username: str, password: str) -> bool:
        user = next(
            (
                u
                for u in self.users(self.credentials()).values()
                if u["username"] == username
            ),
            None,
        )
        valid = bool(
            user and user.get("enabled", True) and self.matches(user, password)
        )
        if not valid:
            self.failed_attempt(username)
        return valid

    def check_token(self, token: str) -> bool:
        return bool(token) and hmac.compare_digest(
            digest(token), self.credentials()["api_token_hash"]
        )

    def create_session(self, user_id="owner"):
        user = self.account(user_id)
        if not user["enabled"]:
            raise PermissionError("Account is unavailable")
        token, csrf, now = (
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(32),
            time.time(),
        )
        with self.connect() as db:
            db.execute("DELETE FROM user_sessions WHERE expires <= ?", (now,))
            db.execute(
                "INSERT INTO user_sessions (id, user_id, csrf, created, expires) VALUES (?, ?, ?, ?, ?)",
                (digest(token), user_id, csrf, now, now + self.ttl),
            )
        return token, csrf, now + self.ttl

    def session(self, token: str):
        if not token:
            return None
        with self.connect() as db:
            row = db.execute(
                "SELECT user_id, csrf, created, expires FROM user_sessions WHERE id = ?",
                (digest(token),),
            ).fetchone()
        user = self.users(self.credentials()).get(row[0]) if row else None
        if (
            user
            and user.get("enabled", True)
            and row[2] > user.get("revoked_before", 0)
            and time.time() < min(row[3], row[2] + self.ttl)
        ):
            return {
                **self.public(row[0], user),
                "csrf": row[1],
                "expires": min(row[3], row[2] + self.ttl),
            }
        return None

    def revoke(self, token: str | None = None, *, user_id=None):
        with self.connect() as db:
            if token is not None:
                db.execute("DELETE FROM user_sessions WHERE id = ?", (digest(token),))
            elif user_id is not None:
                db.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            else:
                db.execute("DELETE FROM user_sessions")
            if user_id == "owner" or (token is None and user_id is None):
                db.execute("DELETE FROM sessions")
