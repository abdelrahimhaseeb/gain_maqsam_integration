"""Caller-profile facade.

Public entry point used by `api.py`, hooks, and external callers. Delegates to
focused submodules under `gain_maqsam_integration.profile.*`. Existing imports
(`from gain_maqsam_integration.caller_profile import ...`) keep working.
"""

from __future__ import annotations

from typing import Any

import frappe

from gain_maqsam_integration.profile.appointments import get_appointments
from gain_maqsam_integration.profile.calls import (
    CALL_LOG_FIELDS,
    get_customer_facing_number,
    get_recent_calls,
    resolve_lookup_phone,
)
from gain_maqsam_integration.profile.invoices import (
    INVOICE_FIELDS,
    get_invoice_summary,
    get_related_patients_and_customers as _get_related_patients_and_customers,
)
from gain_maqsam_integration.profile.matcher import (
    MATCH_PRIORITY,
    PHONE_LINK_FIELDS,
    find_matches,
)
from gain_maqsam_integration.profile.phone import (
    digits_only,
    phone_matches,
    phone_matches_any,
    phone_suffix as _phone_suffix,
)


def build_profile_summary(
    phone: str,
    matches: list[dict[str, Any]],
    recent_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    primary = matches[0] if matches else None
    last_call = recent_calls[0] if recent_calls else None
    return {
        "input_phone": phone,
        "normalized_phone": digits_only(phone),
        "known_caller": bool(primary),
        "match_count": len(matches),
        "display_name": primary.get("title") if primary else "Unknown Caller",
        "display_type": primary.get("doctype") if primary else "Unknown",
        "last_call": last_call,
        "last_outcome": (last_call or {}).get("outcome") or (last_call or {}).get("state") or "",
    }


def get_caller_profile(
    phone: str | None = None,
    call_log: str | None = None,
    maqsam_call_id: str | None = None,
) -> dict[str, Any]:
    resolved_phone = resolve_lookup_phone(phone=phone, call_log=call_log, maqsam_call_id=maqsam_call_id)
    if not resolved_phone:
        frappe.throw("Phone, Call Log, or Maqsam Call ID is required.")

    matches = find_matches(resolved_phone)
    recent_calls = get_recent_calls(resolved_phone, limit=10)
    invoices = get_invoice_summary(matches)
    appointments = get_appointments(matches)
    summary = build_profile_summary(resolved_phone, matches, recent_calls)

    return {
        "profile_summary": summary,
        "primary_match": matches[0] if matches else None,
        "matches": matches,
        "recent_calls": recent_calls,
        "invoices": invoices,
        "appointments": appointments,
    }


__all__ = [
    "CALL_LOG_FIELDS",
    "INVOICE_FIELDS",
    "MATCH_PRIORITY",
    "PHONE_LINK_FIELDS",
    "_get_related_patients_and_customers",
    "_phone_suffix",
    "build_profile_summary",
    "digits_only",
    "find_matches",
    "get_appointments",
    "get_caller_profile",
    "get_customer_facing_number",
    "get_invoice_summary",
    "get_recent_calls",
    "phone_matches",
    "phone_matches_any",
    "resolve_lookup_phone",
]
