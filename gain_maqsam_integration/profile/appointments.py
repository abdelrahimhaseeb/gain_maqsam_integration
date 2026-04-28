from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import format_datetime, get_datetime, now_datetime

from gain_maqsam_integration.profile.invoices import get_related_patients_and_customers


def get_appointments(matches: list[dict[str, Any]]) -> dict[str, Any]:
    patients, _customers = get_related_patients_and_customers(matches)
    if not patients or not frappe.db.exists("DocType", "Patient Appointment"):
        return {"upcoming": [], "recent": []}

    meta = frappe.get_meta("Patient Appointment")
    fields = [
        "name",
        *[
            field
            for field in (
                "patient",
                "patient_name",
                "status",
                "appointment_date",
                "appointment_time",
                "appointment_datetime",
                "practitioner",
                "department",
                "ref_sales_invoice",
            )
            if meta.has_field(field)
        ],
    ]
    rows = frappe.get_all(
        "Patient Appointment",
        fields=fields,
        filters={"patient": ["in", list(patients)], "docstatus": ["!=", 2]},
        order_by="appointment_datetime desc, appointment_date desc, creation desc",
        limit_page_length=100,
        ignore_permissions=True,
    )
    now = now_datetime()
    upcoming: list[dict[str, Any]] = []
    recent: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        when = item.get("appointment_datetime")
        if not when and item.get("appointment_date"):
            when = get_datetime(item.get("appointment_date"))
        item["appointment_display"] = format_datetime(when) if when else ""
        if when and get_datetime(when) >= now:
            upcoming.append(item)
        else:
            recent.append(item)

    upcoming.sort(
        key=lambda row: get_datetime(row.get("appointment_datetime") or row.get("appointment_date") or now)
    )
    return {"upcoming": upcoming[:5], "recent": recent[:5]}
