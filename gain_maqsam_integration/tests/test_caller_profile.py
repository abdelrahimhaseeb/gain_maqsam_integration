from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from gain_maqsam_integration.profile import calls as profile_calls
from gain_maqsam_integration.profile import matcher as profile_matcher
from gain_maqsam_integration.caller_profile import (
    _phone_suffix,
    digits_only,
    phone_matches,
)


class TestDigitsOnly(unittest.TestCase):
    def test_strips_non_digits(self):
        self.assertEqual(digits_only("+966 56 434 8436"), "966564348436")

    def test_handles_none(self):
        self.assertEqual(digits_only(None), "")


class TestPhoneSuffix(unittest.TestCase):
    def test_takes_last_seven(self):
        self.assertEqual(_phone_suffix("+966564348436"), "4348436")

    def test_short_number_returns_all(self):
        self.assertEqual(_phone_suffix("12345"), "12345")

    def test_blank(self):
        self.assertEqual(_phone_suffix(""), "")


class TestPhoneMatches(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(phone_matches("966564348436", "966564348436"))

    def test_suffix_match_ignores_country_code(self):
        self.assertTrue(phone_matches("+966 56 434 8436", "0564348436"))

    def test_too_short_suffix_does_not_match(self):
        self.assertFalse(phone_matches("123456", "666123456"))

    def test_blank_returns_false(self):
        self.assertFalse(phone_matches("", "123"))
        self.assertFalse(phone_matches("123", None))

class TestRecentCallsQueryShape(unittest.TestCase):
    def test_exact_match_uses_or_across_caller_callee_and_normalized(self):
        with patch(
            "gain_maqsam_integration.profile.calls.frappe.get_all",
            side_effect=[[], []],
        ) as get_all_mock:
            profile_calls.get_recent_calls("+966500123456")

        first_call_kwargs = get_all_mock.call_args_list[0].kwargs
        self.assertFalse(first_call_kwargs.get("filters"))
        self.assertIn(["caller_number", "in", ["+966500123456", "966500123456"]], first_call_kwargs["or_filters"])
        self.assertIn(["callee_number", "in", ["+966500123456", "966500123456"]], first_call_kwargs["or_filters"])
        self.assertIn(["normalized_phone", "in", ["+966500123456", "966500123456"]], first_call_kwargs["or_filters"])

    def test_suffix_fallback_runs_when_exact_rows_are_filtered_by_permissions(self):
        exact_row = frappe._dict(
            {
                "name": "MCL-HIDDEN",
                "caller_number": "+966500123456",
                "callee_number": "",
                "normalized_phone": "+966500123456",
            }
        )
        fallback_row = frappe._dict(
            {
                "name": "MCL-VISIBLE",
                "caller_number": "0500123456",
                "callee_number": "",
                "normalized_phone": "0500123456",
            }
        )

        with patch(
            "gain_maqsam_integration.profile.calls.frappe.get_all",
            side_effect=[[exact_row], [fallback_row]],
        ), patch(
            "gain_maqsam_integration.profile.calls.can_access_call_log",
            side_effect=lambda row, ptype="read": row.get("name") == "MCL-VISIBLE",
        ):
            result = profile_calls.get_recent_calls("+966500123456")

        self.assertEqual([row["name"] for row in result], ["MCL-VISIBLE"])


class TestMatcherFallback(unittest.TestCase):
    def test_suffix_fallback_runs_when_exact_records_are_filtered_by_permissions(self):
        class FakeMeta:
            def has_field(self, fieldname):
                return fieldname in {"mobile_no", "lead_name"}

        exact_row = frappe._dict(
            {
                "name": "LEAD-HIDDEN",
                "mobile_no": "+966500123456",
                "lead_name": "Hidden Lead",
            }
        )
        fallback_row = frappe._dict(
            {
                "name": "LEAD-VISIBLE",
                "mobile_no": "0500123456",
                "lead_name": "Visible Lead",
            }
        )
        matches = []

        with patch("gain_maqsam_integration.profile.matcher.frappe.db.exists", return_value=True), patch(
            "gain_maqsam_integration.profile.matcher.frappe.get_meta",
            return_value=FakeMeta(),
        ), patch(
            "gain_maqsam_integration.profile.matcher.frappe.get_all",
            side_effect=[[exact_row], [fallback_row]],
        ), patch(
            "gain_maqsam_integration.profile.matcher.can_read_document",
            side_effect=lambda doctype, name: name == "LEAD-VISIBLE",
        ):
            profile_matcher._match_standard_doctype(
                "Lead",
                ["+966500123456", "966500123456"],
                matches,
                set(),
            )

        self.assertEqual([match["name"] for match in matches], ["LEAD-VISIBLE"])
