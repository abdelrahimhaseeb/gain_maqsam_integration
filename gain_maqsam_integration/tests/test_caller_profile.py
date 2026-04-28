from __future__ import annotations

import unittest

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
