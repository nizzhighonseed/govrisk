"""Tests for registration governance and portfolio access control.

Covers:
- self-registration creates a PENDING (unapproved) account - no portfolio access
- a client-supplied role can never escalate privileges (always viewer + pending)
- registration no longer leaks "email already exists" (duplicate -> identical 201)
- registration rate limiting is preserved
- every protected portfolio endpoint (projects, alerts, dashboard, analytics,
  risk map, assistant, AI, project updates) returns 403 for a pending account
- admin-only approval workflow (self-approval blocked, role unchanged, active/
  inactive handled safely, deactivated accounts still blocked)
- existing / demo users are never locked out by the approval model (default
  is_approved=True)
- RBAC laid on top of approval still applies
- audit logs never contain passwords or tokens; denied access / denied admin
  actions are recorded

All HTTP tests run against isolated temp databases (same pattern as
test_auth_security); the developer's sankalp.db / auth.db are never written.
The in-process rate limiter is reset before every test.
"""

import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import auth.rate_limit as rate_limit

try:
    from tests.test_risk_service import make_project
except ImportError:  # pragma: no cover - start-in-subdir variant
    from test_risk_service import make_project


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

    tmpdir = tempfile.mkdtemp(prefix="sankalp-reggov-")
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


class RegistrationGovernanceApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _patch_temp_dbs()
        from fastapi.testclient import TestClient
        from main import app

        cls.client = TestClient(app)
        cls._created_project_ids = []

    @classmethod
    def tearDownClass(cls):
        from database import SessionLocal
        from models import Project

        with SessionLocal() as db:
            for project in db.query(Project).filter(
                Project.id.in_(cls._created_project_ids)
            ).all():
                db.delete(project)
            db.commit()

    def setUp(self):
        rate_limit.limiter = _fresh_limiter()

    def tearDown(self):
        rate_limit.limiter.reset()

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _register(self, email=None, password="testpass123", **extra):
        email = email or f"gov_{uuid.uuid4().hex[:10]}@sankalp.gov.in"
        payload = {
            "fullName": "Governance Test User",
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

    def _seed_project(self, pid=None) -> str:
        from database import SessionLocal

        p = make_project(
            id=pid or f"RG-{uuid.uuid4().hex[:6]}",
            name=f"Governance Project {uuid.uuid4().hex[:6]}",
            state="Karnataka",
            cost_overrun_probability=20,
            delay_probability=30,
            implementation_risk=25,
            risk_score=10,
            risk_level="LOW",
        )
        with SessionLocal() as db:
            db.add(p)
            db.flush()
            project_id = p.id
            db.commit()
        self._created_project_ids.append(project_id)
        return project_id

    def _register_pending(self, email=None, password="testpass123", **payload_extra):
        email, r = self._register(email=email, password=password, **payload_extra)
        self.assertEqual(r.status_code, 201, r.text)
        data = r.json()
        self.assertIn("accessToken", data)
        self.assertIn("refreshToken", data)
        return email, data

    def _approved_admin(self):
        email, data = self._register_pending()
        self._set_user_state(email, role="admin", is_approved=True)
        return email

    def _approved_user(self, role="viewer", email=None):
        email, data = self._register_pending(email=email)
        self._set_user_state(email, role=role, is_approved=True)
        r = self._login(email)
        self.assertEqual(r.status_code, 200, r.text)
        return email, r.json()["accessToken"]

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
    # registration
    # ------------------------------------------------------------------ #
    def test_anonymous_user_can_submit_registration(self):
        email, data = self._register_pending()
        self.assertEqual(data["user"]["email"], email)
        self.assertFalse(data["user"]["isApproved"])
        self.assertIn("REGISTERED", self._audit_actions_for(email))

    def test_self_registered_account_is_pending(self):
        email, _ = self._register_pending()
        u = self._user_row(email)
        self.assertIsNotNone(u)
        self.assertFalse(u.is_approved)
        self.assertTrue(u.is_active)
        self.assertEqual(u.role, "viewer")

    def test_registration_cannot_request_admin_role(self):
        for payload in (
            {"role": "admin"},
            {"role": "officer"},
            {"role": "analyst"},
        ):
            with self.subTest(payload=payload):
                email2, r = self._register(
                    email=f"esc_{uuid.uuid4().hex[:8]}@sankalp.gov.in",
                    **payload,
                )
                self.assertEqual(r.status_code, 201, r.text)
                u = self._user_row(email2)
                self.assertEqual(u.role, "viewer")
                self.assertFalse(u.is_approved)

    def test_client_supplied_role_cannot_escalate(self):
        email, data = self._register_pending(
            email=f"esc2_{uuid.uuid4().hex[:8]}@sankalp.gov.in",
            role="admin",
            isApproved=True,
        )
        u = self._user_row(email)
        self.assertEqual(u.role, "viewer")
        self.assertFalse(u.is_approved)
        self.assertEqual(data["user"]["role"], "viewer")

    def test_registration_rate_limiting_still_works(self):
        rate_limit.limiter = _fresh_limiter(max_requests=2, window_seconds=60)
        self.assertEqual(self._register()[1].status_code, 201)
        self.assertEqual(self._register()[1].status_code, 201)
        _, r = self._register()
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r.headers)

    def test_registration_does_not_issue_a_usable_portfolio_session(self):
        email, data = self._register_pending()
        pid = self._seed_project()
        headers = self._headers(data["accessToken"])
        for method, path, body in (
            ("GET", "/api/projects", None),
            ("GET", f"/api/projects/{pid}", None),
            ("GET", f"/api/projects/{pid}/risk", None),
            ("GET", f"/api/projects/{pid}/updates", None),
            ("GET", "/api/alerts", None),
            ("GET", "/api/dashboard", None),
            ("GET", "/api/analytics", None),
            ("GET", "/api/risk-map", None),
            ("GET", f"/api/ai/projects/{pid}/insights", None),
            ("GET", "/api/ai/health", None),
            ("GET", "/api/auth/me", None),
            ("GET", "/api/users/me", None),
        ):
            with self.subTest(method=method, path=path):
                r = self.client.request(method, path, headers=headers, json=body)
                self.assertEqual(r.status_code, 403, r.text)
                self.assertEqual(r.json().get("detail"), "Account approval is required.")
        # denied access is recorded in the audit trail
        self.assertIn("ACCESS_DENIED_PENDING", self._audit_actions_for(email))

    def test_pending_user_cannot_post_assistant_intelligence(self):
        email, data = self._register_pending()
        r = self.client.post(
            "/api/assistant",
            json={"query": "Which projects are at highest risk?"},
            headers=self._headers(data["accessToken"]),
        )
        self.assertEqual(r.status_code, 403, r.text)

    def test_pending_user_cannot_modify_project_data(self):
        email, data = self._register_pending()
        pid = self._seed_project()
        headers = self._headers(data["accessToken"])
        r = self.client.post(
            f"/api/projects/{pid}/updates",
            json={"updateType": "GENERAL", "content": "staged by pending user"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 403, r.text)
        r = self.client.put(
            f"/api/projects/{pid}",
            json={"name": "Hijacked Project"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 403, r.text)
        r = self.client.post(
            "/api/projects",
            json={
                "name": "Unauthorized Project",
                "ministry": "MoRD",
                "agency": "X",
                "sector": "Transport",
                "state": "Bihar",
                "originalCost": 1,
                "physicalProgress": 0,
                "startDate": "2024-01-01",
                "completionDate": "2027-12-31",
            },
            headers=headers,
        )
        self.assertEqual(r.status_code, 403, r.text)

    def test_duplicate_email_registration_is_not_an_enumeration_oracle(self):
        email = f"dup_{uuid.uuid4().hex[:8]}@sankalp.gov.in"
        self._register_pending(email=email)
        _, second = self._register(email=email)
        self.assertEqual(second.status_code, 201, second.text)
        body = second.json()
        for key in ("accessToken", "refreshToken", "user"):
            self.assertIn(key, body)
        self.assertNotIn("already exists", second.text.lower())
        self.assertNotIn("exist", second.text.lower())
        self.assertNotIn("not found", second.text.lower())
        # still only ONE account exists for that email
        from auth.database import AuthSessionLocal
        from auth.models import User

        with AuthSessionLocal() as db:
            matches = db.query(User).filter(User.email == email).all()
            self.assertEqual(len(matches), 1)
            u = matches[0]
            self.assertFalse(u.is_approved)
            self.assertEqual(u.role, "viewer")

    # ------------------------------------------------------------------ #
    # admin approval
    # ------------------------------------------------------------------ #
    def test_admin_can_approve_a_pending_account(self):
        admin_email = self._approved_admin()
        pending_email, _ = self._register_pending()
        admin_login = self._login(admin_email)
        self.assertEqual(admin_login.status_code, 200)
        admin_token = admin_login.json()["accessToken"]
        pending = self._user_row(pending_email)

        r = self.client.patch(
            f"/api/users/{pending.user_id}/approval",
            json={"isApproved": True},
            headers=self._headers(admin_token),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["isApproved"])
        self.assertTrue(self._user_row(pending_email).is_approved)
        self.assertIn("USER_APPROVED", self._audit_actions_for(pending_email))

    def test_pending_account_gains_access_after_admin_approval(self):
        admin_email = self._approved_admin()
        admin_token = self._login(admin_email).json()["accessToken"]
        pending_email, reg = self._register_pending()
        pid = self._seed_project()
        headers = self._headers(reg["accessToken"])
        self.assertEqual(
            self.client.get("/api/projects", headers=headers).status_code, 403
        )

        pending = self._user_row(pending_email)
        r = self.client.patch(
            f"/api/users/{pending.user_id}/approval",
            json={"isApproved": True},
            headers=self._headers(admin_token),
        )
        self.assertEqual(r.status_code, 200, r.text)
        # the SAME pre-approval JWT now works: state is checked per request
        self.assertEqual(
            self.client.get("/api/projects", headers=headers).status_code, 200
        )

    def test_approval_does_not_change_role(self):
        admin_email = self._approved_admin()
        admin_token = self._login(admin_email).json()["accessToken"]
        pending_email, _ = self._register_pending()
        pending = self._user_row(pending_email)
        r = self.client.patch(
            f"/api/users/{pending.user_id}/approval",
            json={"isApproved": True},
            headers=self._headers(admin_token),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._user_row(pending_email).role, "viewer")

    def test_non_admin_cannot_approve_an_account(self):
        officer_email, officer_token = self._approved_user(role="officer")
        pending_email, _ = self._register_pending()
        pending = self._user_row(pending_email)
        r = self.client.patch(
            f"/api/users/{pending.user_id}/approval",
            json={"isApproved": True},
            headers=self._headers(officer_token),
        )
        self.assertEqual(r.status_code, 403, r.text)
        self.assertFalse(self._user_row(pending_email).is_approved)
        self.assertIn("AUTHORIZATION_DENIED", self._audit_actions_for(officer_email))

    def test_admin_cannot_approve_themselves(self):
        admin_email, admin_token = self._approved_user(role="admin")
        u = self._user_row(admin_email)
        r = self.client.patch(
            f"/api/users/{u.user_id}/approval",
            json={"isApproved": True},
            headers=self._headers(admin_token),
        )
        self.assertEqual(r.status_code, 400, r.text)
        r2 = self.client.patch(
            f"/api/users/{u.user_id}/approval",
            json={"isApproved": False},
            headers=self._headers(admin_token),
        )
        self.assertEqual(r2.status_code, 400, r2.text)

    def test_user_cannot_modify_own_approval_through_public_endpoints(self):
        viewer_email, viewer_token = self._approved_user(role="viewer")
        u = self._user_row(viewer_email)
        r = self.client.patch(
            f"/api/users/{u.user_id}/approval",
            json={"isApproved": True},
            headers=self._headers(viewer_token),
        )
        self.assertEqual(r.status_code, 403, r.text)
        # profile update cannot smuggle approval/role/active-state fields
        r2 = self.client.put(
            "/api/users/me",
            json={"fullName": "Renamed", "isApproved": False, "role": "admin", "isActive": False},
            headers=self._headers(viewer_token),
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        u = self._user_row(viewer_email)
        self.assertEqual(u.full_name, "Renamed")
        self.assertTrue(u.is_approved)
        self.assertEqual(u.role, "viewer")
        self.assertTrue(u.is_active)

    def test_already_approved_and_nonexistent_target_handled_safely(self):
        admin_email, admin_token = self._approved_user(role="admin")
        # nonexistent target -> 404
        r = self.client.patch(
            "/api/users/USR-DOES-NOT-EXIST/approval",
            json={"isApproved": True},
            headers=self._headers(admin_token),
        )
        self.assertEqual(r.status_code, 404, r.text)
        # approving an approved user is idempotent
        viewer_email, _ = self._approved_user(role="viewer")
        u = self._user_row(viewer_email)
        r = self.client.patch(
            f"/api/users/{u.user_id}/approval",
            json={"isApproved": True},
            headers=self._headers(admin_token),
        )
        self.assertEqual(r.status_code, 200, r.text)

    def test_rejecting_a_pending_account_blocks_it(self):
        admin_email, admin_token = self._approved_user(role="admin")
        pending_email, reg = self._register_pending()
        u = self._user_row(pending_email)
        r = self.client.patch(
            f"/api/users/{u.user_id}/approval",
            json={"isApproved": False},
            headers=self._headers(admin_token),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(self._user_row(pending_email).is_approved)
        self.assertIn("USER_REJECTED", self._audit_actions_for(pending_email))
        self.assertEqual(
            self.client.get(
                "/api/projects", headers=self._headers(reg["accessToken"])
            ).status_code,
            403,
        )

    def test_deactivated_approved_account_stays_blocked(self):
        admin_email, admin_token = self._approved_user(role="admin")
        target_email, target_token = self._approved_user(role="viewer")
        self._set_user_state(target_email, is_active=False, is_approved=True)
        u = self._user_row(target_email)
        # admin re-approves: approval alone does not reactivate the account
        r = self.client.patch(
            f"/api/users/{u.user_id}/approval",
            json={"isApproved": True},
            headers=self._headers(admin_token),
        )
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.get("/api/projects", headers=self._headers(target_token))
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json().get("detail"), "Account is deactivated")

    # ------------------------------------------------------------------ #
    # existing users / demo compatibility
    # ------------------------------------------------------------------ #
    def test_migration_default_keeps_existing_users_approved(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from auth.models import User
        from auth.database import AuthBase
        from auth.security import hash_password

        engine = create_engine("sqlite://")
        AuthBase.metadata.create_all(bind=engine)
        make = sessionmaker(bind=engine)
        email = f"legacy_{uuid.uuid4().hex[:8]}@sankalp.gov.in"
        with make() as s:
            u = User(
                id=uuid.uuid4().hex,
                user_id="USR-LEGACY-1",
                full_name="Existing User",
                email=email,
                password_hash=hash_password("testpass123"),
                role="viewer",
                is_active=True,
            )
            # note: is_approved intentionally NOT set -> column default True
            s.add(u)
            s.commit()
            self.assertTrue(u.is_approved)

    def test_existing_demo_user_can_still_access_portfolio(self):
        demo_email, demo_token = self._approved_user(role="viewer")
        self._seed_project()
        r = self.client.get("/api/projects", headers=self._headers(demo_token))
        self.assertEqual(r.status_code, 200, r.text)

    def test_existing_admin_still_works(self):
        admin_email, admin_token = self._approved_user(role="admin")
        r = self.client.get("/api/users", headers=self._headers(admin_token))
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.get("/api/users/stats", headers=self._headers(admin_token))
        self.assertEqual(r.status_code, 200, r.text)

    # ------------------------------------------------------------------ #
    # RBAC on top of approval
    # ------------------------------------------------------------------ #
    def test_rbac_still_applies_after_approval(self):
        _, officer_token = self._approved_user(role="officer")
        _, analyst_token = self._approved_user(role="analyst")
        _, viewer_token = self._approved_user(role="viewer")

        project_payload = {
            "name": f"RBAC Project {uuid.uuid4().hex[:6]}",
            "ministry": "MoRD",
            "agency": f"AGENCY-{uuid.uuid4().hex[:6]}",
            "sector": "Transport",
            "state": "Bihar",
            "originalCost": 1000.0,
            "physicalProgress": 40.0,
            "startDate": "2024-01-01",
            "completionDate": "2027-12-31",
        }
        # officer (approved) can create
        r = self.client.post("/api/projects", json=project_payload, headers=self._headers(officer_token))
        self.assertEqual(r.status_code, 201, r.text)
        self._created_project_ids.append(r.json()["id"])
        # analyst / viewer cannot create
        for label, token in (("analyst", analyst_token), ("viewer", viewer_token)):
            with self.subTest(role=label):
                r = self.client.post("/api/projects", json=project_payload, headers=self._headers(token))
                self.assertEqual(r.status_code, 403, r.text)

    # ------------------------------------------------------------------ #
    # security / audit
    # ------------------------------------------------------------------ #
    def test_audit_logs_contain_no_passwords_or_tokens(self):
        secret = "secret-password-governance-77"
        email, data = self._register_pending(password=secret)
        self._login(email, "wrong-wrong")
        self._login(email, "wrong-wrong")
        admin_email, admin_token = self._approved_user(role="admin")
        u = self._user_row(email)
        self.client.patch(
            f"/api/users/{u.user_id}/approval",
            json={"isApproved": True},
            headers=self._headers(admin_token),
        )
        for token in (data["accessToken"], data["refreshToken"]):
            self.assertFalse(self._audit_contains(token))
        self.assertFalse(self._audit_contains(secret))
        self.assertFalse(self._audit_contains("Bearer"))

    def test_unauthorized_admin_endpoint_returns_403_and_is_audited(self):
        viewer_email, viewer_token = self._approved_user(role="viewer")
        for path in ("/api/users", "/api/users/stats", "/api/admin/audit-logs"):
            with self.subTest(path=path):
                r = self.client.get(path, headers=self._headers(viewer_token))
                self.assertEqual(r.status_code, 403, r.text)
        self.assertIn("AUTHORIZATION_DENIED", self._audit_actions_for(viewer_email))

    def test_approval_state_enforced_server_side_not_just_routing(self):
        # No client-side hint can matter: the pending JWT itself is 403'd
        # before the handler runs, even for POST requests carrying data.
        pending_email, data = self._register_pending()
        sink = self._seed_project()
        headers = self._headers(data["accessToken"])
        r = self.client.post(
            f"/api/projects/{sink}/updates",
            json={"updateType": "GENERAL", "content": "should never persist"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 403, r.text)
        from database import SessionLocal
        from models import ProjectUpdate

        with SessionLocal() as db:
            found = (
                db.query(ProjectUpdate)
                .filter(ProjectUpdate.content == "should never persist")
                .count()
            )
            self.assertEqual(found, 0)


if __name__ == "__main__":
    unittest.main()