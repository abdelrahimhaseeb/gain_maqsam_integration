from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import frappe
from frappe.utils import cint, cstr, get_datetime, now_datetime


SYNC_SOURCE = "Maqsam Sync"
CLICK_TO_CALL_SOURCE = "Gain Click-to-Call"
CALL_LOG_DOCTYPE = "Maqsam Call Log"
UPSERT_MAX_ATTEMPTS = 5
UPSERT_RETRY_BACKOFF_SECONDS = 0.2
TERMINAL_CALL_STATES = {
    "ended",
    "completed",
    "answered",
    "serviced",
    "abandoned",
    "dropped",
    "no_answer",
    "busy",
    "failed",
}


PHONE_LINK_FIELDS = {
    "Patient": ("mobile", "phone"),
    "Customer": ("mobile_no", "phone", "default_phone"),
    "Lead": ("mobile_no", "phone", "whatsapp_no"),
    "Contact": ("mobile_no", "phone"),
}


PHONE_MATCH_SUFFIX_LENGTHS = (12, 11, 10, 9, 8, 7)


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _phone_match_score(left: Any, right: Any) -> int:
    left_digits = _digits(left)
    right_digits = _digits(right)
    if not left_digits or not right_digits:
        return 0

    if left_digits == right_digits:
        return 1000 + len(left_digits)

    for suffix_length in PHONE_MATCH_SUFFIX_LENGTHS:
        if len(left_digits) < suffix_length or len(right_digits) < suffix_length:
            continue
        if left_digits[-suffix_length:] == right_digits[-suffix_length:]:
            return suffix_length

    return 0


def _phone_matches(left: Any, right: Any) -> bool:
    return _phone_match_score(left, right) >= 7


def _normalize_state(state: Any) -> str:
    return cstr(state).strip().lower().replace("-", "_").replace(" ", "_")


def _is_terminal_state(state: Any) -> bool:
    return _normalize_state(state) in TERMINAL_CALL_STATES


def _has_value(value: Any) -> bool:
    return value not in (None, "")


def _values_for_existing_call(doc, values: dict[str, Any], call: dict[str, Any]) -> dict[str, Any]:
    protected = dict(values)

    for fieldname in (
        "agent_email",
        "agent_name",
        "caller_number",
        "callee_number",
        "normalized_phone",
        "direction",
        "call_type",
    ):
        if _has_value(doc.get(fieldname)) and not _has_value(protected.get(fieldname)):
            protected.pop(fieldname, None)

    existing_state = _normalize_state(doc.get("state"))
    incoming_state = _normalize_state(protected.get("state"))
    if existing_state and not incoming_state:
        protected.pop("state", None)
    elif _is_terminal_state(existing_state) and not _is_terminal_state(incoming_state):
        protected.pop("state", None)
        protected.pop("outcome", None)

    if cint(doc.get("duration") or 0) > 0 and cint(protected.get("duration") or 0) <= 0:
        protected.pop("duration", None)

    if doc.get("timestamp") and call.get("timestamp") in (None, ""):
        protected.pop("timestamp", None)

    if doc.get("outcome"):
        protected.pop("outcome", None)

    return protected


def _dump_payload(payload: Any) -> str:
    if payload in (None, ""):
        return ""
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _is_duplicate_maqsam_call_id_error(exc: Exception) -> bool:
    if isinstance(exc, frappe.UniqueValidationError):
        return True

    message = cstr(exc).lower()
    return "maqsam call id" in message and "unique" in message


def _clear_duplicate_maqsam_call_id_message() -> None:
    message_log = getattr(frappe.local, "message_log", None)
    if not isinstance(message_log, list):
        return

    filtered = []
    for item in message_log:
        if isinstance(item, dict):
            haystack = " ".join(
                cstr(item.get(key))
                for key in ("message", "title", "description")
            ).lower()
        else:
            haystack = cstr(item).lower()

        if "maqsam call id" in haystack and "unique" in haystack:
            continue
        filtered.append(item)

    frappe.local.message_log = filtered


def _parse_timestamp(value: Any) -> datetime:
    if value in (None, ""):
        return now_datetime()

    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds)

    try:
        result = get_datetime(value)
    except Exception:
        return now_datetime()

    if result is None:
        return now_datetime()

    if getattr(result, "tzinfo", None) is not None:
        result = result.astimezone(timezone.utc).replace(tzinfo=None)

    return result


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


def _phone_suffix(phone: Any) -> str:
    digits = _digits(phone)
    return digits[-7:] if len(digits) >= 7 else digits


def _phone_search_suffixes(phone: Any) -> list[str]:
    digits = _digits(phone)
    if not digits:
        return []

    suffixes = [digits]
    for length in (12, 10, 9, 7):
        if len(digits) >= length:
            suffixes.append(digits[-length:])
    return list(dict.fromkeys(suffixes))


def find_linked_record_for_numbers(numbers: list[Any]) -> dict[str, str]:
    candidates = [number for number in numbers if _digits(number)]
    if not candidates:
        return {}

    suffixes = {
        suffix
        for candidate in candidates
        for suffix in _phone_search_suffixes(candidate)
    }
    if not suffixes:
        return {}

    best_match: tuple[int, str, str] | None = None
    for doctype, fields in PHONE_LINK_FIELDS.items():
        if not frappe.db.exists("DocType", doctype):
            continue

        meta = frappe.get_meta(doctype)
        available_fields = [field for field in fields if meta.has_field(field)]
        if not available_fields:
            continue

        or_filters = [
            [field, "like", f"%{suffix}%"]
            for field in available_fields
            for suffix in suffixes
        ]
        records = frappe.get_all(
            doctype,
            fields=["name", *available_fields],
            or_filters=or_filters,
            order_by="modified desc",
            limit=250,
            ignore_permissions=True,
        )
        for record in records:
            for field in available_fields:
                score = max(
                    (_phone_match_score(record.get(field), candidate) for candidate in candidates),
                    default=0,
                )
                if score >= 7 and (not best_match or score > best_match[0]):
                    best_match = (score, doctype, record.name)

        if best_match and best_match[0] >= 1000:
            break

    if best_match:
        _score, doctype, docname = best_match
        doc = frappe.get_doc(doctype, docname)
        return {
            "linked_doctype": doctype,
            "linked_docname": docname,
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
    link_context = find_linked_record_for_numbers(
        [callee_number] if direction == "outbound" else [caller_number]
    )

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

    base_values = _build_values_from_maqsam_call(call)
    last_lock_error: Exception | None = None

    for attempt in range(UPSERT_MAX_ATTEMPTS):
        try:
            existing_rows = frappe.db.sql(
                f"SELECT name FROM `tab{CALL_LOG_DOCTYPE}` WHERE maqsam_call_id = %s FOR UPDATE",
                (maqsam_call_id,),
                as_dict=True,
            )

            if existing_rows:
                docname = existing_rows[0].name
                if not frappe.db.exists(CALL_LOG_DOCTYPE, docname):
                    continue
                doc = frappe.get_doc(CALL_LOG_DOCTYPE, docname)

                values = _values_for_existing_call(doc, base_values, call)
                if doc.source == CLICK_TO_CALL_SOURCE:
                    values.pop("source", None)

                doc.update(values)
                doc.save(ignore_permissions=True)
                return doc.name, False

            doc = frappe.new_doc(CALL_LOG_DOCTYPE)
            doc.update(base_values)
            doc.insert(ignore_permissions=True)
            return doc.name, True

        except Exception as exc:
            is_deadlock = False
            message = cstr(exc).lower()
            if getattr(exc, "args", None) and isinstance(exc.args, tuple) and len(exc.args) > 0:
                code = getattr(exc.args[0], "args", [exc.args[0]])[0]
                if code in (1213, 1205):
                    is_deadlock = True
            if "deadlock" in message or "lock wait timeout" in message:
                is_deadlock = True

            if is_deadlock:
                last_lock_error = exc
                frappe.db.rollback()
                if attempt < UPSERT_MAX_ATTEMPTS - 1:
                    time.sleep(UPSERT_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                break

            if _is_duplicate_maqsam_call_id_error(exc):
                _clear_duplicate_maqsam_call_id_message()
                frappe.db.rollback()
                if attempt < UPSERT_MAX_ATTEMPTS - 1:
                    time.sleep(UPSERT_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                break

            raise

    if last_lock_error:
        raise Exception(
            f"Could not upsert Maqsam Call Log for call id {maqsam_call_id!r} "
            f"after {UPSERT_MAX_ATTEMPTS} attempts due to database lock contention."
        ) from last_lock_error

    existing = frappe.db.exists(CALL_LOG_DOCTYPE, {"maqsam_call_id": maqsam_call_id})
    if existing:
        doc = frappe.get_doc(CALL_LOG_DOCTYPE, existing)
        values = _values_for_existing_call(doc, base_values, call)
        if doc.source == CLICK_TO_CALL_SOURCE:
            values.pop("source", None)
        doc.update(values)
        doc.save(ignore_permissions=True)
        return doc.name, False

    raise Exception(
        f"Could not upsert Maqsam Call Log for call id {maqsam_call_id!r} "
        f"after {UPSERT_MAX_ATTEMPTS} attempts."
    )

def sync_recent_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    created = 0
    updated = 0
    logs: list[str] = []
    created_inbound: list[dict[str, Any]] = []

    for call in calls:
        if not isinstance(call, dict):
            continue

        log_name, was_created = upsert_maqsam_call(call)
        if not log_name:
            continue

        logs.append(log_name)
        if was_created:
            created += 1
            direction = str(call.get("direction") or call.get("type") or "").strip().lower()
            if direction == "inbound":
                created_inbound.append({"log_name": log_name, "call": call})
        else:
            updated += 1

    return {"created": created, "updated": updated, "logs": logs, "created_inbound": created_inbound}
