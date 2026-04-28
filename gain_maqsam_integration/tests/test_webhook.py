from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from gain_maqsam_integration.api import (
    _extract_agent_email,
    _extract_webhook_call,
    _get_customer_phone_from_call,
    maqsam_receive_call_event,
)


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


class TestWebhookAuth(unittest.TestCase):
    def setUp(self):
        self.created_logs: list[str] = []
        if not frappe.db.exists("DocType", "Maqsam Settings"):
            self.skipTest("Maqsam Settings doctype not installed")
        self.settings = frappe.get_single("Maqsam Settings")
        self.original_token = self.settings.get_password("incoming_webhook_token") or ""
        self.settings.incoming_webhook_token = "test-token-123"
        self.settings.save(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        self.settings.incoming_webhook_token = self.original_token or "placeholder"
        self.settings.save(ignore_permissions=True)
        for name in self.created_logs:
            if frappe.db.exists("Maqsam Call Log", name):
                frappe.delete_doc("Maqsam Call Log", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _set_request(self, token, payload):
        frappe.local.form_dict = frappe._dict({"token": token, **payload})
        frappe.local.request = None

    def test_missing_token_raises_permission_error(self):
        self._set_request("", {"id": "x"})
        with self.assertRaises(frappe.PermissionError):
            maqsam_receive_call_event()

    def test_wrong_token_raises_permission_error(self):
        self._set_request("WRONG", {"id": "x"})
        with self.assertRaises(frappe.PermissionError):
            maqsam_receive_call_event()

    def test_valid_token_with_missing_id_raises_validation(self):
        self._set_request("test-token-123", {})
        with self.assertRaises(frappe.ValidationError):
            maqsam_receive_call_event()

    def test_valid_token_creates_log_and_queues_dispatch(self):
        call_id = f"test-webhook-{frappe.generate_hash(length=8)}"
        self._set_request(
            "test-token-123",
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
