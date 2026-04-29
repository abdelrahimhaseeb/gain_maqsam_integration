from __future__ import annotations

from typing import Any

import frappe
from frappe import _


def execute(filters: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    filters = filters or {}
    if not frappe.db.exists("DocType", "Patient Appointment"):
        frappe.throw(_("This report requires the Healthcare app (Patient Appointment doctype)."))
    return _columns(), _data(filters)


def _columns() -> list[dict[str, Any]]:
    return [
        {"label": _("Agent"), "fieldname": "agent_email", "fieldtype": "Data", "width": 220},
        {"label": _("Inbound Answered"), "fieldname": "answered_calls", "fieldtype": "Int", "width": 130},
        {"label": _("Resulted in Appointment"), "fieldname": "appointments_created", "fieldtype": "Int", "width": 180},
        {"label": _("Conversion %"), "fieldname": "conversion_rate", "fieldtype": "Percent", "width": 120},
        {"label": _("Avg Time-to-Book (min)"), "fieldname": "avg_booking_minutes", "fieldtype": "Float", "width": 170},
    ]


def _data(filters: dict[str, Any]) -> list[dict[str, Any]]:
    from_date = filters.get("from_date") or frappe.utils.add_days(frappe.utils.today(), -30)
    to_date = filters.get("to_date") or frappe.utils.today()
    window_hours = int(filters.get("window_hours") or 24)

    # Pull answered inbound calls linked to a Patient
    calls = frappe.db.sql(
        """
        SELECT
            COALESCE(NULLIF(agent_email, ''), 'Unassigned') AS agent_email,
            linked_docname                                  AS patient,
            timestamp                                       AS call_time
        FROM `tabMaqsam Call Log`
        WHERE direction = 'inbound'
          AND outcome = 'Answered'
          AND linked_doctype = 'Patient'
          AND linked_docname IS NOT NULL
          AND DATE(timestamp) BETWEEN %(from_date)s AND %(to_date)s
        """,
        {"from_date": from_date, "to_date": to_date},
        as_dict=True,
    )

    if not calls:
        return []

    patient_names = list({row.patient for row in calls if row.patient})

    # Find appointments for these patients within the window
    apt_rows = frappe.db.sql(
        """
        SELECT
            patient,
            creation
        FROM `tabPatient Appointment`
        WHERE patient IN %(patients)s
          AND docstatus != 2
        """,
        {"patients": tuple(patient_names) or ("__none__",)},
        as_dict=True,
    )
    apts_by_patient: dict[str, list[Any]] = {}
    for apt in apt_rows:
        apts_by_patient.setdefault(apt.patient, []).append(apt.creation)

    aggregates: dict[str, dict[str, Any]] = {}
    for call in calls:
        agent_bucket = aggregates.setdefault(
            call.agent_email,
            {
                "agent_email": call.agent_email,
                "answered_calls": 0,
                "appointments_created": 0,
                "_booking_minutes_sum": 0.0,
                "_booking_minutes_count": 0,
            },
        )
        agent_bucket["answered_calls"] += 1

        candidate_apts = apts_by_patient.get(call.patient) or []
        for apt_creation in candidate_apts:
            delta_minutes = (frappe.utils.get_datetime(apt_creation) - frappe.utils.get_datetime(call.call_time)).total_seconds() / 60
            if 0 <= delta_minutes <= window_hours * 60:
                agent_bucket["appointments_created"] += 1
                agent_bucket["_booking_minutes_sum"] += delta_minutes
                agent_bucket["_booking_minutes_count"] += 1
                break

    rows: list[dict[str, Any]] = []
    for bucket in aggregates.values():
        answered = bucket["answered_calls"]
        booked = bucket["appointments_created"]
        booking_count = bucket.pop("_booking_minutes_count")
        booking_sum = bucket.pop("_booking_minutes_sum")
        bucket["conversion_rate"] = round((booked / answered) * 100, 1) if answered else 0
        bucket["avg_booking_minutes"] = round(booking_sum / booking_count, 1) if booking_count else 0
        rows.append(bucket)

    rows.sort(key=lambda r: r["answered_calls"], reverse=True)
    return rows
