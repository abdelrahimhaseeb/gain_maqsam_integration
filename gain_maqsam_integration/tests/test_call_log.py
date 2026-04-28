from __future__ import annotations

import unittest

import frappe

from gain_maqsam_integration.call_log import (
    _parse_timestamp,
    extract_maqsam_call_id,
    infer_outcome,
    upsert_maqsam_call,
)


class TestParseTimestamp(unittest.TestCase):
    def test_iso_z_is_naive_utc(self):
        result = _parse_timestamp("2026-04-27T20:30:00Z")
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.hour, 20)
        self.assertIsNone(result.tzinfo)

    def test_iso_offset_converts_to_utc(self):
        result = _parse_timestamp("2026-04-27T23:30:00+03:00")
        self.assertEqual(result.hour, 20)
        self.assertIsNone(result.tzinfo)

    def test_unix_seconds(self):
        result = _parse_timestamp(1777321800)
        self.assertEqual(result.year, 2026)

    def test_blank_falls_back_to_now(self):
        result = _parse_timestamp("")
        self.assertIsNotNone(result)


class TestInferOutcome(unittest.TestCase):
    def test_answered(self):
        self.assertEqual(infer_outcome("answered"), "Answered")
        self.assertEqual(infer_outcome("connected"), "Answered")

    def test_no_answer(self):
        self.assertEqual(infer_outcome("no_answer"), "No Answer")
        self.assertEqual(infer_outcome("missed"), "No Answer")

    def test_busy(self):
        self.assertEqual(infer_outcome("busy"), "Busy")

    def test_unknown(self):
        self.assertEqual(infer_outcome("ringing"), "")
        self.assertEqual(infer_outcome(None), "")


class TestExtractCallId(unittest.TestCase):
    def test_top_level(self):
        self.assertEqual(extract_maqsam_call_id({"id": " 123 "}), "123")

    def test_nested(self):
        self.assertEqual(extract_maqsam_call_id({"call": {"id": "abc"}}), "abc")

    def test_alias(self):
        self.assertEqual(extract_maqsam_call_id({"callId": "xyz"}), "xyz")

    def test_missing(self):
        self.assertEqual(extract_maqsam_call_id({}), "")


class TestUpsertIdempotency(unittest.TestCase):
    def setUp(self):
        self.call_id = f"test-upsert-{frappe.generate_hash(length=8)}"
        self.created_logs: list[str] = []

    def tearDown(self):
        for name in self.created_logs:
            if frappe.db.exists("Maqsam Call Log", name):
                frappe.delete_doc("Maqsam Call Log", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_second_call_with_same_id_updates(self):
        first = {
            "id": self.call_id,
            "direction": "inbound",
            "caller": "+966500000001",
            "callee": "+966112223344",
            "state": "ringing",
            "timestamp": "2026-04-27 20:30:00",
        }
        name1, created1 = upsert_maqsam_call(first)
        frappe.db.commit()
        self.created_logs.append(name1)
        self.assertTrue(created1)

        second = dict(first, state="in_progress", duration=42)
        name2, created2 = upsert_maqsam_call(second)
        frappe.db.commit()

        self.assertEqual(name1, name2)
        self.assertFalse(created2)
        self.assertEqual(frappe.db.get_value("Maqsam Call Log", name2, "state"), "in_progress")
        self.assertEqual(frappe.db.get_value("Maqsam Call Log", name2, "duration"), 42)

    def test_blank_id_returns_none(self):
        name, created = upsert_maqsam_call({"id": "", "direction": "inbound"})
        self.assertIsNone(name)
        self.assertFalse(created)
