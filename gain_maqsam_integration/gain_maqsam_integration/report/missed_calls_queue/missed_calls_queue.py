from __future__ import annotations

from typing import Any

import frappe
from frappe import _


def execute(filters: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    filters = filters or {}
    return _columns(), _data(filters)


def _columns() -> list[dict[str, Any]]:
    return [
        {"label": _("Call"), "fieldname": "name", "fieldtype": "Link", "options": "Maqsam Call Log", "width": 120},
        {"label": _("When"), "fieldname": "timestamp", "fieldtype": "Datetime", "width": 150},
        {"label": _("Caller"), "fieldname": "caller_number", "fieldtype": "Data", "width": 140},
        {"label": _("Linked"), "fieldname": "linked_title", "fieldtype": "Data", "width": 180},
        {"label": _("Linked DocType"), "fieldname": "linked_doctype", "fieldtype": "Link", "options": "DocType", "width": 110},
        {"label": _("Linked Doc"), "fieldname": "linked_docname", "fieldtype": "Dynamic Link", "options": "linked_doctype", "width": 140},
        {"label": _("Agent"), "fieldname": "agent_email", "fieldtype": "Data", "width": 180},
        {"label": _("Outcome"), "fieldname": "outcome", "fieldtype": "Data", "width": 110},
        {"label": _("Follow-up"), "fieldname": "follow_up_required", "fieldtype": "Check", "width": 90},
        {"label": _("Follow-up Date"), "fieldname": "follow_up_date", "fieldtype": "Date", "width": 120},
    ]


def _data(filters: dict[str, Any]) -> list[dict[str, Any]]:
    days = int(filters.get("days") or 7)
    since = frappe.utils.add_days(frappe.utils.now_datetime(), -days)

    conditions = ["direction = 'inbound'", "outcome IN ('No Answer', 'Busy')", "timestamp >= %(since)s"]
    params: dict[str, Any] = {"since": since}

    if filters.get("agent_email"):
        conditions.append("agent_email = %(agent_email)s")
        params["agent_email"] = filters["agent_email"]
    if filters.get("only_pending_followup"):
        conditions.append("(follow_up_required = 1 OR follow_up_required IS NULL)")

    sql = f"""
        SELECT
            name, timestamp, caller_number, linked_title, linked_doctype,
            linked_docname, agent_email, outcome, follow_up_required, follow_up_date
        FROM `tabMaqsam Call Log`
        WHERE {' AND '.join(conditions)}
        ORDER BY timestamp DESC
        LIMIT 500
    """
    return frappe.db.sql(sql, params, as_dict=True)
