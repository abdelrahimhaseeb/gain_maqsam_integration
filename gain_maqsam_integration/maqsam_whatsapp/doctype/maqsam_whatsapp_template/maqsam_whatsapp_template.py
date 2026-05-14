from __future__ import annotations

import json

from frappe.model.document import Document


class MaqsamWhatsAppTemplate(Document):
    def validate(self) -> None:
        for fieldname in ("raw_payload", "request_payload", "response_payload"):
            if hasattr(self, fieldname) and isinstance(self.get(fieldname), (dict, list)):
                self.set(fieldname, json.dumps(self.get(fieldname), ensure_ascii=True, indent=2, default=str))
