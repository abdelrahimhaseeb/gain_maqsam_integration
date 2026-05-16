from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import format_datetime

from gain_maqsam_integration.permissions import can_access_call_log
from gain_maqsam_integration.profile.phone import digits_only, phone_matches_any, phone_suffix


CALL_LOG_FIELDS = [
    "name",
    "maqsam_call_id",
    "source",
    "direction",
    "state",
    "outcome",
    "agent_email",
    "caller_number",
    "callee_number",
    "normalized_phone",
    "duration",
    "timestamp",
    "linked_doctype",
    "linked_docname",
    "linked_title",
]


def _query_recent_call_rows(or_filters: list[list[Any]], limit: int) -> list[Any]:
    return frappe.get_all(
        "Maqsam Call Log",
        fields=CALL_LOG_FIELDS,
        or_filters=or_filters,
        order_by="timestamp desc, creation desc",
        limit=limit * 3,
        ignore_permissions=True,
    )


def _append_visible_recent_call(
    calls: list[dict[str, Any]],
    seen: set[str],
    row: Any,
    lookup_numbers: list[str],
    limit: int,
) -> None:
    if len(calls) >= limit:
        return

    name = row.get("name")
    if name in seen:
        return
    seen.add(name)

    if not can_access_call_log(row, ptype="read"):
        return
    if not any(
        phone_matches_any(row.get(field), lookup_numbers)
        for field in ("caller_number", "callee_number", "normalized_phone")
    ):
        return

    row = dict(row)
    row["timestamp_display"] = format_datetime(row.get("timestamp")) if row.get("timestamp") else ""
    calls.append(row)


def get_recent_calls(phone: str, limit: int = 10) -> list[dict[str, Any]]:
    lookup_numbers = [phone, digits_only(phone)]
    suffix = phone_suffix(phone)
    if not suffix:
        return []

    exact_numbers = [n for n in lookup_numbers if n]
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()

    if exact_numbers:
        for row in _query_recent_call_rows(
            or_filters=[
                ["caller_number", "in", exact_numbers],
                ["callee_number", "in", exact_numbers],
                ["normalized_phone", "in", exact_numbers],
            ],
            limit=limit,
        ):
            _append_visible_recent_call(calls, seen, row, lookup_numbers, limit)

    if len(calls) < limit:
        for row in _query_recent_call_rows(
            or_filters=[
                ["caller_number", "like", f"%{suffix}%"],
                ["callee_number", "like", f"%{suffix}%"],
                ["normalized_phone", "like", f"%{suffix}%"],
            ],
            limit=limit,
        ):
            _append_visible_recent_call(calls, seen, row, lookup_numbers, limit)

    return calls


def get_customer_facing_number(call_log) -> str:
    direction = str(call_log.get("direction") or "").lower()
    if direction == "inbound":
        return call_log.get("caller_number") or call_log.get("normalized_phone") or ""
    if direction == "outbound":
        return call_log.get("callee_number") or call_log.get("normalized_phone") or ""
    return call_log.get("normalized_phone") or call_log.get("caller_number") or call_log.get("callee_number") or ""


def resolve_lookup_phone(
    phone: str | None = None,
    call_log: str | None = None,
    maqsam_call_id: str | None = None,
) -> str:
    if phone:
        return str(phone).strip()

    log_name = call_log
    if not log_name and maqsam_call_id:
        log_name = frappe.db.get_value("Maqsam Call Log", {"maqsam_call_id": str(maqsam_call_id).strip()}, "name")

    if not log_name:
        return ""

    doc = frappe.get_doc("Maqsam Call Log", log_name)
    doc.check_permission("read")
    return get_customer_facing_number(doc)
