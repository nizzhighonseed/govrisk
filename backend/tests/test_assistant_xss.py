"""Regression tests for the stored-XSS fix in the Assistant chat.

A low-privilege authenticated user can store raw HTML-like strings in
user-controlled fields (project name/state/sector or update content).
Those strings are interpolated into assistant replies. Previously the
frontend rendered assistant replies through `dangerouslySetInnerHTML`, so
such payloads became executable HTML in every viewer's browser.

The fix has two layers:
- frontend renders assistant replies as React text (never raw HTML) -
  the primary trust boundary;
- the backend strips angle-bracket tag syntax from user-controlled text
  before interpolating it into replies - defense in depth.

These tests prove the server half: replies containing the classic payloads
cannot contain executable markup, while normal names, the `**bold**`
markers and newline structure are preserved 1:1.
"""

import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

try:
    from tests.test_risk_service import make_project
except ImportError:  # pragma: no cover - start dir variant (unittest discover)
    from test_risk_service import make_project

from services.text_guard import strip_html_tags

PAYLOAD_SCRIPT = "<script>alert(1)</script>"
PAYLOAD_IMG = '<img src=x onerror=alert(1)>'
PAYLOAD_SVG = "<svg/onload=alert(1)>"


class TextGuardTestCase(unittest.TestCase):
    def test_script_payload_is_neutralised(self):
        self.assertEqual(strip_html_tags(PAYLOAD_SCRIPT), "alert(1)")

    def test_img_onerror_payload_is_neutralised(self):
        self.assertEqual(strip_html_tags(PAYLOAD_IMG), "")

    def test_svg_onload_payload_is_neutralised(self):
        self.assertEqual(strip_html_tags(PAYLOAD_SVG), "")

    def test_plain_text_is_preserved(self):
        name = "River Basin Development Project (Phase II) - Bihar"
        self.assertEqual(strip_html_tags(name), name)

    def test_bold_markers_preserved_for_chat_formatting(self):
        self.assertEqual(strip_html_tags("**River Basin**"), "**River Basin**")

    def test_none_and_non_string_values_safe(self):
        self.assertEqual(strip_html_tags(None), "")
        self.assertEqual(strip_html_tags(123), "123")

    def test_ampersands_are_not_double_escaped(self):
        self.assertEqual(strip_html_tags("AT&T & Sons LLP"), "AT&T & Sons LLP")


def _session_with(projects):
    """Open a throwaway in-memory DB preloaded with `projects`."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import Base
    import models  # noqa: F401 - register model metadata on Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session._engine = engine
    for project in projects:
        session.add(project)
    session.commit()
    return session


def _close_session(session):
    session.close()
    session._engine.dispose()


class AssistantReplyPlainTextTestCase(unittest.TestCase):
    """Direct tests of the reply generator (no HTTP)."""

    def _reply(self, name="XSS Guard Project", state="Bihar", sector="Transport",
               query="Which projects are at highest risk?"):
        from services.risk_service import generate_assistant_response

        project = make_project(
            name=name, state=state, sector=sector,
            risk_score=80, risk_level="CRITICAL", delay_probability=70,
            cost_overrun_probability=50, implementation_risk=60,
        )
        db = _session_with([project])
        try:
            return generate_assistant_response(query, db)
        finally:
            _close_session(db)

    def test_script_payload_in_project_name_is_plain_text(self):
        reply = self._reply(name=PAYLOAD_SCRIPT)
        self.assertNotIn("<script", reply)
        self.assertNotIn("</script", reply)
        self.assertIn("alert(1)", reply)

    def test_img_payload_in_project_name_is_plain_text(self):
        reply = self._reply(name=PAYLOAD_IMG)
        self.assertNotIn("<img", reply)
        self.assertNotIn("onerror=", reply)
        self.assertNotIn("<", reply)

    def test_svg_payload_in_project_name_is_plain_text(self):
        reply = self._reply(name=PAYLOAD_SVG)
        self.assertNotIn("<svg", reply)
        self.assertNotIn("onload=", reply)
        self.assertNotIn("<", reply)

    def test_payload_in_project_state_is_plain_text(self):
        reply = self._reply(name="Safe Name", state=PAYLOAD_IMG)
        self.assertNotIn("<img", reply)
        self.assertNotIn("onerror=", reply)

    def test_payload_in_sector_analytics_is_plain_text(self):
        from services.risk_service import generate_assistant_response

        project = make_project(
            name="Safe Name", state="Bihar", sector=PAYLOAD_IMG,
            risk_score=50, risk_level="MEDIUM", delay_probability=30,
            cost_overrun_probability=20, implementation_risk=40,
        )
        db = _session_with([project])
        try:
            reply = generate_assistant_response("sector analysis", db)
        finally:
            _close_session(db)
        self.assertNotIn("<img", reply)
        self.assertNotIn("onerror=", reply)

    def test_normal_project_name_preserved_verbatim(self):
        name = "River Basin Development Project (Phase II) - Bihar"
        reply = self._reply(name=name)
        self.assertIn(name, reply)

    def test_bold_markers_and_newlines_preserved(self):
        name = "River Basin Development Project"
        reply = self._reply(name=name)
        self.assertIn(f"**{name}**", reply)
        self.assertIn("\n", reply)


def _patch_temp_dbs():
    """Point main + router DB sessions at throwaway SQLite files so the
    API tests never write to the developer's sankalp.db / auth.db."""
    global _TMP_ENGINE, _TMP_AUTH_ENGINE
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import database
    import auth.database

    import models  # noqa: F401
    import auth.models  # noqa: F401

    tmpdir = tempfile.mkdtemp(prefix="sankalp-xss-test-")
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
    import ai.ai_service
    ai.ai_service.SessionLocal = database.SessionLocal


class AssistantApiXssTestCase(unittest.TestCase):
    """End-to-end tests through the HTTP API against an isolated temp DB."""

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

    def _officer_headers(self):
        suffix = uuid.uuid4().hex[:8]
        email = f"xss_officer_{suffix}@sankalp.gov.in"
        r = self.client.post(
            "/api/auth/register",
            json={
                "fullName": "XSS Test Officer",
                "email": email,
                "password": "testpass123",
                "department": "IT",
                "designation": "Testing",
            },
        )
        self.assertEqual(r.status_code, 201, r.text)
        from auth.database import AuthSessionLocal
        from auth.models import User

        with AuthSessionLocal() as db:
            user = db.query(User).filter(User.email == email).first()
            user.role = "officer"
            user.is_approved = True
            db.commit()
        return {"Authorization": f"Bearer {r.json()['accessToken']}"}

    def _create_project(self, headers, name, state="Bihar"):
        r = self.client.post(
            "/api/projects",
            json={
                "name": name,
                "ministry": "MoRD",
                "agency": f"NHAI-{uuid.uuid4().hex[:6]}",
                "sector": "Transport",
                "state": state,
                "originalCost": 1000.0,
                "physicalProgress": 40.0,
                "startDate": "2024-01-01",
                "completionDate": "2027-12-31",
            },
            headers=headers,
        )
        self.assertEqual(r.status_code, 201, r.text)
        self._created_project_ids.append(r.json()["id"])
        return r.json()

    def test_malicious_project_name_and_state_never_become_html(self):
        headers = self._officer_headers()
        self._create_project(
            headers,
            name=f"{PAYLOAD_IMG} {PAYLOAD_SVG}",
            state=PAYLOAD_SCRIPT,
        )
        r = self.client.post(
            "/api/assistant",
            json={"query": "Which projects are at highest risk?"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 200, r.text)
        reply = r.json()["reply"]
        for forbidden in ("<script", "</script", "<img", "<svg",
                          "onerror=", "onload="):
            self.assertNotIn(forbidden, reply)

    def test_malicious_update_content_never_leaks_markup_into_reply(self):
        headers = self._officer_headers()
        project = self._create_project(headers, "XSS Guard Project")
        pid = project["id"]
        update = self.client.post(
            f"/api/projects/{pid}/updates",
            json={
                "updateType": "GENERAL",
                "content": (
                    f"Land acquisition {PAYLOAD_IMG} is blocked "
                    f"{PAYLOAD_SCRIPT} behind schedule"
                ),
            },
            headers=headers,
        )
        self.assertEqual(update.status_code, 201, update.text)

        r = self.client.post(
            "/api/assistant",
            json={"query": "Which projects are at highest risk?"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 200, r.text)
        reply = r.json()["reply"]
        self.assertIn("**XSS Guard Project**", reply)
        for forbidden in ("<script", "</script", "<img", "<svg",
                          "onerror=", "onload="):
            self.assertNotIn(forbidden, reply)

        # Mentioning the project also triggers the AI early-warning line,
        # which embeds project name / anomaly / emerging-risk titles.
        r2 = self.client.post(
            "/api/assistant",
            json={"query": f"What is the status of {pid}?"},
            headers=headers,
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        reply2 = r2.json()["reply"]
        for forbidden in ("<script", "</script", "<img", "<svg",
                          "onerror=", "onload="):
            self.assertNotIn(forbidden, reply2)

    def test_normal_assistant_reply_still_formats_bold_and_newlines(self):
        headers = self._officer_headers()
        self._create_project(headers, "River Basin Development Project")
        r = self.client.post(
            "/api/assistant",
            json={"query": "Which projects are at highest risk?"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 200, r.text)
        reply = r.json()["reply"]
        self.assertIn("**River Basin Development Project**", reply)
        self.assertIn("\n", reply)


if __name__ == "__main__":
    unittest.main()