"""Account-level brute-force lockout for the existing `users` table.

Lockout state lives directly on the User model in auth.db - there is no
second authentication database. The fields added alongside the existing
model are:

* failed_login_count  - consecutive failed logins in the current streak
* last_failed_login   - timestamp of the last failed login (naive UTC)
* locked_until        - instant the account stops being locked (naive UTC)

TIMESTAMPS
-----------
The project stores DateTimes in SQLite, which round-trips them as *naive*
values. All lockout math therefore uses naive UTC values so comparisons in
Python and SQL see the same timezone-less clock.

CONCURRENCY / RACE CONDITIONS
-----------------------------
Failed attempts are recorded with a single atomic SQL UPDATE:

    failed_login_count = CASE WHEN <streak stale> THEN 1
                              ELSE failed_login_count + 1 END

The increment happens inside the database engine (not Python read-
modify-write), so two concurrent requests can never both read the old value
and lose an increment. SQLite serialises writers, so the counter advances
exactly once per processed failure regardless of interleaving.

STREAK RESET / NO PERMANENT LOCKOUT
-----------------------------------
A failure resets the streak to 1 (instead of incrementing) when the previous
failure is older than the lockout duration. Combined with "the first
attempt after the lockout window expires resets the streak", a legitimate
user can never be permanent-locked by months of sporadic typos.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, or_, update
from sqlalchemy.orm import Session

from config import AUTH_LOCKOUT_MINUTES, AUTH_MAX_FAILED_ATTEMPTS
from auth.models import User


def utcnow_naive() -> datetime:
    """Naive UTC now, matching how SQLite round-trips DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def lockout_duration() -> timedelta:
    return timedelta(minutes=AUTH_LOCKOUT_MINUTES)


def is_locked(user: User, now: datetime = None) -> bool:
    """True while the account's lockout timer has not expired."""
    now = now if now is not None else utcnow_naive()
    return bool(user.locked_until and user.locked_until > now)


def register_failed_attempt(db: Session, user: User, now: datetime = None) -> bool:
    """Atomically record one failed login for `user`.

    Returns True when this failure pushed the account into lockout, so the
    caller can audit the transition. Idempotent-ish: repeated calls simply
    advance the counter; the caller decides when to stop calling.
    """
    now = now if now is not None else utcnow_naive()
    stale_cutoff = now - lockout_duration()
    db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            failed_login_count=case(
                (
                    or_(
                        User.last_failed_login.is_(None),
                        User.last_failed_login < stale_cutoff,
                    ),
                    1,
                ),
                else_=User.failed_login_count + 1,
            ),
            last_failed_login=now,
        )
    )
    db.flush()
    db.refresh(user)
    if user.failed_login_count >= AUTH_MAX_FAILED_ATTEMPTS:
        user.locked_until = now + lockout_duration()
        return True
    return False


def clear_failed_attempts(db: Session, user: User) -> None:
    """Reset failure state on a successful authentication."""
    user.failed_login_count = 0
    user.last_failed_login = None
    user.locked_until = None