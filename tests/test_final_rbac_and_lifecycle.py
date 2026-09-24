"""Comprehensive End-to-End Verification Tests for Final RBAC, Forecaster Access,
Alert Lifecycle, and Permanent Model Automation.

Specification Coverage:
Section 1: Authoritative role model (public, forecaster, coordinator; authoritative from public.profiles)
Section 2: Permanently enable automatic model switching (no freeze/unfreeze/force-last-known-good/disable-candidate)
Section 4: Forecaster access flow (single entry point, no conventional login, check-access, request-access, OTP gate)
Section 5: Forecaster request panel (coordinator-only list, approve, reject, profiles sync)
Section 6: Coordinator privileges (promotion forecaster -> coordinator, self-promotion disallowed, public disallowed)
Section 7: Alert cancellation behavior (soft cancel, no physical deletion, cancelled_by & cancelled_at, display name)
Section 8: Overview dynamic model version display (no hardcoded versions, switch metadata)
Section 9 & 10: Complete Authorization Matrix verification
"""

from __future__ import annotations

import datetime
import time
import uuid

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from core.config import settings

TEST_JWT_SECRET = "super-secret-test-jwt-key-for-rbac-and-lifecycle-testing"


def create_token(user_id: str, email: str, role: str) -> str:
    """Creates a signed test JWT."""
    payload = {
        "sub": user_id,
        "email": email,
        "role": "authenticated",
        "app_metadata": {"role": role},
        "user_metadata": {"role": role},
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
    }
    return jwt.encode(payload, settings.SUPABASE_JWT_SECRET or TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db_conn():
    """Provides a raw psycopg2 connection for setting up and verifying test fixtures."""
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    demo_users = [
        ("00000000-0000-0000-0000-000000000001", "public@aagam.gov.in", "public", "Demo Public"),
        ("00000000-0000-0000-0000-000000000002", "forecaster@aagam.gov.in", "forecaster", "Demo Forecaster"),
        ("00000000-0000-0000-0000-000000000003", "coordinator@aagam.gov.in", "coordinator", "Demo Coordinator"),
    ]
    with conn.cursor() as cur:
        for uid, email, role, dname in demo_users:
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;", (uid, email))
            cur.execute(
                """
                INSERT INTO profiles (user_id, display_name, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET role = EXCLUDED.role, display_name = EXCLUDED.display_name;
                """,
                (uid, dname, role),
            )
    yield conn
    with conn.cursor() as cur:
        for uid, _, _, _ in demo_users:
            cur.execute("DELETE FROM profiles WHERE user_id = %s;", (uid,))
            cur.execute("DELETE FROM auth.users WHERE id = %s;", (uid,))
    conn.close()


@pytest.fixture
def client(monkeypatch):
    """TestClient configured with test JWT secret."""
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "ENABLE_LOCAL_DEMO_AUTH", True)
    with TestClient(app) as test_client:
        yield test_client


# ==============================================================================
# SECTION A: FORECASTER ACCESS FLOW (NO CONVENTIONAL LOGIN)
# ==============================================================================

class TestForecasterAccessFlow:
    """Verifies single Forecaster Access entry point, email check, OTP gating, and request submission."""

    def test_approved_forecaster_email_check_access(self, client, db_conn):
        """Case A: Approved forecaster email check returns is_approved=True and role='forecaster'."""
        test_uid = str(uuid.uuid4())
        test_email = f"forecaster_{uuid.uuid4().hex[:6]}@example.gov.in"

        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (test_uid, test_email))
            cur.execute(
                """
                INSERT INTO profiles (user_id, display_name, role)
                VALUES (%s, 'Test Forecaster', 'forecaster')
                ON CONFLICT (user_id) DO UPDATE SET role = 'forecaster', display_name = 'Test Forecaster';
                """,
                (test_uid,),
            )

        try:
            resp = client.post("/api/v1/auth/forecaster/check-access", json={"email": test_email})
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["is_approved"] is True
            assert data["role"] == "forecaster"
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM profiles WHERE user_id = %s;", (test_uid,))
                cur.execute("DELETE FROM auth.users WHERE id = %s;", (test_uid,))

    def test_approved_coordinator_email_check_access(self, client, db_conn):
        """Case A: Approved coordinator email check returns is_approved=True and role='coordinator'."""
        test_uid = str(uuid.uuid4())
        test_email = f"coord_{uuid.uuid4().hex[:6]}@example.gov.in"

        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (test_uid, test_email))
            cur.execute(
                """
                INSERT INTO profiles (user_id, display_name, role)
                VALUES (%s, 'Test Coord', 'coordinator')
                ON CONFLICT (user_id) DO UPDATE SET role = 'coordinator', display_name = 'Test Coord';
                """,
                (test_uid,),
            )

        try:
            resp = client.post("/api/v1/auth/forecaster/check-access", json={"email": test_email})
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["is_approved"] is True
            assert data["role"] == "coordinator"
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM profiles WHERE user_id = %s;", (test_uid,))
                cur.execute("DELETE FROM auth.users WHERE id = %s;", (test_uid,))

    def test_unregistered_email_check_access(self, client):
        """Case B: Unregistered email check returns is_approved=False and role=None."""
        resp = client.post("/api/v1/auth/forecaster/check-access", json={"email": "unknown_person@somewhere.org"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_approved"] is False
        assert data["role"] is None

    def test_unregistered_email_submit_request_success(self, client, db_conn):
        """Case B: Candidate submits Forecaster access request; saved with status='pending'."""
        cand_email = f"applicant_{uuid.uuid4().hex[:6]}@imd.gov.in"
        cand_name = "Candidate Meteorologist"

        try:
            resp = client.post(
                "/api/v1/auth/forecaster/request-access",
                json={"name": cand_name, "email": cand_email, "institution": "IMD Delhi"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["status"] == "ok"

            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT name, status, institution FROM forecaster_access_requests WHERE email = %s;",
                    (cand_email,),
                )
                row = cur.fetchone()
                assert row is not None, "Request row not saved in forecaster_access_requests"
                assert row[0] == cand_name
                assert row[1] == "pending"
                assert row[2] == "IMD Delhi"
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM forecaster_access_requests WHERE email = %s;", (cand_email,))

    def test_unapproved_email_cannot_request_forecaster_otp(self, client):
        """Unapproved email cannot request forecaster OTP and receives 403 ACCESS_NOT_APPROVED."""
        resp = client.post(
            "/api/v1/auth/forecaster/otp/request",
            json={"email": "unregistered_stranger@gmail.com"},
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["error"]["code"] == "ACCESS_NOT_APPROVED"

    def test_public_user_cannot_access_coordinator_requests_panel(self, client):
        """Public/anonymous user receives 403 when trying to access coordinator requests endpoint."""
        resp = client.get("/api/v1/auth/forecaster/requests")
        assert resp.status_code in (401, 403)

        # Authenticated public user
        headers = {"Authorization": "Bearer demo-public-token"}
        resp = client.get("/api/v1/auth/forecaster/requests", headers=headers)
        assert resp.status_code == 403


# ==============================================================================
# SECTION B: FORECASTER REQUEST APPROVAL & PROFILES SYNC
# ==============================================================================

class TestForecasterRequestApproval:
    """Verifies coordinator approval workflow, role='forecaster' assignment, and rejection."""

    def test_coordinator_can_approve_request(self, client, db_conn):
        """Coordinator approves pending request: request status='approved' and profile role='forecaster'."""
        target_uid = str(uuid.uuid4())
        target_email = f"candidate_{uuid.uuid4().hex[:6]}@met.gov.in"

        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (target_uid, target_email))
            cur.execute(
                """
                INSERT INTO profiles (user_id, display_name, role)
                VALUES (%s, 'Candidate', 'public')
                ON CONFLICT (user_id) DO UPDATE SET role = 'public', display_name = 'Candidate';
                """,
                (target_uid,),
            )
            cur.execute(
                """
                INSERT INTO forecaster_access_requests (name, email, institution, status)
                VALUES ('Candidate Met', %s, 'IMD', 'pending')
                RETURNING id;
                """,
                (target_email,),
            )
            req_id = cur.fetchone()[0]

        try:
            coord_headers = {"Authorization": "Bearer demo-coordinator-token"}
            resp = client.post(f"/api/v1/auth/forecaster/requests/{req_id}/approve", headers=coord_headers)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["status"] == "approved"
            assert data["email"] == target_email

            with db_conn.cursor() as cur:
                cur.execute("SELECT status, reviewed_by FROM forecaster_access_requests WHERE id = %s;", (req_id,))
                req_row = cur.fetchone()
                assert req_row[0] == "approved"
                assert req_row[1] is not None

                cur.execute("SELECT role FROM profiles WHERE user_id = %s;", (target_uid,))
                prof_row = cur.fetchone()
                assert prof_row[0] == "forecaster", f"Expected profile role 'forecaster', got '{prof_row[0]}'"
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM forecaster_access_requests WHERE id = %s;", (req_id,))
                cur.execute("DELETE FROM profiles WHERE user_id = %s;", (target_uid,))
                cur.execute("DELETE FROM auth.users WHERE id = %s;", (target_uid,))

    def test_forecaster_cannot_approve_request(self, client, db_conn):
        """Forecaster receives 403 when trying to approve an access request."""
        cand_email = f"cand_{uuid.uuid4().hex[:6]}@test.com"
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO forecaster_access_requests (name, email, status) VALUES ('X', %s, 'pending') RETURNING id;",
                (cand_email,),
            )
            req_id = cur.fetchone()[0]

        try:
            forecaster_headers = {"Authorization": "Bearer demo-forecaster-token"}
            resp = client.post(f"/api/v1/auth/forecaster/requests/{req_id}/approve", headers=forecaster_headers)
            assert resp.status_code == 403
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM forecaster_access_requests WHERE id = %s;", (req_id,))

    def test_public_cannot_approve_request(self, client, db_conn):
        """Public user receives 403 when trying to approve an access request."""
        cand_email = f"cand_{uuid.uuid4().hex[:6]}@test.com"
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO forecaster_access_requests (name, email, status) VALUES ('X', %s, 'pending') RETURNING id;",
                (cand_email,),
            )
            req_id = cur.fetchone()[0]

        try:
            public_headers = {"Authorization": "Bearer demo-public-token"}
            resp = client.post(f"/api/v1/auth/forecaster/requests/{req_id}/approve", headers=public_headers)
            assert resp.status_code == 403
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM forecaster_access_requests WHERE id = %s;", (req_id,))


# ==============================================================================
# SECTION C: COORDINATOR PROMOTION RULES
# ==============================================================================

class TestCoordinatorPromotionRules:
    """Verifies promotion of verified forecaster to coordinator and all promotion constraints."""

    def test_coordinator_can_promote_verified_forecaster(self, client, db_conn):
        """Coordinator promotes verified forecaster: role becomes 'coordinator'."""
        forecaster_uid = str(uuid.uuid4())
        forecaster_email = f"forecaster_{uuid.uuid4().hex[:6]}@imd.gov.in"

        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (forecaster_uid, forecaster_email))
            cur.execute(
                """
                INSERT INTO profiles (user_id, display_name, role)
                VALUES (%s, 'Senior Forecaster', 'forecaster')
                ON CONFLICT (user_id) DO UPDATE SET role = 'forecaster', display_name = 'Senior Forecaster';
                """,
                (forecaster_uid,),
            )

        try:
            coord_headers = {"Authorization": "Bearer demo-coordinator-token"}
            resp = client.post(f"/api/v1/auth/forecasters/{forecaster_uid}/promote-coordinator", headers=coord_headers)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["status"] == "ok"
            assert data["role"] == "coordinator"

            with db_conn.cursor() as cur:
                cur.execute("SELECT role FROM profiles WHERE user_id = %s;", (forecaster_uid,))
                row = cur.fetchone()
                assert row[0] == "coordinator"
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM profiles WHERE user_id = %s;", (forecaster_uid,))
                cur.execute("DELETE FROM auth.users WHERE id = %s;", (forecaster_uid,))

    def test_forecaster_cannot_promote(self, client):
        """Forecaster receives 403 when trying to promote."""
        forecaster_headers = {"Authorization": "Bearer demo-forecaster-token"}
        dummy_uid = str(uuid.uuid4())
        resp = client.post(f"/api/v1/auth/forecasters/{dummy_uid}/promote-coordinator", headers=forecaster_headers)
        assert resp.status_code == 403

    def test_public_cannot_promote(self, client):
        """Public user receives 403 when trying to promote."""
        public_headers = {"Authorization": "Bearer demo-public-token"}
        dummy_uid = str(uuid.uuid4())
        resp = client.post(f"/api/v1/auth/forecasters/{dummy_uid}/promote-coordinator", headers=public_headers)
        assert resp.status_code == 403

    def test_coordinator_cannot_self_promote(self, client):
        """Coordinator cannot self-promote: rejected with 400 SELF_PROMOTION_DISALLOWED."""
        coord_headers = {"Authorization": "Bearer demo-coordinator-token"}
        coord_uid = "00000000-0000-0000-0000-000000000003"
        resp = client.post(f"/api/v1/auth/forecasters/{coord_uid}/promote-coordinator", headers=coord_headers)
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "SELF_PROMOTION_DISALLOWED"

    def test_public_user_cannot_be_promoted_directly(self, client, db_conn):
        """Public user cannot be directly promoted to coordinator: rejected with 400 INVALID_TARGET_ROLE."""
        public_uid = str(uuid.uuid4())
        public_email = f"public_{uuid.uuid4().hex[:6]}@example.com"

        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s);", (public_uid, public_email))
            cur.execute(
                """
                INSERT INTO profiles (user_id, display_name, role)
                VALUES (%s, 'Ordinary Citizen', 'public')
                ON CONFLICT (user_id) DO UPDATE SET role = 'public', display_name = 'Ordinary Citizen';
                """,
                (public_uid,),
            )

        try:
            coord_headers = {"Authorization": "Bearer demo-coordinator-token"}
            resp = client.post(f"/api/v1/auth/forecasters/{public_uid}/promote-coordinator", headers=coord_headers)
            assert resp.status_code == 400
            assert resp.json()["error"]["code"] == "INVALID_TARGET_ROLE"
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM profiles WHERE user_id = %s;", (public_uid,))
                cur.execute("DELETE FROM auth.users WHERE id = %s;", (public_uid,))


# ==============================================================================
# SECTION D: ALERT CANCELLATION LIFECYCLE (SOFT CANCEL, NO PHYSICAL DELETE)
# ==============================================================================

class TestAlertCancellationLifecycle:
    """Verifies that alert cancellation marks status='cancelled', preserves DB rows, records actor and display name."""

    def test_forecaster_can_cancel_alert(self, client, db_conn):
        """Forecaster cancels alert: status='cancelled', cancelled_by & cancelled_at populated, row preserved."""
        today = datetime.date.today()
        forecaster_uid = "00000000-0000-0000-0000-000000000002"

        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_events (location_id, hazard, status, severity_peak, start_date, end_date)
                VALUES (36, 'heavy_rain', 'active', 'watch', %s, %s)
                RETURNING id;
                """,
                (today, today),
            )
            event_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO alerts (location_id, hazard, severity, issue_time, valid_date, lead_days, rule, status, event_id)
                VALUES (36, 'heavy_rain', 'watch', NOW(), %s, 1, '{"name": "heavy_rain_watch_rule"}'::json, 'active', %s)
                RETURNING id;
                """,
                (today, event_id),
            )
            alert_id = cur.fetchone()[0]

        try:
            forecaster_headers = {"Authorization": "Bearer demo-forecaster-token"}
            resp = client.post(f"/api/v1/alerts/{alert_id}/cancel", headers=forecaster_headers)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["status"] == "cancelled"
            assert data["cancelled_by"] == forecaster_uid
            assert data["cancelled_at"] is not None
            assert "cancelled_by_name" in data

            # Verify in DB: row is NOT deleted, status is 'cancelled'
            with db_conn.cursor() as cur:
                cur.execute("SELECT status, cancelled_by, cancelled_at FROM alerts WHERE id = %s;", (alert_id,))
                row = cur.fetchone()
                assert row is not None, "Alert was physically deleted! It must be preserved."
                assert row[0] == "cancelled"
                assert str(row[1]) == forecaster_uid
                assert row[2] is not None
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM alerts WHERE id = %s;", (alert_id,))
                cur.execute("DELETE FROM alert_events WHERE id = %s;", (event_id,))

    def test_cancel_alert_event_cascades_to_children_and_preserves_records(self, client, db_conn):
        """Cancelling alert event cascades status='cancelled' to active child alerts and preserves all rows."""
        today = datetime.date.today()
        coord_uid = "00000000-0000-0000-0000-000000000003"

        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_events (location_id, hazard, status, severity_peak, start_date, end_date)
                VALUES (36, 'heatwave', 'active', 'alert', %s, %s)
                RETURNING id;
                """,
                (today, today),
            )
            event_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO alerts (location_id, hazard, severity, issue_time, valid_date, lead_days, rule, status, event_id)
                VALUES (36, 'heatwave', 'alert', NOW(), %s, 0, '{"name": "heatwave_alert_rule"}'::json, 'active', %s)
                RETURNING id;
                """,
                (today, event_id),
            )
            child_alert_id = cur.fetchone()[0]

        try:
            coord_headers = {"Authorization": "Bearer demo-coordinator-token"}
            resp = client.post(f"/api/v1/alerts/events/{event_id}/cancel", headers=coord_headers)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["status"] == "cancelled"
            assert data["cancelled_by"] == coord_uid
            assert data["cancelled_at"] is not None

            # Verify in DB: both event and child alert are preserved with status='cancelled'
            with db_conn.cursor() as cur:
                cur.execute("SELECT status, cancelled_by FROM alert_events WHERE id = %s;", (event_id,))
                ev_row = cur.fetchone()
                assert ev_row is not None
                assert ev_row[0] == "cancelled"
                assert str(ev_row[1]) == coord_uid

                cur.execute("SELECT status, cancelled_by FROM alerts WHERE id = %s;", (child_alert_id,))
                al_row = cur.fetchone()
                assert al_row is not None
                assert al_row[0] == "cancelled"
                assert str(al_row[1]) == coord_uid

            # Verify GET event detail renders cancelled_by and cancelled_by_name
            get_resp = client.get(f"/api/v1/alerts/events/{event_id}")
            assert get_resp.status_code == 200
            ev_data = get_resp.json()
            assert ev_data["event"]["status"] == "cancelled"
            assert ev_data["event"]["cancelled_by"] == coord_uid
            assert ev_data["event"]["cancelled_at"] is not None
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM alerts WHERE id = %s;", (child_alert_id,))
                cur.execute("DELETE FROM alert_events WHERE id = %s;", (event_id,))

    def test_public_user_cannot_cancel_alert(self, client, db_conn):
        """Public user receives 403 when attempting to cancel an alert."""
        today = datetime.date.today()
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_events (location_id, hazard, status, severity_peak, start_date, end_date)
                VALUES (36, 'heavy_rain', 'active', 'advisory', %s, %s)
                RETURNING id;
                """,
                (today, today),
            )
            event_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO alerts (location_id, hazard, severity, issue_time, valid_date, lead_days, rule, status, event_id)
                VALUES (36, 'heavy_rain', 'advisory', NOW(), %s, 1, '{"name": "heavy_rain_adv_rule"}'::json, 'active', %s)
                RETURNING id;
                """,
                (today, event_id),
            )
            alert_id = cur.fetchone()[0]

        try:
            public_headers = {"Authorization": "Bearer demo-public-token"}
            resp = client.post(f"/api/v1/alerts/{alert_id}/cancel", headers=public_headers)
            assert resp.status_code == 403
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM alerts WHERE id = %s;", (alert_id,))
                cur.execute("DELETE FROM alert_events WHERE id = %s;", (event_id,))


# ==============================================================================
# SECTION E: PERMANENT MODEL AUTOMATION & MUTATION CONTROLS HARD-DISABLED
# ==============================================================================

class TestPermanentModelAutomationControls:
    """Verifies that all manual model automation mutation controls are permanently hard-disabled (403)."""

    @pytest.mark.parametrize("role_token", [
        "demo-public-token",
        "demo-forecaster-token",
        "demo-coordinator-token",
    ])
    def test_freeze_hard_disabled_for_all_roles(self, client, role_token):
        """POST /api/v1/models/automation/freeze returns 403 OPERATION_DISALLOWED for every role."""
        resp = client.post(
            "/api/v1/models/automation/freeze",
            json={"reason": "Manual freeze test"},
            headers={"Authorization": f"Bearer {role_token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "OPERATION_DISALLOWED"

    @pytest.mark.parametrize("role_token", [
        "demo-public-token",
        "demo-forecaster-token",
        "demo-coordinator-token",
    ])
    def test_unfreeze_hard_disabled_for_all_roles(self, client, role_token):
        """POST /api/v1/models/automation/unfreeze returns 403 OPERATION_DISALLOWED for every role."""
        resp = client.post(
            "/api/v1/models/automation/unfreeze",
            json={"reason": "Manual unfreeze test"},
            headers={"Authorization": f"Bearer {role_token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "OPERATION_DISALLOWED"

    @pytest.mark.parametrize("role_token", [
        "demo-public-token",
        "demo-forecaster-token",
        "demo-coordinator-token",
    ])
    def test_force_last_known_good_hard_disabled_for_all_roles(self, client, role_token):
        """POST /api/v1/models/automation/force-last-known-good returns 403 OPERATION_DISALLOWED for every role."""
        resp = client.post(
            "/api/v1/models/automation/force-last-known-good",
            json={"reason": "Manual rollback test"},
            headers={"Authorization": f"Bearer {role_token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "OPERATION_DISALLOWED"

    @pytest.mark.parametrize("role_token", [
        "demo-public-token",
        "demo-forecaster-token",
        "demo-coordinator-token",
    ])
    def test_disable_candidate_hard_disabled_for_all_roles(self, client, role_token):
        """POST /api/v1/models/candidates/{id}/disable returns 403 OPERATION_DISALLOWED for every role."""
        resp = client.post(
            "/api/v1/models/candidates/3/disable",
            json={"reason": "Manual reject test"},
            headers={"Authorization": f"Bearer {role_token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "OPERATION_DISALLOWED"

    @pytest.mark.parametrize("role_token", [
        "demo-public-token",
        "demo-forecaster-token",
        "demo-coordinator-token",
    ])
    def test_direct_activation_hard_disabled_for_all_roles(self, client, role_token):
        """POST /api/v1/models/{id}/activate remains permanently hard-disabled (403) for all roles."""
        resp = client.post(
            "/api/v1/models/3/activate",
            headers={"Authorization": f"Bearer {role_token}"},
        )
        assert resp.status_code == 403

    def test_model_automation_status_rbac(self, client):
        """GET /api/v1/models/automation/status: 200 for forecaster/coordinator, 403 for public/anon."""
        # Anon -> 403
        assert client.get("/api/v1/models/automation/status").status_code == 403

        # Public -> 403
        assert client.get(
            "/api/v1/models/automation/status",
            headers={"Authorization": "Bearer demo-public-token"},
        ).status_code == 403

        # Forecaster -> 200
        resp_f = client.get(
            "/api/v1/models/automation/status",
            headers={"Authorization": "Bearer demo-forecaster-token"},
        )
        assert resp_f.status_code == 200

        # Coordinator -> 200
        resp_c = client.get(
            "/api/v1/models/automation/status",
            headers={"Authorization": "Bearer demo-coordinator-token"},
        )
        assert resp_c.status_code == 200


# ==============================================================================
# SECTION F: OVERVIEW DYNAMIC MODEL VERSION DISPLAY
# ==============================================================================

class TestOverviewDynamicModelVersionDisplay:
    """Verifies that the overview endpoint exposes authoritative dynamic model version data."""

    def test_overview_meta_active_model_version_dynamic(self, client):
        """GET /api/v1/meta provides dynamic active_model_version with id and switch metadata."""
        resp = client.get("/api/v1/meta")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "active_model_version" in data
        active_ver = data["active_model_version"]
        assert "id" in active_ver
        assert isinstance(active_ver["id"], int)
        assert "is_active" in active_ver
        assert active_ver["is_active"] is True
        # Check switch fields exist
        assert "previous_version_id" in active_ver
        assert "parent_version_id" in active_ver
        assert "switched_at" in active_ver
