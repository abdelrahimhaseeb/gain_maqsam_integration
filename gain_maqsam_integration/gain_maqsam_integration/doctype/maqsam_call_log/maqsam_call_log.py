from __future__ import annotations

import json

import frappe
from frappe.model.document import Document


class MaqsamCallLog(Document):
    def validate(self) -> None:
        if isinstance(self.raw_payload, (dict, list)):
            self.raw_payload = json.dumps(self.raw_payload, ensure_ascii=False, indent=2)

        if self.follow_up_required and not self.follow_up_date:
            frappe.throw("Follow-up Date is required when Follow-up Required is enabled.")

