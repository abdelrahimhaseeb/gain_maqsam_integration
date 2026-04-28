from __future__ import annotations

import frappe
from frappe.utils import get_url


MAQSAM_AGENT_ROLE = "Maqsam Agent"
WEBHOOK_PATH = "/api/method/gain_maqsam_integration.api.maqsam_receive_call_event"


def execute() -> None:
    if not frappe.db.exists("Role", MAQSAM_AGENT_ROLE):
        frappe.get_doc(
            {
                "doctype": "Role",
                "role_name": MAQSAM_AGENT_ROLE,
                "desk_access": 1,
            }
        ).insert(ignore_permissions=True)

    if not frappe.db.exists("DocType", "Maqsam Settings"):
        return

    settings = frappe.get_single("Maqsam Settings")
    if not (settings.get("incoming_webhook_url") or "").strip():
        settings.incoming_webhook_url = f"{get_url()}{WEBHOOK_PATH}"
        settings.save(ignore_permissions=True)
