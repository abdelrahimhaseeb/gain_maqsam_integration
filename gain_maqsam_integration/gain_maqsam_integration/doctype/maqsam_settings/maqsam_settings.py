# Copyright (c) 2026, Ghain and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class MaqsamSettings(Document):
    def validate(self) -> None:
        self.base_url = (self.base_url or "").strip()
        self.access_key_id = (self.access_key_id or "").strip()
        self.default_caller = (self.default_caller or "").strip()
        self.default_agent_email = (self.default_agent_email or "").strip()
        self.incoming_webhook_url = (self.incoming_webhook_url or "").strip()
        self.timeout_seconds = cint(self.timeout_seconds or 30)

        if self.timeout_seconds <= 0:
            frappe.throw("Timeout Seconds must be greater than zero.")
