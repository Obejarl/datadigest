"""User accounts: passwords, sessions and API tokens (used when AUTH_MODE=accounts).

Nothing here needs a library beyond the standard one:

- passwords are stored as scrypt hashes with a per-user salt, never as text;
- a session cookie is "<user id>.<expiry>.<HMAC>", signed with SECRET_KEY, so the server
  keeps no session table and a cookie cannot be forged or extended;
- an API token is shown once and stored as its SHA-256, so a leaked database does not
  hand out working tokens.

    python -m datadigest.accounts add ada@example.org --admin     # asks for the password
    python -m datadigest.accounts list
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import logging
import os
import secrets
import sys
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from datadigest.config import Settings, get_settings
from datadigest.models import Role, User

log = logging.getLogger(__name__)

SESSION_SECONDS = 30 * 24 * 3600
MIN_PASSWORD_LENGTH = 10
# scrypt cost: about 50 ms and 16 MB per check, which is slow enough to make guessing expensive.
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
TOKEN_PREFIX = "dd_"
_fallback_secret = secrets.token_bytes(32)


class AccountError(ValueError):
    """A problem with the input. The message is safe to show to users."""


# ---------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), **SCRYPT)
        return hmac.compare_digest(candidate, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"The password needs at least {MIN_PASSWORD_LENGTH} characters")


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    if not local or "." not in domain or " " in email or len(email) > 254:
        raise AccountError("That does not look like an email address")
    return email


# ---------------------------------------------------------------- sessions and tokens


def _secret(settings: Settings) -> bytes:
    if settings.secret_key:
        return settings.secret_key.encode()
    # Works for one process; sessions end when it restarts and other replicas reject them.
    return _fallback_secret


def make_session(user_id: uuid.UUID, settings: Settings, now: float | None = None) -> str:
    expires = int((now or time.time()) + SESSION_SECONDS)
    payload = f"{user_id.hex}.{expires}"
    signature = hmac.new(_secret(settings), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_session(value: str, settings: Settings, now: float | None = None) -> uuid.UUID | None:
    """The user id inside a session cookie, or None when it is forged, damaged or expired."""
    try:
        user_hex, expires, signature = value.split(".")
        payload = f"{user_hex}.{expires}"
        expected = hmac.new(_secret(settings), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature.encode(), expected.encode()):
            return None
        if int(expires) < (now or time.time()):
            return None
        return uuid.UUID(hex=user_hex)
    except (ValueError, AttributeError):
        return None


def new_token() -> tuple[str, str]:
    """A fresh API token and the hash to store. The token itself is never stored."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- users


def create_user(db: Session, email: str, password: str, role: str = Role.MEMBER) -> User:
    email = normalize_email(email)
    check_password_rules(password)
    if role not in tuple(Role):
        raise AccountError(f"Unknown role '{role}'. Choose one of: {', '.join(Role)}")
    if db.scalars(select(User).where(User.email == email)).first() is not None:
        raise AccountError(f"{email} already has an account")
    user = User(email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalars(select(User).where(User.email == email.strip().lower())).first()
    if user is None:
        # Spend the same time as a real check, so response time does not reveal which emails exist.
        verify_password(password, hash_password("not-a-real-account"))
        return None
    return user if user.is_active and verify_password(password, user.password_hash) else None


def user_for_token(db: Session, token: str) -> User | None:
    if not token.startswith(TOKEN_PREFIX):
        return None
    user = db.scalars(select(User).where(User.token_hash == hash_token(token))).first()
    return user if user is not None and user.is_active else None


def bootstrap_admin(factory: sessionmaker, settings: Settings) -> User | None:
    """Create the first administrator from ADMIN_EMAIL / ADMIN_PASSWORD when no user exists yet."""
    if not (settings.accounts_enabled and settings.admin_email and settings.admin_password):
        return None
    with factory() as db:
        if db.scalar(select(func.count()).select_from(User)):
            return None
        user = create_user(db, settings.admin_email, settings.admin_password, Role.ADMIN)
        log.info("created the first administrator: %s", user.email)
        return user


# ---------------------------------------------------------------- command line


def main(argv: list[str] | None = None, factory: sessionmaker | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m datadigest.accounts", description="Manage user accounts."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="create a user")
    add.add_argument("email")
    add.add_argument("--admin", action="store_true", help="administrators see every dataset and manage users")
    add.add_argument("--password", help="omit to be asked for it (keeps it out of the shell history)")
    commands.add_parser("list", help="show the users")
    args = parser.parse_args(argv)

    if factory is None:
        from datadigest.db import SessionLocal as factory  # noqa: N813 (a sessionmaker, used like a function)
    with factory() as db:
        if args.command == "list":
            for user in db.scalars(select(User).order_by(User.created_at)):
                print(f"{user.email}\t{user.role}\t{'active' if user.is_active else 'disabled'}")
            return 0
        try:
            password = args.password or getpass.getpass("Password: ")
            user = create_user(db, args.email, password, Role.ADMIN if args.admin else Role.MEMBER)
        except AccountError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"created {user.email} ({user.role})")
        if not get_settings().accounts_enabled:
            print("note: accounts are not switched on; set AUTH_MODE=accounts", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
