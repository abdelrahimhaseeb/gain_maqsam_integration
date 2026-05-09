from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import frappe

from gain_maqsam_integration.api import (
    _extract_agent_email,
    _extract_webhook_call,
    _get_customer_phone_from_call,
    _get_latest_call_state,
    _resolve_popup_target_users,
    maqsam_receive_call_event,
)
from gain_maqsam_integration.call_log import upsert_maqsam_call
from gain_maqsam_integration.permissions import MAQSAM_AGENT_ROLE


class FakeRequest:
    def __init__(self, token: str = "", payload=None, method: str = "POST", headers=None):
        self.method = method
        self._payload = payload or {}
        self.headers = dict(headers or {})
        if token:
            self.headers.setdefault("X-Maqsam-Webhook-Token", token)
        self.headers.setdefault("Content-Length", str(len(json.dumps(self._payload, default=str))))

    def get_json(self, silent: bool = True):
        return self._payload


def ensure_role(role_name: str) -> None:
    if frappe.db.exists("Role", role_name):
        return
    frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert(ignore_permissions=True)


class TestExtractWebhookCall(unittest.TestCase):
    def test_flat_payload(self):
        payload = {"id": "abc", "callerNumber": "966500000001", "type": "inbound"}
        call = _extract_webhook_call(payload)
        self.assertEqual(call["id"], "abc")
        self.assertEqual(call["callerNumber"], "966500000001")
        self.assertEqual(call["direction"], "inbound")

    def test_nested_payload(self):
        payload = {"call": {"id": "xyz", "caller": "+966500000002", "direction": "inbound"}}
        call = _extract_webhook_call(payload)
        self.assertEqual(call["id"], "xyz")
        self.assertEqual(call["caller"], "+966500000002")

    def test_aliases_fill_missing_fields(self):
        payload = {"id": "1", "from": "+1", "to": "+2", "callStatus": "ringing"}
        call = _extract_webhook_call(payload)
        self.assertEqual(call["caller"], "+1")
        self.assertEqual(call["callee"], "+2")
        self.assertEqual(call["state"], "ringing")


class TestExtractAgentEmail(unittest.TestCase):
    def test_from_agents_list(self):
        call = {"agents": [{"email": "a@example.com"}]}
        self.assertEqual(_extract_agent_email({}, call), "a@example.com")

    def test_from_top_level_agentEmail(self):
        self.assertEqual(_extract_agent_email({"agentEmail": "b@x.com"}, {}), "b@x.com")

    def test_blank_when_missing(self):
        self.assertEqual(_extract_agent_email({}, {}), "")


class TestCustomerPhoneFromCall(unittest.TestCase):
    def test_inbound_uses_caller(self):
        self.assertEqual(
            _get_customer_phone_from_call({"direction": "inbound", "callerNumber": "+966500"}),
            "+966500",
        )

    def test_outbound_uses_callee(self):
        self.assertEqual(
            _get_customer_phone_from_call({"direction": "outbound", "calleeNumber": "+966600"}),
            "+966600",
        )


class TestPopupTargetUsers(unittest.TestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        ensure_role(MAQSAM_AGENT_ROLE)
        self.created_users: list[str] = []

    def tearDown(self):
        frappe.set_user("Administrator")
        for user in self.created_users:
            if frappe.db.exists("User", user):
                frappe.delete_doc("User", user, ignore_permissions=True, force=True)
        frappe.db.commit()

    def _make_user(self, label: str, roles: list[str]) -> str:
        email = f"maqsam-popup-{label}-{frappe.generate_hash(length=8)}@example.com"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Maqsam",
                "last_name": label.title(),
                "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": role} for role in roles],
            }
        ).insert(ignore_permissions=True)
        self.created_users.append(email)
        return email

    def test_assigned_call_broadcasts_to_all_maqsam_agents(self):
        matched_agent = self._make_user("matched", [MAQSAM_AGENT_ROLE])
        other_agent = self._make_user("other", [MAQSAM_AGENT_ROLE])
        desk_user = self._make_user("desk", ["Desk User"])
        frappe.db.commit()

        targets = _resolve_popup_target_users(matched_agent, frappe._dict())

        self.assertIn(matched_agent, targets)
        self.assertIn(other_agent, targets)
        self.assertNotIn(desk_user, targets)

    def test_unassigned_call_broadcasts_to_all_maqsam_agents(self):
        first_agent = self._make_user("first", [MAQSAM_AGENT_ROLE])
        second_agent = self._make_user("second", [MAQSAM_AGENT_ROLE])
        frappe.db.commit()

        targets = _resolve_popup_target_users("", frappe._dict())

        self.assertIn(first_agent, targets)
        self.assertIn(second_agent, targets)


class TestIncomingRealtimeState(unittest.TestCase):
    def setUp(self):
        self.call_id = f"test-realtime-state-{frappe.generate_hash(length=8)}"
        self.log_name, _created = upsert_maqsam_call(
            {
                "id": self.call_id,
                "caller": "+966500000010",
                "callee": "+966112223344",
                "state": "ended",
                "direction": "inbound",
                "timestamp": "2026-04-27 20:30:00",
            }
        )
        frappe.db.commit()

    def tearDown(self):
        if self.log_name and frappe.db.exists("Maqsam Call Log", self.log_name):
            frappe.delete_doc("Maqsam Call Log", self.log_name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_latest_call_state_prefers_saved_state_over_stale_payload(self):
        self.assertEqual(_get_latest_call_state(self.log_name, "ringing"), "ended")

    def test_latest_call_state_falls_back_when_log_missing(self):
        self.assertEqual(_get_latest_call_state("MCL-MISSING", "ringing"), "ringing")


class TestWebhookAuth(unittest.TestCase):
    def setUp(self):
        self.created_logs: list[str] = []
        if not frappe.db.exists("DocType", "Maqsam Settings"):
            self.skipTest("Maqsam Settings doctype not installed")
        self.settings = frappe.get_single("Maqsam Settings")
        self.original_token = self.settings.get_password("incoming_webhook_token") or ""
        self.original_enabled = self.settings.enabled
        self.settings.enabled = 1
        self.settings.incoming_webhook_token = "test-token-with-32-plus-chars-12345"
        self.settings.save(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        # Restore the original token (or a high-entropy placeholder) so the
        # validator's min-length rule doesn't reject the teardown save.
        self.settings.enabled = self.original_enabled
        self.settings.incoming_webhook_token = (
            self.original_token or "test-placeholder-with-32-plus-chars-1234"
        )
        self.settings.save(ignore_permissions=True)
        for name in self.created_logs:
            if frappe.db.exists("Maqsam Call Log", name):
                frappe.delete_doc("Maqsam Call Log", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _set_request(self, token, payload, method="POST", headers=None, form_token=None):
        frappe.local.form_dict = frappe._dict({"token": form_token} if form_token else {})
        frappe.local.form_dict.cmd = "gain_maqsam_integration.api.maqsam_receive_call_event"
        frappe.local.request_ip = "127.0.0.1"
        frappe.local.request = FakeRequest(token=token, payload=payload, method=method, headers=headers)

    def test_missing_token_raises_permission_error(self):
        self._set_request("", {"id": "x"})
        with self.assertRaises(frappe.PermissionError):
            maqsam_receive_call_event()

    def test_wrong_token_raises_permission_error(self):
        self._set_request("WRONG", {"id": "x"})
        with self.assertRaises(frappe.PermissionError):
            maqsam_receive_call_event()

    def test_form_token_is_rejected_even_when_valid(self):
        self._set_request("", {"id": "x"}, form_token="test-token-with-32-plus-chars-12345")
        with self.assertRaises(frappe.PermissionError):
            maqsam_receive_call_event()

    def test_get_request_is_rejected(self):
        self._set_request("test-token-with-32-plus-chars-12345", {"id": "x"}, method="GET")
        with self.assertRaises(frappe.PermissionError):
            maqsam_receive_call_event()

    def test_disabled_integration_rejects_webhook(self):
        self.settings.enabled = 0
        self.settings.save(ignore_permissions=True)
        frappe.db.commit()
        self._set_request("test-token-with-32-plus-chars-12345", {"id": "x"})
        with self.assertRaises(frappe.PermissionError):
            maqsam_receive_call_event()

    def test_large_payload_is_rejected(self):
        self._set_request(
            "test-token-with-32-plus-chars-12345",
            {"id": "x"},
            headers={"Content-Length": str((64 * 1024) + 1)},
        )
        with self.assertRaises(frappe.ValidationError):
            maqsam_receive_call_event()

    def test_invalid_direction_is_rejected(self):
        self._set_request("test-token-with-32-plus-chars-12345", {"id": "x", "direction": "sideways"})
        with self.assertRaises(frappe.ValidationError):
            maqsam_receive_call_event()

    def test_valid_token_with_missing_id_raises_validation(self):
        self._set_request("test-token-with-32-plus-chars-12345", {})
        with self.assertRaises(frappe.ValidationError):
            maqsam_receive_call_event()

    def test_valid_token_creates_log_and_queues_dispatch(self):
        call_id = f"test-webhook-{frappe.generate_hash(length=8)}"
        self._set_request(
            "test-token-with-32-plus-chars-12345",
            {
                "id": call_id,
                "caller": "+966500000099",
                "callee": "+966112223344",
                "state": "ringing",
                "direction": "inbound",
                "timestamp": "2026-04-27 20:30:00",
            },
        )
        with patch("gain_maqsam_integration.api.frappe.enqueue") as enqueue_mock:
            response = maqsam_receive_call_event()

        self.assertTrue(response["ok"])
        self.assertTrue(response["created"])
        self.assertTrue(response["queued"])
        self.created_logs.append(response["call_log"])
        enqueue_mock.assert_called_once()
        self.assertEqual(
            enqueue_mock.call_args.kwargs.get("call", {}).get("id"), call_id
        )

    def test_subsequent_event_for_same_call_skips_enqueue(self):
        # The two-phase dispatch only queues the heavy profile lookup on the
        # very first event for a call. Subsequent events (in_progress, ended)
        # rely on the fast notification to update the drawer state — there's
        # no need to re-fetch the profile, so enqueue must not be called.
        call_id = f"test-webhook-noreq-{frappe.generate_hash(length=8)}"
        first_payload = {
            "id": call_id,
            "caller": "+966500111222",
            "callee": "+966112223344",
            "state": "ringing",
            "direction": "inbound",
            "timestamp": "2026-04-27 22:00:00",
        }
        self._set_request("test-token-with-32-plus-chars-12345", first_payload)
        with patch("gain_maqsam_integration.api.frappe.enqueue"):
            first = maqsam_receive_call_event()
        self.created_logs.append(first["call_log"])
        self.assertTrue(first["created"])

        # Second event for the same call (Maqsam fires `in_progress`).
        self._set_request("test-token-with-32-plus-chars-12345", dict(first_payload, state="in_progress"))
        with patch("gain_maqsam_integration.api.frappe.enqueue") as enqueue_mock:
            second = maqsam_receive_call_event()

        self.assertTrue(second["ok"])
        self.assertFalse(second["created"])
        self.assertFalse(second["queued"])
        enqueue_mock.assert_not_called()


class TestWebhookConcurrency(unittest.TestCase):
    def setUp(self):
        self.created_logs: list[str] = []
        if not frappe.db.exists("DocType", "Maqsam Settings"):
            self.skipTest("Maqsam Settings doctype not installed")
        self.settings = frappe.get_single("Maqsam Settings")
        self.original_token = self.settings.get_password("incoming_webhook_token") or ""
        self.original_enabled = self.settings.enabled
        self.settings.enabled = 1
        self.settings.incoming_webhook_token = "test-token-with-32-plus-chars-54321"
        self.settings.save(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        self.settings.enabled = self.original_enabled
        self.settings.incoming_webhook_token = (
            self.original_token or "test-placeholder-with-32-plus-chars-1234"
        )
        self.settings.save(ignore_permissions=True)
        for name in self.created_logs:
            if frappe.db.exists("Maqsam Call Log", name):
                frappe.delete_doc("Maqsam Call Log", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _set_request(self, token, payload, method="POST", headers=None, form_token=None):
        frappe.local.form_dict = frappe._dict({"token": form_token} if form_token else {})
        frappe.local.form_dict.cmd = "gain_maqsam_integration.api.maqsam_receive_call_event"
        frappe.local.request_ip = "127.0.0.1"
        frappe.local.request = FakeRequest(token=token, payload=payload, method=method, headers=headers)

    def test_physical_threading_stress(self):
        call_id = f"stress-{frappe.generate_hash(length=8)}"
        payload = {
            "id": call_id,
            "caller": "+966500000099",
            "state": "ringing",
            "direction": "inbound",
            "timestamp": "2026-04-27 20:30:00",
        }
        site_name = frappe.local.site

        def _worker():
            frappe.init(site=site_name)
            frappe.connect()
            frappe.flags.in_test = True
            original_user = getattr(frappe.session, "user", "Administrator")
            try:
                frappe.set_user("Administrator")
                frappe.local.form_dict = frappe._dict()
                frappe.local.form_dict.cmd = "gain_maqsam_integration.api.maqsam_receive_call_event"
                frappe.local.request_ip = "127.0.0.1"
                frappe.local.request = FakeRequest(token="test-token-with-32-plus-chars-54321", payload=payload)
                return maqsam_receive_call_event()
            except Exception as e:
                return e
            finally:
                frappe.db.rollback()
                frappe.set_user(original_user)
                frappe.destroy()

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_worker) for _ in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        for res in results:
            self.assertIsInstance(res, dict, f"Worker returned exception: {res}")
            self.assertTrue(res.get("ok"), "Webhook failed ok status")
            if res.get("call_log"):
                self.created_logs.append(res["call_log"])

        created_count = sum(1 for r in results if isinstance(r, dict) and r.get("created"))
        self.assertEqual(created_count, 1, "Exactly one thread should have created it")

    def test_transient_deadlock_retries_and_updates_call_log(self):
        call_id = f"deadlock-{frappe.generate_hash(length=8)}"
        log_name, created = upsert_maqsam_call(
            {
                "id": call_id,
                "caller": "+966500000099",
                "callee": "+966112223344",
                "state": "ringing",
                "direction": "inbound",
                "timestamp": "2026-04-27 20:30:00",
            }
        )
        frappe.db.commit()
        self.created_logs.append(log_name)
        self.assertTrue(created)

        payload = {
            "id": call_id,
            "caller": "+966500000099",
            "callee": "+966112223344",
            "state": "in_progress",
            "direction": "inbound",
            "timestamp": "2026-04-27 20:31:00",
        }
        self._set_request("test-token-with-32-plus-chars-54321", payload)

        original_sql = frappe.db.sql
        failures = {"count": 0}

        def mock_sql(query, *args, **kwargs):
            if "FOR UPDATE" in query and call_id in str(args) and failures["count"] == 0:
                failures["count"] += 1
                e = Exception("Deadlock found when trying to get lock; try restarting transaction")
                e.args = (1213, "Deadlock found...")
                raise e
            return original_sql(query, *args, **kwargs)

        with patch("gain_maqsam_integration.call_log.frappe.db.sql", side_effect=mock_sql), patch(
            "gain_maqsam_integration.call_log.time.sleep",
            return_value=None,
        ):
            res = maqsam_receive_call_event()

        self.assertEqual(failures["count"], 1)
        self.assertTrue(res.get("ok"))
        self.assertFalse(res.get("created"))
        self.assertEqual(res.get("call_log"), log_name)
        self.assertEqual(frappe.db.get_value("Maqsam Call Log", log_name, "state"), "in_progress")

    def test_repeated_deadlock_raises_visible_failure(self):
        call_id = f"deadlock-exhaust-{frappe.generate_hash(length=8)}"
        payload = {
            "id": call_id,
            "caller": "+966500000099",
            "callee": "+966112223344",
            "state": "ringing",
            "direction": "inbound",
            "timestamp": "2026-04-27 20:30:00",
        }
        self._set_request("test-token-with-32-plus-chars-54321", payload)

        original_sql = frappe.db.sql

        def mock_sql(query, *args, **kwargs):
            if "FOR UPDATE" in query and call_id in str(args):
                e = Exception("Lock wait timeout exceeded; try restarting transaction")
                e.args = (1205, "Lock wait timeout...")
                raise e
            return original_sql(query, *args, **kwargs)

        with patch("gain_maqsam_integration.call_log.frappe.db.sql", side_effect=mock_sql), patch(
            "gain_maqsam_integration.call_log.time.sleep",
            return_value=None,
        ):
            with self.assertRaises(Exception) as ctx:
                maqsam_receive_call_event()

        self.assertIn("database lock contention", str(ctx.exception))
        self.assertFalse(frappe.db.exists("Maqsam Call Log", {"maqsam_call_id": call_id}))
