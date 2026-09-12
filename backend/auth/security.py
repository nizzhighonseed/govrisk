import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
from jose import JWTError, jwt

from config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    REFRESH_TOKEN_EXPIRE_DAYS,
)


def generate_id() -> str:
    return str(uuid.uuid4())


# Ambiguous characters (0/O, 1/l/I) are excluded so a printed/typed temporary
# password cannot be mis-copied. The 63-character alphabet gives ~5.98 bits of
# entropy per character, so a 16-character temporary password has ~96 bits -
# far stronger than the previous "GovRisk@" + 4-digit system (10^4 = ~13 bits)
# and immune to the old prefix/predictability attacks.
TEMP_PASSWORD_ALPHABET = (
    "ABCDEFGHJKLMNPQRSTUVWXYZ"
    "abcdefghijkmnpqrstuvwxyz"
    "23456789"
    "@#$%&*+="
)
TEMP_PASSWORD_LENGTH = 16


def generate_temporary_password(length: int = TEMP_PASSWORD_LENGTH) -> str:
    """Generate a cryptographically secure temporary password.

    Uses only the standard-library ``secrets`` module (no ``random``, no
    timestamps, no user-derived input), so the output is unpredictable even
    against an attacker who knows the username, email, user ID, creation time
    and server behaviour.
    """
    return "".join(secrets.choice(TEMP_PASSWORD_ALPHABET) for _ in range(length))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# Burned once at import so a login against a NON-EXISTENT account spends the
# same bcrypt cost as a real account: an attacker cannot use response timing
# to tell "no such account" from "wrong password".
DUMMY_PASSWORD_HASH = hash_password("<govrisk-timing-equalizer>")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def safe_verify_password(plain_password: str, hashed_password: str) -> bool:
    """verify_password that never raises on malformed/oversized input.

    bcrypt rejects passwords longer than 72 bytes with ValueError; treating
    that as "not a match" keeps the login path returning a generic 401
    instead of an internal error 500 (and applies identically to real and
    dummy hashes, so it leaks nothing).
    """
    try:
        return verify_password(plain_password, hashed_password)
    except ValueError:
        return False


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": subject,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None
