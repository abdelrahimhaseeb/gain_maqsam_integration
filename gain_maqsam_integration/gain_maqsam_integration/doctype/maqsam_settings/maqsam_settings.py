# Copyright (c) 2026, Ghain and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint, cstr, get_url


WEBHOOK_PATH = "/api/method/gain_maqsam_integration.api.maqsam_receive_call_event"
MIN_WEBHOOK_TOKEN_LENGTH = 32


class MaqsamSettings(Document):
    def validate(self) -> None:
        self.base_url = (self.base_url or "").strip()
        self.access_key_id = (self.access_key_id or "").strip()
        self.default_caller = (self.default_caller or "").strip()
        self.default_agent_email = (self.default_agent_email or "").strip()
        self.timeout_seconds = cint(self.timeout_seconds or 30)

        if self.timeout_seconds <= 0:
            frappe.throw("Timeout Seconds must be greater than zero.")

        if not (self.incoming_webhook_url or "").strip():
            self.incoming_webhook_url = f"{get_url()}{WEBHOOK_PATH}"
        else:
            self.incoming_webhook_url = self.incoming_webhook_url.strip()

        self._validate_webhook_token()

    def _validate_webhook_token(self) -> None:
        """Reject weak webhook tokens.

        The webhook URL is publicly reachable (allow_guest=True) and the only
        thing standing between an attacker and the ability to forge call
        events is this shared secret. A short token is brute-forceable; we
        require at least 32 characters and no obvious whitespace/duplication
        patterns. We don't enforce on empty values — the integration may be
        configured before the token is set.
        """
        # Read raw value: fields can be a Password fieldtype (stored encrypted)
        # or a regular Data field for new docs being saved for the first time.
        try:
            token = cstr(self.get_password("incoming_webhook_token") or "").strip()
        except Exception:
            token = cstr(self.get("incoming_webhook_token") or "").strip()

        if not token:
            return

        if len(token) < MIN_WEBHOOK_TOKEN_LENGTH:
            frappe.throw(
                f"Incoming Webhook Token must be at least {MIN_WEBHOOK_TOKEN_LENGTH} "
                f"characters long. Use a high-entropy random string — e.g. "
                f"`openssl rand -hex 32`."
            )

        if len(set(token)) < 8:
            frappe.throw(
                "Incoming Webhook Token has too few unique characters. "
                "Use a high-entropy random string."
            )
