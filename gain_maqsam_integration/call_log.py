from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import frappe
from frappe.utils import cint, get_datetime, now_datetime


SYNC_SOURCE = "Maqsam Sync"
CLICK_TO_CALL_SOURCE = "Gain Click-to-Call"
CALL_LOG_DOCTYPE = "Maqsam Call Log"


PHONE_LINK_FIELDS = {
    "Patient": ("mobile", "phone"),
    "Customer": ("mobile_no", "phone", "default_phone"),
    "Lead": ("mobile_no", "phone", "whatsapp_no"),
    "Contact": ("mobile_no", "phone"),
}


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _phone_matches(left: Any, right: Any) -> bool:
    left_digits = _digits(left)
    right_digits = _digits(right)
    if not left_digits or not right_digits:
        return False

    if left_digits == right_digits:
        return True

    suffix_length = min(9, len(left_digits), len(right_digits))
    return suffix_length >= 7 and left_digits[-suffix_length:] == right_digits[-suffix_length:]


def _dump_payload(payload: Any) -> str:
    if payload in (None, ""):
        return ""
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _parse_timestamp(value: Any) -> datetime:
    if value in (None, ""):
        return now_datetime()

    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds)

    try:
        return get_datetime(value)
    except Exception:
        return now_datetime()


def _extract_nested_value(payload: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(payload, dict):
        return None

    for key in keys:
        if payload.get(key) not in (None, ""):
            return payload.get(key)

    for container_key in ("message", "result", "data", "call"):
        nested = payload.get(container_key)
        if isinstance(nested, dict):
            found = _extract_nested_value(nested, keys)
            if found not in (None, ""):
                return found

    return None


def extract_maqsam_call_id(payload: Any) -> str:
    return str(_extract_nested_value(payload, ("id", "callId", "call_id", "maqsam_call_id")) or "").strip()


def _extract_agent(call: dict[str, Any]) -> tuple[str, str]:
    agents = call.get("agents") or []
    if isinstance(agents, dict):
        agents = [agents]

    if isinstance(agents, list) and agents:
        first = agents[0] if isinstance(agents[0], dict) else {}
        return (
            str(first.get("email") or call.get("agentEmail") or "").strip(),
            str(first.get("name") or first.get("identifier") or call.get("agentName") or "").strip(),
        )

    return (
        str(call.get("agentEmail") or call.get("email") or "").strip(),
        str(call.get("agentName") or "").strip(),
    )


def infer_outcome(state: Any) -> str:
    normalized = str(state or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return ""
    if "busy" in normalized:
        return "Busy"
    if "no_answer" in normalized or "miss" in normalized or "abandon" in normalized:
        return "No Answer"
    if (
        "answer" in normalized
        or "complete" in normalized
        or "connected" in normalized
        or normalized in {"done", "serviced"}
    ):
        return "Answered"
    if "fail" in normalized or "invalid" in normalized:
        return "Other"
    return ""


def get_link_context(doctype: str | None, docname: str | None) -> dict[str, str]:
    if not doctype or not docname or not frappe.db.exists(doctype, docname):
        return {}

    doc = frappe.get_doc(doctype, docname)
    doc.check_permission("read")
    return {
        "linked_doctype": doctype,
        "linked_docname": docname,
        "linked_title": doc.get_title(),
    }


def find_linked_record_for_numbers(numbers: list[Any]) -> dict[str, str]:
    candidates = [number for number in numbers if _digits(number)]
    if not candidates:
        return {}

    for doctype, fields in PHONE_LINK_FIELDS.items():
        if not frappe.db.exists("DocType", doctype):
            continue

        meta = frappe.get_meta(doctype)
        available_fields = [field for field in fields if meta.has_field(field)]
        if not available_fields:
            continue

        records = frappe.get_all(
            doctype,
            fields=["name", *available_fields],
            limit_page_length=500,
            ignore_permissions=True,
        )
        for record in records:
            for field in available_fields:
                if any(_phone_matches(record.get(field), candidate) for candidate in candidates):
                    doc = frappe.get_doc(doctype, record.name)
                    return {
                        "linked_doctype": doctype,
                        "linked_docname": record.name,
                        "linked_title": doc.get_title(),
                    }

    return {}


def create_gain_call_log(
    *,
    doctype: str | None,
    docname: str | None,
    agent_email: str,
    phone: str,
    caller: str | None,
    normalized_phone: str,
) -> str:
    link_context = get_link_context(doctype, docname)
    log = frappe.get_doc(
        {
            "doctype": CALL_LOG_DOCTYPE,
            "source": CLICK_TO_CALL_SOURCE,
            "direction": "outbound",
            "state": "queued",
            "agent_email": agent_email,
            "caller_number": caller,
            "callee_number": phone,
            "normalized_phone": normalized_phone,
            "timestamp": now_datetime(),
            **link_context,
        }
    )
    log.insert(ignore_permissions=True)
    return log.name


def update_gain_call_log_from_response(call_log: str, payload: Any) -> None:
    doc = frappe.get_doc(CALL_LOG_DOCTYPE, call_log)
    maqsam_call_id = extract_maqsam_call_id(payload)
    if maqsam_call_id:
        doc.maqsam_call_id = maqsam_call_id
    doc.state = str(_extract_nested_value(payload, ("state", "status")) or "requested").strip().lower()
    doc.raw_payload = _dump_payload(payload)
    doc.save(ignore_permissions=True)


def mark_call_log_failed(call_log: str, message: str, state: str = "failed") -> None:
    doc = frappe.get_doc(CALL_LOG_DOCTYPE, call_log)
    doc.state = state
    doc.outcome = doc.outcome or "Other"
    doc.notes = "\n".join(filter(None, [doc.notes, message]))
    doc.save(ignore_permissions=True)


def _build_values_from_maqsam_call(call: dict[str, Any]) -> dict[str, Any]:
    caller_number = call.get("callerNumber") or call.get("caller")
    callee_number = call.get("calleeNumber") or call.get("callee")
    state = str(call.get("state") or "").strip().lower()
    direction = str(call.get("direction") or "unknown").strip().lower()
    agent_email, agent_name = _extract_agent(call)
    link_context = find_linked_record_for_numbers([caller_number, callee_number])

    return {
        "maqsam_call_id": str(call.get("id") or "").strip(),
        "source": SYNC_SOURCE,
        "direction": direction or "unknown",
        "state": state,
        "call_type": str(call.get("type") or "").strip(),
        "agent_email": agent_email,
        "agent_name": agent_name,
        "caller_number": caller_number,
        "callee_number": callee_number,
        "normalized_phone": callee_number if direction == "outbound" else caller_number,
        "duration": cint(call.get("duration") or 0),
        "timestamp": _parse_timestamp(call.get("timestamp")),
        "outcome": infer_outcome(state),
        "raw_payload": _dump_payload(call),
        **link_context,
    }


def upsert_maqsam_call(call: dict[str, Any]) -> tuple[str | None, bool]:
    maqsam_call_id = str(call.get("id") or "").strip()
    if not maqsam_call_id:
        return None, False

    values = _build_values_from_maqsam_call(call)
    existing = frappe.db.exists(CALL_LOG_DOCTYPE, {"maqsam_call_id": maqsam_call_id})
    created = not bool(existing)
    doc = frappe.get_doc(CALL_LOG_DOCTYPE, existing) if existing else frappe.new_doc(CALL_LOG_DOCTYPE)

    if not created and doc.source == CLICK_TO_CALL_SOURCE:
        values.pop("source", None)

    if doc.outcome:
        values.pop("outcome", None)

    doc.update(values)
    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    return doc.name, created


def sync_recent_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    created = 0
    updated = 0
    logs: list[str] = []

    for call in calls:
        if not isinstance(call, dict):
            continue

        log_name, was_created = upsert_maqsam_call(call)
        if not log_name:
            continue

        logs.append(log_name)
        if was_created:
            created += 1
        else:
            updated += 1

    return {"created": created, "updated": updated, "logs": logs}
