from __future__ import annotations

import frappe


MAQSAM_SUPERVISOR_ROLE = "Maqsam Supervisor"


def execute() -> None:
    if frappe.db.exists("Role", MAQSAM_SUPERVISOR_ROLE):
        return

    frappe.get_doc(
        {
            "doctype": "Role",
            "role_name": MAQSAM_SUPERVISOR_ROLE,
            "desk_access": 1,
        }
    ).insert(ignore_permissions=True)
