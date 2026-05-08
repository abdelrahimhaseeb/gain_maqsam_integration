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
        {"label": _("Caller Number"), "fieldname": "caller_number", "fieldtype": "Data", "width": 160},
        {"label": _("Linked"), "fieldname": "linked_title", "fieldtype": "Data", "width": 200},
        {"label": _("Linked DocType"), "fieldname": "linked_doctype", "fieldtype": "Link", "options": "DocType", "width": 110},
        {"label": _("Linked Doc"), "fieldname": "linked_docname", "fieldtype": "Dynamic Link", "options": "linked_doctype", "width": 160},
        {"label": _("Total Calls"), "fieldname": "total_calls", "fieldtype": "Int", "width": 100},
        {"label": _("Answered"), "fieldname": "answered"  , "fieldtype": "Int", "width": 90},
        {"label": _("Missed"),  "fieldname": "missed"     , "fieldtype": "Int", "width": 90},
        {"label": _("Last Call"), "fieldname": "last_call", "fieldtype": "Datetime", "width": 150},
        {"label": _("Total Duration"), "fieldname": "total_duration", "fieldtype": "Duration", "width": 130},
    ]


def _data(filters: dict[str, Any]) -> list[dict[str, Any]]:
    days = int(filters.get("days") or 30)
    limit = int(filters.get("limit") or 50)
    since = frappe.utils.add_days(frappe.utils.now_datetime(), -days)
    scope_condition, scope_params = get_call_log_report_scope()
    conditions = [
        "direction = 'inbound'",
        "timestamp >= %(since)s",
        "caller_number IS NOT NULL AND caller_number != ''",
    ]
    if scope_condition:
        conditions.append(scope_condition)
    params: dict[str, Any] = {"since": since, "limit": limit, **scope_params}

    return frappe.db.sql(
        f"""
        SELECT
            caller_number,
            MAX(linked_title)                                                AS linked_title,
            MAX(linked_doctype)                                              AS linked_doctype,
            MAX(linked_docname)                                              AS linked_docname,
            COUNT(*)                                                         AS total_calls,
            SUM(CASE WHEN outcome = 'Answered' THEN 1 ELSE 0 END)            AS answered,
            SUM(CASE WHEN outcome IN ('No Answer', 'Busy') THEN 1 ELSE 0 END) AS missed,
            MAX(timestamp)                                                   AS last_call,
            SUM(COALESCE(duration, 0))                                       AS total_duration
        FROM `tabMaqsam Call Log`
        WHERE {" AND ".join(conditions)}
        GROUP BY caller_number
        ORDER BY total_calls DESC, last_call DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
