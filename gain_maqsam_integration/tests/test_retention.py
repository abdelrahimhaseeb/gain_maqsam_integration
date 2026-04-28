from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from gain_maqsam_integration.api import _resolve_retention_days


class TestResolveRetentionDays(unittest.TestCase):
    def _settings(self, **fields):
        # Build a fake "Maqsam Settings" doc that responds to .get(...)
        return MagicMock(get=lambda field, default=None: fields.get(field, default))

    def test_explicit_override_takes_priority(self):
        with patch(
            "gain_maqsam_integration.api._get_maqsam_settings",
            return_value=self._settings(disable_recording_cleanup=1, recording_retention_days=30),
        ):
            self.assertEqual(
                _resolve_retention_days(
                    "disable_recording_cleanup",
                    "recording_retention_days",
                    90,
                    180,
                ),
                180,
            )

    def test_explicit_zero_means_disabled(self):
        with patch("gain_maqsam_integration.api._get_maqsam_settings", return_value=None):
            self.assertIsNone(
                _resolve_retention_days(
                    "disable_recording_cleanup",
                    "recording_retention_days",
                    90,
                    0,
                ),
            )

    def test_disable_flag_returns_none(self):
        with patch(
            "gain_maqsam_integration.api._get_maqsam_settings",
            return_value=self._settings(disable_recording_cleanup=1, recording_retention_days=90),
        ):
            self.assertIsNone(
                _resolve_retention_days(
                    "disable_recording_cleanup",
                    "recording_retention_days",
                    90,
                    None,
                ),
            )

    def test_settings_value_used_when_present(self):
        with patch(
            "gain_maqsam_integration.api._get_maqsam_settings",
            return_value=self._settings(disable_recording_cleanup=0, recording_retention_days=180),
        ):
            self.assertEqual(
                _resolve_retention_days(
                    "disable_recording_cleanup",
                    "recording_retention_days",
                    90,
                    None,
                ),
                180,
            )

    def test_falls_back_to_default(self):
        with patch(
            "gain_maqsam_integration.api._get_maqsam_settings",
            return_value=self._settings(disable_recording_cleanup=0, recording_retention_days=0),
        ):
            self.assertEqual(
                _resolve_retention_days(
                    "disable_recording_cleanup",
                    "recording_retention_days",
                    90,
                    None,
                ),
                90,
            )

    def test_no_settings_uses_default(self):
        with patch("gain_maqsam_integration.api._get_maqsam_settings", return_value=None):
            self.assertEqual(
                _resolve_retention_days(
                    "disable_recording_cleanup",
                    "recording_retention_days",
                    90,
                    None,
                ),
                90,
            )
