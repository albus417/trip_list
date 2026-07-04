from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from uuid import uuid4
import re
import secrets
import string


def new_id() -> str:
    return str(uuid4())


def clean_email(email: str) -> str:
    return (email or "").strip().lower().replace(" ", "")


def yen(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def today_iso() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hash_passcode(passcode: str) -> str:
    return sha256((passcode or "").strip().encode("utf-8")).hexdigest()


def make_invite_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def safe_filename(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name or "file")
    return name[:120]


def sort_key_date_time(row: dict) -> tuple[str, str]:
    return (row.get("date") or "9999-99-99", row.get("time") or "99:99")
