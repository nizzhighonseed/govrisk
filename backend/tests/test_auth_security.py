"""Tests for the authentication brute-force / rate-limiting hardening.

Covers:
- correct login still works; wrong password returns a generic 401
- repeated failures lock the account; the lockout expires and success clears it
- invalid usernames are indistinguishable from wrong passwords
- request-level throttling of login, register and refresh (with expiring
  windows and state cleanup)
- passwords / JWTs / refresh tokens are never written to audit logs
- concurrent failures cannot bypass the account threshold

All HTTP tests run against isolated temp databases (same pattern as
test_ai_analysis / test_assistant_xss); the developer's govrisk.db and
auth.db are never written. The in-process rate limiter is reset before every
test so the suite cannot leak throttle state between tests, and no external
Redis/server is required.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import auth.lockout as lockout_module
import auth.rate_limit as rate_limit


def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fresh_limiter(max_requests=None, window_seconds=None):
    from config import AUTH_MAX_REQUESTS_PER_WINDOW, AUTH_RATE_LIMIT_WINDOW_SECONDS

    return rate_limit.InMemoryRateLimiter(
        max_requests=max_requests or AUTH_MAX_REQUESTS_PER_WINDOW,
        window_seconds=window_seconds or AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )


def _patch_temp_dbs():
    """Point main + router DB sessions at throwaway SQLite files."""
    global _TMP_ENGINE, _TMP_AUTH_ENGINE
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import database
    import auth.database

    import models  # noqa: F401 - register metadata on Base
    import auth.models  # noqa: F401 - register metadata on AuthBase

    tmpdir = tempfile.mkdtemp(prefix="govrisk-authsec-")
    _TMP_ENGINE = create_engine(
        "sqlite:///" + os.path.join(tmpdir, "test.db"),
        connect_args={"check_same_thread": False},
    )
    _TMP_AUTH_ENGINE = create_engine(
        "sqlite:///" + os.path.join(tmpdir, "auth.db"),
        connect_args={"check_same_thread": False},
    )
    make = sessionmaker(autocommit=False, autoflush=False)
    make.configure(bind=_TMP_ENGINE)
    database.SessionLocal = make
    database.Base.metadata.create_all(bind=_TMP_ENGINE)
    make_auth = sessionmaker(autocommit=False, autoflush=False)
    make_auth.configure(bind=_TMP_AUTH_ENGINE)
    auth.database.AuthSessionLocal = make_auth
    auth.database.AuthBase.metadata.create_all(bind=_TMP_AUTH_ENGINE)


class AuthSecurityApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _patch_temp_dbs()
        from fastapi.testclient import TestClient
        from main import app

        cls.client = TestClient(app)

    def setUp(self):
        rate_limit.limiter = _fresh_limiter()

    def tearDown(self):
        rate_limit.limiter.reset()

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _register(self, email=None, password="testpass123", expect=201):
        email = email or f"auth_{uuid.uuid4().hex[:10]}@govrisk.gov.in"
        r = self.client.post(
            "/api/auth/register",
            json={
                "fullName": "Auth Test User",
                "email": email,
                "password": password,
                "department": "IT",
                "designation": "Testing",
            },
        )
        self.assertEqual(r.status_code, expect, r.text)
        return email, r.json()

    def _login(self, email, password):
        return self.client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )

    def _user_row(self, email):
        from auth.database import AuthSessionLocal
        from auth.models import User

        with AuthSessionLocal() as db:
            user = db.query(User).filter(User.email == email).first()
            if user is None:
                return None
            db.expunge(user)
            return user

    def _failure_state(self, email):
        u = self._user_row(email)
        return {
            "count": u.failed_login_count,
            "last_failed": u.last_failed_login,
            "locked_until": u.locked_until,
        }

    def _set_locked_until(self, email, value):
        from auth.database import AuthSessionLocal
        from auth.models import User

        with AuthSessionLocal() as db:
            user = db.query(User).filter(User.email == email).first()
            user.locked_until = value
            db.commit()

    def _audit_inputs(self):
        from auth.database import AuthSessionLocal
        from auth.models import AuditLog

        with AuthSessionLocal() as db:
            rows = db.query(AuditLog).all()
            return [
                (
                    row.action or "",
                    row.user_id or "",
                    row.target_user_id or "",
                    row.details or "",
                )
                for row in rows
            ]

    def _audit_contains(self, text):
        return any(text in "|".join(part for part in row) for row in self._audit_inputs())

    def _audit_actions_for(self, email):
        u = self._user_row(email)
        if u is None:
            return set()
        return {
            action
            for action, _uid, target, _details in self._audit_inputs()
            if target == u.user_id
        }

    # ------------------------------------------------------------------ #
    # login: basic behavior
    # ------------------------------------------------------------------ #
    def test_correct_credentials_still_succeed(self):
        email, _ = self._register()
        r = self._login(email, "testpass123")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("accessToken", body)
        self.assertIn("refreshToken", body)
        self.assertEqual(body["user"]["email"], email)
        self.assertIn("LOGIN_SUCCESS", self._audit_actions_for(email))

    def test_incorrect_password_generic_failure(self):
        email, _ = self._register()
        r = self._login(email, "wrong-password")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"], "Invalid email or password")
        self.assertNotIn("wrong-password", r.text)

    # ------------------------------------------------------------------ #
    # login: lockout
    # ------------------------------------------------------------------ #
    def test_repeated_failures_trigger_lockout(self):
        email, _ = self._register()
        for _ in range(5):
            r = self._login(email, "wrong")
            self.assertEqual(r.status_code, 401, r.text)
        # locked: even the correct password is rejected with a generic 429
        r = self._login(email, "testpass123")
        self.assertEqual(r.status_code, 429)
        self.assertIn("ACCOUNT_LOCKED", self._audit_actions_for(email))
        state = self._failure_state(email)
        self.assertTrue(state["locked_until"] is not None)

    def test_login_during_lockout_rejected(self):
        email, _ = self._register()
        for _ in range(5):
            self._login(email, "wrong")
        r = self._login(email, "testpass123")
        self.assertEqual(r.status_code, 429)
        # no additional failure was counted while locked
        self.assertEqual(self._failure_state(email)["count"], 5)

    def test_lockout_expires(self):
        email, _ = self._register()
        for _ in range(5):
            self._login(email, "wrong")
        self._set_locked_until(email, _naive_utc_now() - timedelta(minutes=1))
        r = self._login(email, "testpass123")
        self.assertEqual(r.status_code, 200, r.text)
        state = self._failure_state(email)
        self.assertEqual(state["count"], 0)
        self.assertIsNone(state["locked_until"])

    def test_successful_login_resets_failure_state(self):
        email, _ = self._register()
        for _ in range(3):
            self._login(email, "wrong")
        r = self._login(email, "testpass123")
        self.assertEqual(r.status_code, 200, r.text)
        state = self._failure_state(email)
        self.assertEqual(state["count"], 0)
        self.assertIsNone(state["last_failed"])
        self.assertIsNone(state["locked_until"])
        # a new failure begins a fresh sequence, not a continuation
        self.assertEqual(self._login(email, "wrong").status_code, 401)
        self.assertEqual(self._failure_state(email)["count"], 1)

    # ------------------------------------------------------------------ #
    # login: no account enumeration
    # ------------------------------------------------------------------ #
    def test_invalid_username_identical_to_wrong_password(self):
        ghost = f"ghost_{uuid.uuid4().hex[:8]}@govrisk.gov.in"
        unknown = self._login(ghost, "some-password")
        self.assertEqual(unknown.status_code, 401)
        email, _ = self._register()
        known_wrong = self._login(email, "some-password")
        self.assertEqual(known_wrong.status_code, 401)
        self.assertEqual(unknown.json().get("detail"), known_wrong.json().get("detail"))
        self.assertEqual(unknown.json().get("detail"), "Invalid email or password")
        neither = unknown.json().get("detail") or known_wrong.json().get("detail")
        self.assertNotIn("exist", neither.lower())
        self.assertNotIn("not found", neither.lower())
        self.assertNotIn(email, unknown.text)

    # ------------------------------------------------------------------ #
    # rate limiting
    # ------------------------------------------------------------------ #
    def test_excessive_login_throttled(self):
        rate_limit.limiter = _fresh_limiter(max_requests=3, window_seconds=60)
        email, _ = self._register()
        for _ in range(3):
            self.assertEqual(self._login(email, "wrong").status_code, 401)
        r = self._login(email, "wrong")
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r.headers)
        # request-level throttle, not account lockout (only 3 DB failures)
        self.assertEqual(self._failure_state(email)["count"], 3)
        self.assertNotIn("ACCOUNT_LOCKED", self._audit_actions_for(email))

    def test_excessive_registration_throttled(self):
        rate_limit.limiter = _fresh_limiter(max_requests=2, window_seconds=60)
        self._register()
        self._register()
        r = self.client.post(
            "/api/auth/register",
            json={
                "fullName": "Throttled",
                "email": f"t{uuid.uuid4().hex[:8]}@govrisk.gov.in",
                "password": "testpass123",
            },
        )
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r.headers)

    def test_excessive_refresh_throttled(self):
        _email, data = self._register()
        refresh = data["refreshToken"]
        # a normal refresh still works inside the budget
        ok = self.client.post("/api/auth/refresh", json={"refreshToken": refresh})
        self.assertEqual(ok.status_code, 200, ok.text)
        rate_limit.limiter = _fresh_limiter(max_requests=2, window_seconds=60)
        self.client.post("/api/auth/refresh", json={"refreshToken": refresh})
        self.client.post("/api/auth/refresh", json={"refreshToken": refresh})
        r = self.client.post("/api/auth/refresh", json={"refreshToken": refresh})
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r.headers)
        # a different (noise) token is throttled identically - token not leaked
        end = self.client.post("/api/auth/refresh", json={"refreshToken": "garbage"})
        self.assertEqual(end.status_code, 429)

    def test_expired_rate_limit_window_allows_requests_again(self):
        class _Clock:
            def __init__(self, start):
                self.value = start

            def __call__(self):
                return self.value

        clock = _Clock(time.time())
        rate_limit.limiter = rate_limit.InMemoryRateLimiter(
            max_requests=2, window_seconds=2, clock=clock
        )
        email, _ = self._register()
        self.assertEqual(self._login(email, "wrong").status_code, 401)
        self.assertEqual(self._login(email, "wrong").status_code, 401)
        self.assertEqual(self._login(email, "wrong").status_code, 429)
        # advance past the fixed window: the budget resets
        clock.value += 2.5
        r = self._login(email, "wrong")
        self.assertEqual(r.status_code, 401, r.text)

    def test_rate_limit_state_cleaned_up(self):
        lim = rate_limit.InMemoryRateLimiter(max_requests=5, window_seconds=60)
        now = time.time()
        for i in range(50):
            lim.hit(f"probe-key-{i}", now=now)
        self.assertEqual(lim.bucket_count(), 50)
        lim.prune(now=now + 120.0 + 1.0)
        self.assertEqual(lim.bucket_count(), 0)

    # ------------------------------------------------------------------ #
    # audit logging: no secrets
    # ------------------------------------------------------------------ #
    def test_passwords_never_written_to_audit_logs(self):
        email, _ = self._register()
        secret = "super-secret-password-57"
        for _ in range(3):
            self._login(email, secret)
        self.assertFalse(self._audit_contains(secret))

    def test_tokens_never_written_to_audit_logs(self):
        email, data = self._register()
        access = data["accessToken"]
        refresh = data["refreshToken"]
        self.assertEqual(self._login(email, "testpass123").status_code, 200)
        self.client.post("/api/auth/refresh", json={"refreshToken": refresh})
        for token in (access, refresh):
            self.assertFalse(self._audit_contains(token))
        self.assertFalse(self._audit_contains("Bearer"))

    # ------------------------------------------------------------------ #
    # concurrency
    # ------------------------------------------------------------------ #
    def test_concurrent_failures_cannot_bypass_lockout(self):
        from auth.models import User
        from auth.database import AuthBase
        from auth.security import hash_password
        from auth.lockout import register_failed_attempt
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        _engine = create_engine(
            "sqlite:///" + path,
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        AuthBase.metadata.create_all(bind=_engine)
        make = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
        email = f"conc_{uuid.uuid4().hex[:8]}@govrisk.gov.in"
        with make() as s:
            u = User(
                id=uuid.uuid4().hex,
                user_id=f"USR-{uuid.uuid4().hex[:6]}",
                full_name="Concurrency Probe",
                email=email,
                password_hash=hash_password("x"),
                role="viewer",
                is_active=True,
            )
            s.add(u)
            s.commit()

        errors = []

        def worker():
            make_local = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
            try:
                with make_local() as s:
                    uu = s.query(User).filter(User.email == email).one()
                    register_failed_attempt(s, uu)
                    s.commit()
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        with make() as s:
            uu = s.query(User).filter(User.email == email).one()
            # every failure was recorded - no lost increments
            self.assertEqual(uu.failed_login_count, 8)
            # and the account is locked (threshold reached)
            self.assertIsNotNone(uu.locked_until)
            self.assertGreater(uu.locked_until, _naive_utc_now())
        try:
            os.unlink(path)
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # regression: pre-existing behavior preserved
    # ------------------------------------------------------------------ #
    def test_deactivated_account_still_forbidden(self):
        email, _ = self._register()
        u = self._user_row(email)
        from auth.database import AuthSessionLocal
        from auth.models import User

        with AuthSessionLocal() as db:
            user = db.query(User).filter(User.id == u.id).first()
            user.is_active = False
            db.commit()
        r = self._login(email, "testpass123")
        self.assertEqual(r.status_code, 403)


class LockoutUnitTestCase(unittest.TestCase):
    def test_register_failed_attempt_threshold_math(self):
        from auth.models import User
        from auth.database import AuthBase
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine("sqlite://")
        AuthBase.metadata.create_all(bind=engine)
        make = sessionmaker(bind=engine)
        with make() as s:
            u = User(
                id="u1", user_id="USR-U1", full_name="Unit",
                email=f"unit{uuid.uuid4().hex[:8]}@govrisk.gov.in",
                password_hash="x", role="viewer", is_active=True,
            )
            s.add(u)
            s.commit()
            now = _naive_utc_now()
            self.assertFalse(lockout_module.register_failed_attempt(s, u, now))
            self.assertFalse(lockout_module.register_failed_attempt(s, u, now))
            self.assertFalse(lockout_module.register_failed_attempt(s, u, now))
            self.assertFalse(lockout_module.register_failed_attempt(s, u, now))
            # 5th failure crosses the threshold -> locked
            self.assertTrue(lockout_module.register_failed_attempt(s, u, now))
            self.assertTrue(lockout_module.is_locked(u))
            self.assertEqual(u.failed_login_count, 5)
            s.commit()

            # streak resets once the previous failure is older than the
            # lockout duration (no permanent lockout from old streaks)
            u2 = User(
                id="u2", user_id="USR-U2", full_name="Unit",
                email=f"unit2{uuid.uuid4().hex[:8]}@govrisk.gov.in",
                password_hash="x", role="viewer", is_active=True,
                failed_login_count=4,
                last_failed_login=now - timedelta(minutes=60),
            )
            s.add(u2)
            s.commit()
            now2 = _naive_utc_now()
            from auth.models import User as UserModel

            with make() as s3:
                u3 = s3.query(UserModel).filter(UserModel.id == "u2").first()
                locked = lockout_module.register_failed_attempt(s3, u3, now2)
                self.assertEqual(u3.failed_login_count, 1)
                self.assertFalse(locked)
                s3.commit()


class RateLimiterUnitTestCase(unittest.TestCase):
    def test_fixed_window_and_retry_after(self):
        lim = rate_limit.InMemoryRateLimiter(max_requests=2, window_seconds=60)
        now = 1_700_000_000.0
        self.assertEqual(lim.hit("k", now=now), (True, 0))
        self.assertEqual(lim.hit("k", now=now), (True, 0))
        allowed, retry_after = lim.hit("k", now=now)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry_after, 1)
        # new window resets the budget
        self.assertTrue(lim.hit("k", now=now + 60.0)[0])

    def test_distinct_keys_share_nothing(self):
        lim = rate_limit.InMemoryRateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(lim.hit("a", now=1000.0)[0])
        self.assertTrue(lim.hit("b", now=1000.0)[0])
        self.assertEqual(lim.bucket_count(), 2)


if __name__ == "__main__":
    unittest.main()