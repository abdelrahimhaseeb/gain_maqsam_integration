from __future__ import annotations

import re

import frappe
from frappe.model.document import Document


class MaqsamBlockedNumber(Document):
    def validate(self) -> None:
        digits = re.sub(r"\D", "", self.phone_digits or "")
        if not digits:
            frappe.throw("Phone (digits only) is required.")
        self.phone_digits = digits
