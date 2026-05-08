from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from gain_maqsam_integration.permissions import get_call_log_report_scope, only_maqsam_user


def execute(filters: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    only_maqsam_user()
    filters = filters or {}
    return _columns(), _data(filters)


def _columns() -> list[dict[str, Any]]:
    return [
        {"label": _("Agent"), "fieldname": "agent_email", "fieldtype": "Data", "width": 220},
        {"label": _("Total Calls"), "fieldname": "total_calls", "fieldtype": "Int", "width": 110},
        {"label": _("Inbound"), "fieldname": "inbound_calls", "fieldtype": "Int", "width": 90},
        {"label": _("Outbound"), "fieldname": "outbound_calls", "fieldtype": "Int", "width": 90},
        {"label": _("Answered"), "fieldname": "answered_calls", "fieldtype": "Int", "width": 90},
        {"label": _("No Answer"), "fieldname": "no_answer_calls", "fieldtype": "Int", "width": 100},
        {"label": _("Answer Rate %"), "fieldname": "answer_rate", "fieldtype": "Percent", "width": 110},
        {"label": _("Avg Duration"), "fieldname": "avg_duration", "fieldtype": "Duration", "width": 120},
        {"label": _("Total Talk Time"), "fieldname": "total_duration", "fieldtype": "Duration", "width": 130},
    ]


def _data(filters: dict[str, Any]) -> list[dict[str, Any]]:
    from_date = filters.get("from_date") or frappe.utils.add_days(frappe.utils.today(), -30)
    to_date = filters.get("to_date") or frappe.utils.today()
    scope_condition, scope_params = get_call_log_report_scope()
    conditions = ["DATE(timestamp) BETWEEN %(from_date)s AND %(to_date)s"]
    if scope_condition:
        conditions.append(scope_condition)
    params: dict[str, Any] = {"from_date": from_date, "to_date": to_date, **scope_params}

    rows = frappe.db.sql(
        f"""
        SELECT
            COALESCE(NULLIF(agent_email, ''), 'Unassigned') AS agent_email,
            COUNT(*)                                                            AS total_calls,
            SUM(CASE WHEN direction = 'inbound'  THEN 1 ELSE 0 END)             AS inbound_calls,
            SUM(CASE WHEN direction = 'outbound' THEN 1 ELSE 0 END)             AS outbound_calls,
            SUM(CASE WHEN outcome   = 'Answered' THEN 1 ELSE 0 END)             AS answered_calls,
            SUM(CASE WHEN outcome  IN ('No Answer', 'Busy') THEN 1 ELSE 0 END)  AS no_answer_calls,
            ROUND(AVG(NULLIF(duration, 0)), 0)                                  AS avg_duration,
            SUM(COALESCE(duration, 0))                                          AS total_duration
        FROM `tabMaqsam Call Log`
        WHERE {" AND ".join(conditions)}
        GROUP BY COALESCE(NULLIF(agent_email, ''), 'Unassigned')
        ORDER BY total_calls DESC
        """,
        params,
        as_dict=True,
    )

    for row in rows:
        total = row.get("total_calls") or 0
        answered = row.get("answered_calls") or 0
        row["answer_rate"] = round((answered / total) * 100, 1) if total else 0

    return rows
