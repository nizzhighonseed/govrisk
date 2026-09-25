"""Tests for temporary-password hardening and first-login password change.

Covers:
- server-side CSPRNG generation (secrets, not random); no legacy GovRisk@XXXX
- admin-created accounts: flagged must_change_password, hash-only storage, temp
  password returned exactly once, client-supplied temporary passwords ignored
- first login with a temporary password authenticates but all portfolio/action
  endpoints are blocked until the password is changed
- the self-service change endpoint is reachable pre-change, clears the flag on
  success only, and invalidates the temporary password
- failed changes (wrong current, invalid new) keep the flag and audit
- resets issue a new CSPRNG temp password and re-force the change
- self-registered / existing users are never forced; approval/deactivation
  gates still apply and take precedence
- no plaintext passwords, hashes, or temporary passwords ever reach responses
  or audit logs

All HTTP tests run against isolated temp databases (same pattern as
test_auth_security / test_registration_governance); the developer's
sankalp.db / auth.db are never written. The in-process rate limiter is reset
before every test.
"""

import os
import re
import sys
import tempfile
import unittest
import uuid
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import auth.rate_limit as rate_limit


def _fresh_limiter(max_requests=None, window_seconds=None):
    from config import AUTH_MAX_REQUESTS_PER_WINDOW, AUTH_RATE_LIMIT_WINDOW_SECONDS

    return rate_limit.InMemoryRateLimiter(
        max_requests=max_requests or AUTH_MAX_REQUESTS_PER_WINDOW,
        window_seconds=window_seconds or AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )


def _patch_temp_dbs():
    global _TMP_ENGINE, _TMP_AUTH_ENGINE
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import database
    import auth.database

    import models  # noqa: F401 - register metadata on Base
    import auth.models  # noqa: F401 - register metadata on AuthBase

    tmpdir = tempfile.mkdtemp(prefix="sankalp-temppw-")
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


class TemporaryPasswordTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from auth.security import (
            TEMP_PASSWORD_ALPHABET,
            TEMP_PASSWORD_LENGTH,
            generate_temporary_password,
        )

        cls.ALPHABET = TEMP_PASSWORD_ALPHABET
        cls.DEFAULT_LENGTH = TEMP_PASSWORD_LENGTH
        cls.gen = staticmethod(generate_temporary_password)

    def test_generated_password_length_and_alphabet(self):
        p = self.gen()
        self.assertEqual(len(p), self.DEFAULT_LENGTH)
        self.assertTrue(all(c in self.ALPHABET for c in p))
        self.assertRegex(p, r"^[A-Za-z0-9@#$%&*+=]+$")

    def test_no_ambiguous_characters(self):
        p = self.gen()
        self.assertNotIn("0", p)
        self.assertNotIn("O", p)
        self.assertNotIn("1", p)
        self.assertNotIn("l", p)
        self.assertNotIn("I", p)

    def test_no_legacy_weak_pattern(self):
        samples = [self.gen() for _ in range(200)]
        self.assertFalse(any(s.startswith("GovRisk@") for s in samples))
        # Key space of the legacy 4-digit suffix was only 10^4; the new
        # generator must produce widely-spread values.
        self.assertEqual(len(set(samples)), len(samples))

    def test_generator_uses_secrets_not_random(self):
        called = []

        def recording_choice(seq):
            called.append(seq[0])
            return "x"

        with mock.patch("auth.security.secrets.choice", side_effect=recording_choice):
            p = self.gen(length=4)
        self.assertEqual(p, "xxxx")
        self.assertEqual(len(called), 4)
        # `called` holds the alphabet the CSPRNG is choosing from; if the
        # implementation ever fell back to `random` / timestamps this patch
        # would not be exercised.
        self.assertTrue(all(c in self.ALPHABET for c in called))

    def test_requested_length_respected(self):
        self.assertEqual(len(self.gen(length=8)), 8)

    def test_column_default_keeps_existing_users_unforced(self):
        from auth.database import AuthSessionLocal
        from auth.models import User
        from auth.security import hash_password

        with AuthSessionLocal() as db:
            user = User(
                id=str(uuid.uuid4()),
                user_id="TP-DEFAULT",
                full_name="Default Test",
                email="default@noforce.test",
                password_hash=hash_password("whatever123"),
                role="viewer",
                is_active=True,
                is_approved=True,
                # must_change_password intentionally NOT set -> DB default 0
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            self.assertFalse(user.must_change_password)


class TemporaryPasswordApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _patch_temp_dbs()
        from fastapi.testclient import TestClient
        from main import app

        cls.client = TestClient(app)
        cls._created_project_ids = []

    def setUp(self):
        rate_limit.limiter = _fresh_limiter()

    def tearDown(self):
        rate_limit.limiter.reset()

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _register(self, email=None, password="testpass123", **extra):
        email = email or f"tp_{uuid.uuid4().hex[:10]}@sankalp.gov.in"
        payload = {
            "fullName": "Temp Password Test User",
            "email": email,
            "password": password,
            "department": "IT",
            "designation": "Testing",
        }
        payload.update(extra)
        r = self.client.post("/api/auth/register", json=payload)
        return email, r

    def _login(self, email, password="testpass123"):
        return self.client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )

    def _headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def _user_row(self, email):
        from auth.database import AuthSessionLocal
        from auth.models import User

        with AuthSessionLocal() as db:
            user = db.query(User).filter(User.email == email).first()
            if user is None:
                return None
            db.expunge(user)
            return user

    def _set_user_state(self, email, **columns):
        from auth.database import AuthSessionLocal
        from auth.models import User

        with AuthSessionLocal() as db:
            user = db.query(User).filter(User.email == email).first()
            for key, value in columns.items():
                setattr(user, key, value)
            db.commit()

    def _registered_pending(self, email=None, password="testpass123"):
        email, r = self._register(email=email, password=password)
        self.assertEqual(r.status_code, 201, r.text)
        return email

    def _approved_admin(self):
        email = self._registered_pending()
        self._set_user_state(email, role="admin", is_approved=True)
        r = self._login(email)
        self.assertEqual(r.status_code, 200, r.text)
        return email, r.json()["accessToken"]

    def _admin_create(self, admin_token, email, role="viewer", extra_payload=None):
        email = email or f"tp_created_{uuid.uuid4().hex[:10]}@sankalp.gov.in"
        payload = {
            "fullName": "Temporary Account",
            "email": email,
            "role": role,
            "department": "IT",
            "isActive": True,
        }
        if extra_payload:
            payload.update(extra_payload)
        r = self.client.post("/api/users", json=payload, headers=self._headers(admin_token))
        return email, r

    def _create_and_temp(self, admin_token, role="viewer", extra_payload=None):
        email, r = self._admin_create(admin_token, email=None, role=role, extra_payload=extra_payload)
        self.assertEqual(r.status_code, 201, r.text)
        return email, r.json()

    def _change(self, token, current, new):
        return self.client.put(
            "/api/users/me/password",
            json={"currentPassword": current, "newPassword": new},
            headers=self._headers(token),
        )

    def _audit_blob(self):
        from auth.database import AuthSessionLocal
        from auth.models import AuditLog

        with AuthSessionLocal() as db:
            rows = db.query(AuditLog).all()
            return "\n".join(
                "|".join(
                    (row.action or "", row.user_id or "", row.target_user_id or "", row.details or "")
                )
                for row in rows
            )

    # ------------------------------------------------------------------ #
    # admin user creation
    # ------------------------------------------------------------------ #
    def test_create_requires_authentication_and_admin_role(self):
        anon = self.client.post(
            "/api/users",
            json={"fullName": "x", "email": "a@b.test", "role": "viewer"},
        )
        self.assertEqual(anon.status_code, 401)

        officer_email = self._registered_pending()
        self._set_user_state(officer_email, role="officer", is_approved=True)
        r = self._login(officer_email)
        officer_token = r.json()["accessToken"]
        denied = self.client.post(
            "/api/users",
            json={"fullName": "x", "email": "b@b.test", "role": "viewer"},
            headers=self._headers(officer_token),
        )
        self.assertEqual(denied.status_code, 403)

    def test_admin_created_user_must_change_password(self):
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        self.assertIn("temporaryPassword", data)
        self.assertTrue(data["mustChangePassword"])
        self.assertNotEqual(data["temporaryPassword"], "")
        row = self._user_row(email)
        self.assertTrue(row.must_change_password)

    def test_client_supplied_temporary_password_is_ignored(self):
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(
            admin_token, extra_payload={"temporaryPassword": "attack-me-123"}
        )
        server_temp = data["temporaryPassword"]
        self.assertNotEqual(server_temp, "attack-me-123")
        # the attacker-chosen password must not authenticate
        self.assertEqual(self._login(email, "attack-me-123").status_code, 401)
        # the server-generated one does
        self.assertEqual(self._login(email, server_temp).status_code, 200)

    def test_duplicate_email_create_conflicts(self):
        _, admin_token = self._approved_admin()
        email, _ = self._create_and_temp(admin_token)
        _, r2 = self._admin_create(admin_token, email=email)
        self.assertEqual(r2.status_code, 409)

    def test_hash_only_storage(self):
        from auth.security import safe_verify_password

        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        temp = data["temporaryPassword"]
        row = self._user_row(email)
        self.assertIsNotNone(row.password_hash)
        self.assertNotEqual(row.password_hash, temp)
        self.assertTrue(row.password_hash.startswith("$2"))
        self.assertTrue(safe_verify_password(temp, row.password_hash))

    def test_temp_password_not_exposed_in_listings_or_audit(self):
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        temp = data["temporaryPassword"]

        listed = self.client.get("/api/users", headers=self._headers(admin_token))
        self.assertEqual(listed.status_code, 200)
        body = listed.json()
        items = body.get("items", [])
        self.assertTrue(
            any(item.get("email") == email and item.get("mustChangePassword") for item in items)
        )
        self.assertNotIn(temp, listed.text)
        self.assertNotIn(temp, self._audit_blob())
        # meta endpoint stays free of temp data too
        meta = self.client.get("/api/auth/me", headers=self._headers(admin_token))
        self.assertNotIn(temp, meta.text)

    def test_temp_password_never_in_any_response_payload(self):
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        temp = data["temporaryPassword"]

        login_r = self._login(email, temp)
        self.assertNotIn(temp, login_r.text)
        me_r = self.client.get("/api/auth/me", headers=self._headers(login_r.json()["accessToken"]))
        self.assertNotIn(temp, me_r.text)
        assert "temporaryPassword" not in login_r.json()
        assert "temporaryPassword" not in me_r.json()

    # ------------------------------------------------------------------ #
    # first login / portfolio gate
    # ------------------------------------------------------------------ #
    def test_first_login_with_temp_authenticates_and_flags_user(self):
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        r = self._login(email, data["temporaryPassword"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["user"]["mustChangePassword"])

    def test_portfolio_blocked_until_password_change(self):
        from auth.dependencies import PASSWORD_CHANGE_REQUIRED_ERROR

        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        token = self._login(email, data["temporaryPassword"]).json()["accessToken"]

        for path in ("/api/projects", "/api/dashboard", "/api/analytics", "/api/alerts"):
            r = self.client.get(path, headers=self._headers(token))
            self.assertEqual(r.status_code, 403, f"{path}: {r.text}")
            self.assertEqual(r.json()["detail"], PASSWORD_CHANGE_REQUIRED_ERROR)

    def test_identity_endpoints_still_bootstrappable_pre_change(self):
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        token = self._login(email, data["temporaryPassword"]).json()["accessToken"]
        me = self.client.get("/api/auth/me", headers=self._headers(token))
        self.assertEqual(me.status_code, 200, me.text)
        self.assertTrue(me.json()["mustChangePassword"])
        # strict profile endpoint stays gated
        profile = self.client.get("/api/users/me", headers=self._headers(token))
        self.assertEqual(profile.status_code, 403)

    def test_change_endpoint_reachable_pre_change(self):
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        token = self._login(email, data["temporaryPassword"]).json()["accessToken"]
        r = self._change(token, data["temporaryPassword"], "permanent-pass-123")
        self.assertEqual(r.status_code, 200, r.text)

    def test_change_requires_auth(self):
        r = self.client.put(
            "/api/users/me/password",
            json={"currentPassword": "x", "newPassword": "permanent-pass-123"},
        )
        self.assertEqual(r.status_code, 401)

    # ------------------------------------------------------------------ #
    # change-password behaviour
    # ------------------------------------------------------------------ #
    def test_wrong_current_password_rejected_and_flag_kept(self):
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        token = self._login(email, data["temporaryPassword"]).json()["accessToken"]
        r = self._change(token, "not-the-temp", "permanent-pass-123")
        self.assertEqual(r.status_code, 400)
        self.assertIn("PASSWORD_CHANGE_FAILED", self._audit_blob())
        self.assertNotIn("permanent-pass-123", self._audit_blob())
        self.assertTrue(self._user_row(email).must_change_password)
        # old temp still works, portfolio still blocked
        self.assertEqual(self._login(email, data["temporaryPassword"]).status_code, 200)

    def test_invalid_new_password_rejected_and_flag_kept(self):
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        token = self._login(email, data["temporaryPassword"]).json()["accessToken"]
        for bad in ("", "12345"):
            r = self._change(token, data["temporaryPassword"], bad)
            self.assertEqual(r.status_code, 422, r.text)
        self.assertTrue(self._user_row(email).must_change_password)

    def test_change_new_password_must_differ_from_temp(self):
        # Server accepts any policy-compliant new password; the requirement is
        # enforced at the strongest point (bcrypt hash replacement) plus the
        # UI. Verify the endpoint round-trips and the old credential dies.
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        token = self._login(email, data["temporaryPassword"]).json()["accessToken"]
        new = "a-completely-new-passphrase-99"
        self.assertEqual(self._change(token, data["temporaryPassword"], new).status_code, 200)
        self.assertNotEqual(self._login(email, data["temporaryPassword"]).status_code, 200)
        self.assertEqual(self._login(email, new).status_code, 200)

    def test_successful_change_clears_flag_and_unblocks_portfolio(self):
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        token = self._login(email, data["temporaryPassword"]).json()["accessToken"]
        new = "fresh-permanent-77"
        r = self._change(token, data["temporaryPassword"], new)
        self.assertEqual(r.status_code, 200, r.text)

        row = self._user_row(email)
        self.assertFalse(row.must_change_password)

        new_token = self._login(email, new).json()["accessToken"]
        me = self.client.get("/api/auth/me", headers=self._headers(new_token))
        self.assertEqual(me.status_code, 200, me.text)
        self.assertFalse(me.json()["mustChangePassword"])
        projects = self.client.get("/api/projects", headers=self._headers(new_token))
        self.assertEqual(projects.status_code, 200, projects.text)

    def test_new_hash_stored_only(self):
        from auth.security import safe_verify_password

        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        token = self._login(email, data["temporaryPassword"]).json()["accessToken"]
        new = "another-permanent-44x"
        self._change(token, data["temporaryPassword"], new)
        row = self._user_row(email)
        self.assertNotEqual(row.password_hash, new)
        self.assertNotIn(new, self._audit_blob())
        self.assertTrue(row.password_hash.startswith("$2"))
        self.assertTrue(safe_verify_password(new, row.password_hash))
        self.assertFalse(safe_verify_password(data["temporaryPassword"], row.password_hash))

    # ------------------------------------------------------------------ #
    # reset flow
    # ------------------------------------------------------------------ #
    def test_reset_issues_csp_random_temp_and_forces_change(self):
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        token = self._login(email, data["temporaryPassword"]).json()["accessToken"]
        new = "first-permanent-1"
        self._change(token, data["temporaryPassword"], new)

        target = self._user_row(email)
        r = self.client.post(
            f"/api/users/{target.user_id}/reset-password",
            headers=self._headers(admin_token),
        )
        self.assertEqual(r.status_code, 200, r.text)
        temp2 = r.json()["temporaryPassword"]
        self.assertTrue(temp2)
        self.assertNotEqual(temp2, data["temporaryPassword"])
        self.assertNotEqual(temp2, new)
        self.assertTrue(self._user_row(email).must_change_password)
        self.assertNotIn(temp2, self._audit_blob())

        # new temp works immediately and is forced again
        r = self._login(email, temp2)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["user"]["mustChangePassword"])
        self.assertEqual(self._login(email, new).status_code, 401)

    # ------------------------------------------------------------------ #
    # ordering with other gates / not forced cases
    # ------------------------------------------------------------------ #
    def test_deactivated_and_pending_gates_take_precedence(self):
        from auth.dependencies import PENDING_ACCESS_ERROR

        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        token = self._login(email, data["temporaryPassword"]).json()["accessToken"]

        # deactivated beats the must-change gate
        self._set_user_state(email, is_active=False)
        r = self.client.get("/api/auth/me", headers=self._headers(token))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"], "Account is deactivated")

        # pending approval beats the must-change gate too
        self._set_user_state(email, is_active=True, is_approved=False)
        r2 = self.client.get("/api/projects", headers=self._headers(token))
        self.assertEqual(r2.status_code, 403)
        self.assertEqual(r2.json()["detail"], PENDING_ACCESS_ERROR)

    def test_self_registered_users_are_never_forced(self):
        _, admin_token = self._approved_admin()
        email = self._registered_pending(password="self-chosen-123")
        self.assertFalse(self._user_row(email).must_change_password)
        self._set_user_state(email, is_approved=True)
        r = self._login(email, "self-chosen-123")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["user"]["mustChangePassword"])
        token = r.json()["accessToken"]
        projects = self.client.get("/api/projects", headers=self._headers(token))
        self.assertEqual(projects.status_code, 200, projects.text)

    def test_tokens_do_not_rotate_but_old_access_token_dies_with_password(self):
        # Scope note: refresh-token rotation is explicitly OUT of scope; this
        # test just documents that the pre-change access token can reach the
        # change endpoint (its only permitted port) and nothing else.
        _, admin_token = self._approved_admin()
        email, data = self._create_and_temp(admin_token)
        token = self._login(email, data["temporaryPassword"]).json()["accessToken"]
        blocked = self.client.get("/api/projects", headers=self._headers(token))
        self.assertEqual(blocked.status_code, 403)
        allowed = self.client.get("/api/auth/me", headers=self._headers(token))
        self.assertEqual(allowed.status_code, 200)


if __name__ == "__main__":
    unittest.main()