from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from gain_maqsam_integration.api import _is_blocked, maqsam_tag_call
from gain_maqsam_integration.call_log import upsert_maqsam_call


class TestBlockedNumber(unittest.TestCase):
    def setUp(self):
        self.created_logs: list[str] = []
        self.created_blocks: list[str] = []
        frappe.set_user("Administrator")

    def tearDown(self):
        for name in self.created_blocks:
            if frappe.db.exists("Maqsam Blocked Number", name):
                frappe.delete_doc("Maqsam Blocked Number", name, ignore_permissions=True, force=True)
        for name in self.created_logs:
            if frappe.db.exists("Maqsam Call Log", name):
                frappe.delete_doc("Maqsam Call Log", name, ignore_permissions=True, force=True)
        frappe.db.commit()

    def test_is_blocked_returns_false_for_unknown(self):
        self.assertFalse(_is_blocked("+966500000123"))
        self.assertFalse(_is_blocked(""))
        self.assertFalse(_is_blocked(None))

    def test_tag_call_creates_blocked_number_and_updates_outcome(self):
        call_id = f"test-tag-{frappe.generate_hash(length=8)}"
        log_name, _ = upsert_maqsam_call(
            {
                "id": call_id,
                "direction": "inbound",
                "caller": "+966500999777",
                "callee": "+966112223344",
                "state": "ended",
                "timestamp": "2026-04-27 21:00:00",
            }
        )
        frappe.db.commit()
        self.created_logs.append(log_name)

        result = maqsam_tag_call(call_log=log_name, label="Wrong Number", reason="testing")

        self.assertTrue(result["ok"])
        self.assertEqual(result["label"], "Wrong Number")
        self.assertEqual(result["blocked"], "966500999777")
        self.created_blocks.append("966500999777")

        self.assertEqual(frappe.db.get_value("Maqsam Call Log", log_name, "outcome"), "Wrong Number")
        self.assertTrue(_is_blocked("+966 50 099 9777"))

    def test_dispatch_skips_blocked_caller(self):
        digits = "966500888666"
        block = frappe.get_doc(
            {
                "doctype": "Maqsam Blocked Number",
                "phone_digits": digits,
                "label": "Spam",
            }
        )
        block.insert(ignore_permissions=True)
        frappe.db.commit()
        self.created_blocks.append(digits)

        from gain_maqsam_integration.api import _dispatch_incoming_call_popup

        with patch(
            "gain_maqsam_integration.api.frappe.publish_realtime"
        ) as publish_mock:
            _dispatch_incoming_call_popup(
                log_name="MCL-FAKE",
                call={"id": "x", "direction": "inbound", "caller": "+" + digits},
                agent_email="",
            )

        publish_mock.assert_not_called()

    def test_invalid_label_raises(self):
        with self.assertRaises(frappe.ValidationError):
            maqsam_tag_call(call_log="nonexistent", label="NotAnOption")
