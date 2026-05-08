from __future__ import annotations

from datetime import datetime, timedelta, timezone

import hmac
import json
import re
from typing import Any

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, cstr, get_datetime, now_datetime
from frappe.utils.file_manager import save_file

from gain_maqsam_integration.call_log import (
    create_gain_call_log,
    extract_maqsam_call_id,
    mark_call_log_failed,
    sync_recent_calls,
    update_gain_call_log_from_response,
    upsert_maqsam_call,
)
from gain_maqsam_integration.caller_profile import get_caller_profile
from gain_maqsam_integration.maqsam_client import get_client
from gain_maqsam_integration.permissions import (
    MAQSAM_AGENT_ROLE,
    can_access_call_log,
    enforce_call_log_access,
    is_maqsam_superuser,
    only_maqsam_user,
)


CLICK_TO_CALL_FIELDS = {
    "Lead": ("mobile_no", "phone", "whatsapp_no"),
    "Contact": ("mobile_no", "phone"),
    "Customer": ("mobile_no", "phone", "default_phone"),
    "Patient": ("mobile", "phone"),
    "Patient Appointment": ("mobile", "phone"),
}

CURRENT_CALL_LOOKBACK_MINUTES = 15
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


def _only_system_manager() -> None:
    frappe.only_for("System Manager")


def _only_logged_in_user() -> None:
    if frappe.session.user == "Guest":
        frappe.throw("Login required", frappe.PermissionError)


def _user_has_role(role: str) -> bool:
    return role in set(frappe.get_roles(frappe.session.user) or [])


def _only_maqsam_user() -> None:
    only_maqsam_user()


def _maqsam_integration_enabled() -> bool:
    if not frappe.db.exists("DocType", "Maqsam Settings"):
        return False

    return bool(frappe.db.get_single_value("Maqsam Settings", "enabled"))


def _get_maqsam_settings():
    if not frappe.db.exists("DocType", "Maqsam Settings"):
        return None

    return frappe.get_single("Maqsam Settings")


def _get_incoming_webhook_token() -> str:
    settings = _get_maqsam_settings()
    if not settings:
        return ""

    try:
        return cstr(settings.get_password("incoming_webhook_token")).strip()
    except Exception:
        return cstr(settings.get("incoming_webhook_token")).strip()


def _get_request_payload() -> dict[str, Any]:
    payload: Any = {}
    if getattr(frappe.local, "request", None):
        payload = frappe.request.get_json(silent=True) or {}

    if not payload:
        payload = dict(frappe.form_dict or {})

    for key in ("cmd", "token"):
        payload.pop(key, None)

    if isinstance(payload.get("payload"), str):
        try:
            payload = json.loads(payload["payload"])
        except ValueError:
            pass

    return payload if isinstance(payload, dict) else {}


def _get_request_token() -> str:
    token = cstr((frappe.form_dict or {}).get("token")).strip()
    if token:
        return token

    if getattr(frappe.local, "request", None):
        for header in ("X-Maqsam-Webhook-Token", "X-Webhook-Token"):
            token = cstr(frappe.request.headers.get(header)).strip()
            if token:
                return token

    return ""


def _extract_webhook_call(payload: dict[str, Any]) -> dict[str, Any]:
    call = payload
    for key in ("call", "data", "message", "result"):
        nested = call.get(key) if isinstance(call, dict) else None
        if isinstance(nested, dict):
            call = nested

    call = dict(call or {})
    maqsam_call_id = extract_maqsam_call_id(call) or extract_maqsam_call_id(payload)
    if maqsam_call_id:
        call["id"] = maqsam_call_id

    for target, aliases in {
        "caller": ("caller", "callerNumber", "from", "fromNumber", "phone"),
        "callerNumber": ("callerNumber", "caller", "from", "fromNumber", "phone"),
        "callee": ("callee", "calleeNumber", "to", "toNumber", "dialedNumber"),
        "calleeNumber": ("calleeNumber", "callee", "to", "toNumber", "dialedNumber"),
        "direction": ("direction", "type", "callDirection"),
        "state": ("state", "status", "callStatus"),
        "timestamp": ("timestamp", "startedAt", "createdAt", "time"),
    }.items():
        if call.get(target) not in (None, ""):
            continue
        for alias in aliases:
            if payload.get(alias) not in (None, ""):
                call[target] = payload.get(alias)
                break

    if not call.get("direction") and str(call.get("type") or "").lower() in {"inbound", "outbound"}:
        call["direction"] = call.get("type")

    agent = call.get("agent") or payload.get("agent")
    if isinstance(agent, dict) and not call.get("agents"):
        call["agents"] = [agent]

    if not call.get("agents"):
        agent_email = call.get("agentEmail") or payload.get("agentEmail") or payload.get("agent_email")
        agent_name = call.get("agentName") or payload.get("agentName") or payload.get("agent_name")
        if agent_email or agent_name:
            call["agents"] = [{"email": agent_email, "name": agent_name}]

    return call


def _extract_agent_email(payload: dict[str, Any], call: dict[str, Any]) -> str:
    agents = call.get("agents") or payload.get("agents") or []
    if isinstance(agents, dict):
        agents = [agents]

    if isinstance(agents, list):
        for agent in agents:
            if isinstance(agent, dict) and agent.get("email"):
                return cstr(agent.get("email")).strip()

    agent = call.get("agent") or payload.get("agent")
    if isinstance(agent, dict) and agent.get("email"):
        return cstr(agent.get("email")).strip()

    return cstr(call.get("agentEmail") or payload.get("agentEmail") or payload.get("agent_email")).strip()


def _resolve_user_from_email(email: str) -> str | None:
    email = cstr(email).strip()
    if not email:
        return None
    if frappe.db.exists("User", email):
        return email
    return frappe.db.get_value("User", {"email": email}, "name")


def _get_customer_phone_from_call(call: dict[str, Any]) -> str:
    direction = cstr(call.get("direction") or call.get("type")).strip().lower()
    if direction == "inbound":
        return cstr(call.get("callerNumber") or call.get("caller")).strip()
    if direction == "outbound":
        return cstr(call.get("calleeNumber") or call.get("callee")).strip()

    return cstr(
        call.get("callerNumber")
        or call.get("caller")
        or call.get("phone")
        or call.get("calleeNumber")
        or call.get("callee")
    ).strip()

def _normalize_call_state(state: Any) -> str:
    return cstr(state).strip().lower().replace("-", "_").replace(" ", "_")


def _is_terminal_call_state(state: Any) -> bool:
    return _normalize_call_state(state) in TERMINAL_CALL_STATES


def _parse_maqsam_timestamp_utc(value: Any):
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)

    try:
        parsed = get_datetime(value)
    except Exception:
        return None

    if not parsed:
        return None
    if getattr(parsed, "tzinfo", None) is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _maqsam_call_is_recent(call: dict[str, Any]) -> bool:
    timestamp = _parse_maqsam_timestamp_utc(call.get("timestamp"))
    if not timestamp:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CURRENT_CALL_LOOKBACK_MINUTES)
    return timestamp >= cutoff


def _current_call_phone_from_row(row: Any) -> str:
    direction = cstr(row.get("direction")).strip().lower()
    if direction == "inbound":
        return cstr(row.get("caller_number") or row.get("normalized_phone")).strip()
    if direction == "outbound":
        return cstr(row.get("callee_number") or row.get("normalized_phone")).strip()

    return cstr(
        row.get("normalized_phone")
        or row.get("caller_number")
        or row.get("callee_number")
    ).strip()


def _can_show_current_call_to_user(row: Any) -> bool:
    if is_maqsam_superuser():
        return True

    # Shared service-desk policy: all Maqsam Agents may view the active inbound
    # caller profile, while historical logs/recordings stay ownership-scoped.
    if cstr(row.get("direction")).strip().lower() == "inbound":
        return True

    return can_access_call_log(row, ptype="read")


def _find_current_call_context_from_logs(include_terminal: bool = False) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CURRENT_CALL_LOOKBACK_MINUTES)
    rows = frappe.get_all(
        "Maqsam Call Log",
        filters={"timestamp": [">=", cutoff.replace(tzinfo=None)]},
        fields=[
            "name",
            "maqsam_call_id",
            "state",
            "direction",
            "agent_email",
            "caller_number",
            "callee_number",
            "normalized_phone",
            "timestamp",
        ],
        order_by="timestamp desc, modified desc",
        limit=25,
        ignore_permissions=True,
    )

    for row in rows:
        terminal = _is_terminal_call_state(row.get("state"))
        if terminal and not include_terminal:
            continue
        if not _can_show_current_call_to_user(row):
            continue

        phone = _current_call_phone_from_row(row)
        if not phone:
            continue

        return {
            "call_log": row.get("name"),
            "maqsam_call_id": row.get("maqsam_call_id"),
            "agent_email": row.get("agent_email"),
            "state": _normalize_call_state(row.get("state")) or "ringing",
            "direction": row.get("direction"),
            "phone": phone,
            "active": not terminal,
        }

    return {}


def _find_current_call_context_from_maqsam_calls(
    calls: list[dict[str, Any]],
    include_terminal: bool = False,
) -> dict[str, Any]:
    for call in calls:
        if not isinstance(call, dict):
            continue

        direction = cstr(call.get("direction") or call.get("type")).strip().lower()
        if direction != "inbound":
            continue
        if not _maqsam_call_is_recent(call):
            continue

        state = _normalize_call_state(call.get("state")) or "ringing"
        terminal = _is_terminal_call_state(state)
        if terminal and not include_terminal:
            continue

        phone = _get_customer_phone_from_call(call)
        if not phone:
            continue

        maqsam_call_id = cstr(call.get("id")).strip()
        log_name = (
            frappe.db.get_value("Maqsam Call Log", {"maqsam_call_id": maqsam_call_id}, "name")
            if maqsam_call_id
            else None
        )

        return {
            "call_log": log_name,
            "maqsam_call_id": maqsam_call_id,
            "agent_email": _extract_agent_email({}, call),
            "state": state,
            "direction": direction,
            "phone": phone,
            "active": not terminal,
        }

    return {}


def _sync_recent_calls_page(page: int = 1) -> dict[str, Any]:
    calls = get_client().list_calls(page=int(page))
    if not isinstance(calls, list):
        frappe.throw("Maqsam recent calls response was not a list.")

    result = sync_recent_calls(calls)
    created_inbound = result.pop("created_inbound", [])
    for item in created_inbound:
        if not isinstance(item, dict):
            continue

        log_name = item.get("log_name")
        call = item.get("call")
        if not log_name or not isinstance(call, dict):
            continue

        frappe.enqueue(
            "gain_maqsam_integration.api._dispatch_incoming_call_popup",
            queue="short",
            now=False,
            enqueue_after_commit=True,
            log_name=log_name,
            call=call,
            agent_email=_extract_agent_email(call, call),
        )

    frappe.db.commit()
    return {"ok": True, "page": int(page), **result}


def _phone_key(value: str) -> str:
    return re.sub(r"[^\d+]", "", value)


def _append_phone_candidate(candidates: list[str], seen: set[str], value: Any) -> None:
    cleaned = cstr(value).strip()
    if not cleaned:
        return

    key = _phone_key(cleaned) or cleaned
    if key in seen:
        return

    seen.add(key)
    candidates.append(cleaned)


def _get_current_user_email() -> str:
    user_email = frappe.db.get_value("User", frappe.session.user, "email") or frappe.session.user
    return cstr(user_email).strip()


def _get_call_log_for_recording(call_log: str, permission: str = "read"):
    doc = enforce_call_log_access(call_log, permission)
    if not doc.maqsam_call_id:
        frappe.throw("This call log does not have a Maqsam Call ID yet.")

    return doc


def _get_recording_file_doc(file_url: str | None):
    if not cstr(file_url).strip():
        return None

    file_name = frappe.db.get_value("File", {"file_url": cstr(file_url).strip()}, "name")
    if not file_name:
        return None

    return frappe.get_doc("File", file_name)


def _recording_filename(doc) -> str:
    return f"maqsam-call-{doc.maqsam_call_id}.mp3"


def _as_bytes(content: bytes | str) -> bytes:
    if isinstance(content, bytes):
        return content

    return content.encode("utf-8")


def _send_recording_response(doc, content: bytes | str, content_type: str | None, download: int | str = 0) -> None:
    disposition = "attachment" if cstr(download).strip().lower() in {"1", "true", "yes"} else "inline"
    frappe.local.response.filename = _recording_filename(doc)
    frappe.local.response.filecontent = _as_bytes(content)
    frappe.local.response.content_type = content_type or doc.recording_content_type or "audio/mpeg"
    frappe.local.response.display_content_as = disposition
    frappe.local.response.type = "download"


def _get_contact_phone_candidates(contact_name: str) -> list[str]:
    contact = frappe.get_cached_doc("Contact", contact_name)
    candidates: list[str] = []
    seen: set[str] = set()

    for fieldname in ("mobile_no", "phone"):
        _append_phone_candidate(candidates, seen, contact.get(fieldname))

    for row in contact.get("phone_nos") or []:
        _append_phone_candidate(candidates, seen, row.phone)

    return candidates


def _get_customer_phone_candidates(doc) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for fieldname in CLICK_TO_CALL_FIELDS["Customer"]:
        _append_phone_candidate(candidates, seen, doc.get(fieldname))

    contact_names: list[str] = []
    if doc.customer_primary_contact:
        contact_names.append(doc.customer_primary_contact)

    linked_contacts = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Contact",
            "link_doctype": "Customer",
            "link_name": doc.name,
        },
        pluck="parent",
    )

    for contact_name in linked_contacts:
        if contact_name not in contact_names:
            contact_names.append(contact_name)

    for contact_name in contact_names:
        for value in _get_contact_phone_candidates(contact_name):
            _append_phone_candidate(candidates, seen, value)

    return candidates


def _get_patient_phone_candidates(doc) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for fieldname in CLICK_TO_CALL_FIELDS["Patient"]:
        _append_phone_candidate(candidates, seen, doc.get(fieldname))

    return candidates


def _get_patient_appointment_phone_candidates(doc) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for fieldname in CLICK_TO_CALL_FIELDS["Patient Appointment"]:
        _append_phone_candidate(candidates, seen, doc.get(fieldname))

    if doc.patient:
        patient = frappe.get_doc("Patient", doc.patient)
        patient.check_permission("read")
        for value in _get_patient_phone_candidates(patient):
            _append_phone_candidate(candidates, seen, value)

    return candidates


def _get_click_to_call_phone_candidates(doctype: str | None, docname: str | None) -> list[str]:
    if not doctype or not docname:
        return []

    if doctype not in CLICK_TO_CALL_FIELDS:
        frappe.throw(f"Unsupported DocType for Maqsam click-to-call: {doctype}")

    doc = frappe.get_doc(doctype, docname)
    doc.check_permission("read")

    if doctype == "Customer":
        return _get_customer_phone_candidates(doc)

    if doctype == "Patient":
        return _get_patient_phone_candidates(doc)

    if doctype == "Patient Appointment":
        return _get_patient_appointment_phone_candidates(doc)

    candidates: list[str] = []
    seen: set[str] = set()

    for fieldname in CLICK_TO_CALL_FIELDS[doctype]:
        _append_phone_candidate(candidates, seen, doc.get(fieldname))

    if doctype == "Contact":
        for value in _get_contact_phone_candidates(doc.name):
            _append_phone_candidate(candidates, seen, value)

    return candidates


@frappe.whitelist()
def maqsam_test_connection() -> dict[str, Any]:
    _only_system_manager()
    return get_client().test_connection()


@frappe.whitelist()
def maqsam_list_recent_calls(page: int = 1) -> list[dict[str, Any]] | Any:
    _only_system_manager()
    return get_client().list_calls(page=int(page))


@frappe.whitelist()
def maqsam_refresh_call_state(call_log: str, max_pages: int = 2) -> dict[str, Any]:
    _only_maqsam_user()
    if not _maqsam_integration_enabled():
        frappe.throw("Maqsam integration is disabled.")

    doc = enforce_call_log_access(call_log, "read")
    call_id = cstr(doc.maqsam_call_id).strip()
    if not call_id:
        frappe.throw("This call log does not have a Maqsam Call ID yet.")

    matched_call: dict[str, Any] | None = None
    client = get_client()
    pages = max(1, min(int(max_pages or 1), 5))

    for page in range(1, pages + 1):
        calls = client.list_calls(page=page)
        if not isinstance(calls, list):
            break

        for call in calls:
            if cstr(call.get("id")).strip() == call_id:
                matched_call = call
                break

        if matched_call or not calls:
            break

    synced = False
    if matched_call:
        log_name, _created = upsert_maqsam_call(matched_call)
        frappe.db.commit()
        if log_name:
            doc = enforce_call_log_access(log_name, "read")
            synced = True

    return {
        "ok": True,
        "synced": synced,
        "call_log": doc.name,
        "maqsam_call_id": doc.maqsam_call_id,
        "state": doc.state,
        "outcome": doc.outcome,
        "duration": doc.duration,
    }


@frappe.whitelist()
def maqsam_list_agents(page: int = 0) -> list[dict[str, Any]] | Any:
    _only_system_manager()
    return get_client().list_agents(page=int(page))


@frappe.whitelist()
def maqsam_get_click_to_call_defaults(
    doctype: str | None = None, docname: str | None = None
) -> dict[str, Any]:
    _only_maqsam_user()
    client = get_client()
    agent_email = _get_current_user_email()
    raw_phone_candidates = _get_click_to_call_phone_candidates(doctype, docname)
    caller_options = client.get_available_caller_numbers()
    default_caller = client.default_caller or (caller_options[0] if caller_options else "")
    normalized_phone_candidates: list[str] = []
    normalized_seen: set[str] = set()
    for value in raw_phone_candidates:
        normalized = client.normalize_outbound_phone(value, caller=default_caller)
        _append_phone_candidate(normalized_phone_candidates, normalized_seen, normalized)

    agent_status = client.get_agent_status(agent_email)

    return {
        "default_agent_email": agent_email,
        "default_caller": default_caller,
        "caller_options": caller_options,
        "phone_candidates": normalized_phone_candidates,
        "raw_phone_candidates": raw_phone_candidates,
        "default_phone": normalized_phone_candidates[0] if normalized_phone_candidates else "",
        "agent_status": agent_status,
        "portal_url": client.get_portal_url(),
        "timeout_seconds": int(client.timeout),
        "api_base": client.api_base,
    }


@frappe.whitelist()
def maqsam_get_agent_status() -> dict[str, Any]:
    _only_maqsam_user()
    client = get_client()
    status = client.get_agent_status(_get_current_user_email())
    status["portal_url"] = client.get_portal_url()
    return status

@frappe.whitelist()
def maqsam_get_current_call_profile(sync: int = 1) -> dict[str, Any]:
    _only_maqsam_user()

    context = _find_current_call_context_from_logs()
    recent_calls: list[dict[str, Any]] = []
    if not context and cint(sync):
        try:
            calls = get_client().list_calls(page=1)
            if isinstance(calls, list):
                recent_calls = calls
                sync_recent_calls(calls)
                frappe.db.commit()
                context = _find_current_call_context_from_logs()
                if not context:
                    context = _find_current_call_context_from_maqsam_calls(calls)
        except Exception:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), "Maqsam Current Call Sync Failed")

    if not context and recent_calls:
        context = _find_current_call_context_from_maqsam_calls(recent_calls, include_terminal=True)

    if not context:
        context = _find_current_call_context_from_logs(include_terminal=True)

    if not context:
        return {}

    phone = context.get("phone")
    context["profile"] = get_caller_profile(phone=phone) if phone else {}
    return context


@frappe.whitelist()
def maqsam_get_caller_profile(
    phone: str | None = None,
    call_log: str | None = None,
    maqsam_call_id: str | None = None,
) -> dict[str, Any]:
    _only_maqsam_user()
    if call_log:
        enforce_call_log_access(call_log, "read")
        return get_caller_profile(call_log=call_log)

    if maqsam_call_id:
        log_name = frappe.db.get_value(
            "Maqsam Call Log",
            {"maqsam_call_id": cstr(maqsam_call_id).strip()},
            "name",
        )
        if not log_name:
            frappe.throw("Maqsam Call Log was not found for this Maqsam Call ID.", frappe.PermissionError)
        enforce_call_log_access(log_name, "read")
        return get_caller_profile(call_log=log_name)

    if phone and not is_maqsam_superuser():
        frappe.throw("Direct Caller 360 phone lookup requires Maqsam Supervisor access.", frappe.PermissionError)

    return get_caller_profile(phone=phone, call_log=call_log, maqsam_call_id=maqsam_call_id)


def _get_broadcast_users() -> list[str]:
    """Users who should see the incoming-call popup when no specific agent is resolved.

    Limited to users holding the `Maqsam Agent` role to avoid spamming every
    Desk user in the org. If the role does not exist or has no enabled members,
    nobody is notified — the call log is still saved for reporting.
    """
    if not frappe.db.exists("Role", MAQSAM_AGENT_ROLE):
        frappe.log_error(
            title="Maqsam Broadcast Skipped",
            message=(
                f"Role '{MAQSAM_AGENT_ROLE}' does not exist. "
                "No incoming-call popup will be shown until the role is created "
                "and assigned to call-center staff."
            ),
        )
        return []

    rows = frappe.get_all(
        "Has Role",
        filters={"role": MAQSAM_AGENT_ROLE, "parenttype": "User"},
        fields=["parent"],
    )
    users = {row.parent for row in rows}
    if not users:
        return []

    enabled = frappe.get_all(
        "User",
        filters={"enabled": 1, "name": ["in", list(users)]},
        pluck="name",
    )
    return [u for u in enabled if u != "Administrator"]


def _process_maqsam_webhook_payload_async(payload: dict[str, Any], call: dict[str, Any]) -> None:
    original_user = frappe.session.user
    frappe.set_user("Administrator")
    try:
        log_name, created = upsert_maqsam_call(call)
        frappe.db.commit()
        agent_email = _extract_agent_email(payload, call)

        _publish_fast_notification(log_name, call, agent_email)

        if created:
            _dispatch_incoming_call_popup(log_name, call, agent_email)
    finally:
        frappe.set_user(original_user)
        frappe.local.message_log = []


def _maqsam_receive_call_event_sync(payload: dict[str, Any], call: dict[str, Any]) -> dict[str, Any]:
    original_user = frappe.session.user
    frappe.set_user("Administrator")
    try:
        log_name, created = upsert_maqsam_call(call)
        frappe.db.commit()
        agent_email = _extract_agent_email(payload, call)

        _publish_fast_notification(log_name, call, agent_email)

        if created:
            frappe.enqueue(
                "gain_maqsam_integration.api._dispatch_incoming_call_popup",
                queue="short",
                now=False,
                enqueue_after_commit=True,
                log_name=log_name,
                call=call,
                agent_email=agent_email,
            )
    finally:
        frappe.set_user(original_user)
        frappe.local.message_log = []

    return {
        "ok": True,
        "call_log": log_name,
        "created": created,
        "queued": bool(created),
    }


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=120, seconds=60)
def maqsam_receive_call_event() -> dict[str, Any]:
    original_form_dict = getattr(frappe.local, "form_dict", None)
    original_request = getattr(frappe.local, "request", None)
    try:
        expected_token = _get_incoming_webhook_token()
        received_token = _get_request_token()
        if not expected_token or not received_token or not hmac.compare_digest(received_token, expected_token):
            frappe.throw("Invalid Maqsam webhook token.", frappe.PermissionError)

        payload = _get_request_payload()
        call = _extract_webhook_call(payload)
        if not call.get("id"):
            frappe.throw("Maqsam webhook payload does not include a call id.")

        if frappe.flags.in_test:
            return _maqsam_receive_call_event_sync(payload, call)

        # Convert incoming payload to background job entirely to prevent race conditions.
        frappe.enqueue(
            "gain_maqsam_integration.api._process_maqsam_webhook_payload_async",
            queue="short",
            now=False,
            payload=payload,
            call=call,
        )

        return {
            "ok": True,
            "queued": True,
        }
    finally:
        frappe.local.form_dict = original_form_dict
        frappe.local.request = original_request


def _is_blocked(phone: str) -> bool:
    if not phone:
        return False
    digits = re.sub(r"\D", "", str(phone))
    if not digits:
        return False
    return bool(frappe.db.exists("Maqsam Blocked Number", digits))


def _resolve_popup_target_users(agent_email: str, settings) -> list[str]:
    """Pick which user(s) should receive the realtime popup for this call.

    Inbound-call handling is a shared service-desk workflow: any available
    Maqsam Agent should see the caller profile even if Maqsam already attached
    the call to a specific agent email. Ownership checks on call-log actions
    still protect write/update/recording operations.
    """
    return _get_broadcast_users()

def _get_latest_call_state(log_name: str | None, fallback: Any = None) -> str:
    state = cstr(fallback or "ringing").strip() or "ringing"
    if not log_name:
        return state

    try:
        latest_state = frappe.db.get_value("Maqsam Call Log", log_name, "state")
    except Exception:
        return state

    return cstr(latest_state).strip() or state


def _publish_fast_notification(log_name: str, call: dict[str, Any], agent_email: str) -> None:
    """Fire a lightweight `maqsam_incoming_call` event from the webhook hot
    path so the drawer skeleton shows immediately.

    Carries the phone, direction, and state — but NOT the heavy profile
    payload, which is fetched separately in `_dispatch_incoming_call_popup`.
    Wrapped in a broad try/except so a transient publish failure can't fail
    the webhook itself (the call log is already persisted).
    """
    try:
        settings = _get_maqsam_settings()
        if not settings or not settings.get("enable_incoming_call_popup"):
            return

        profile_phone = _get_customer_phone_from_call(call)
        if _is_blocked(profile_phone):
            return

        target_users = _resolve_popup_target_users(agent_email, settings)
        if not target_users:
            return

        event_data = {
            "call_log": log_name,
            "maqsam_call_id": call.get("id"),
            "agent_email": agent_email,
            "state": _get_latest_call_state(log_name, call.get("state") or "ringing"),
            "phone": profile_phone,
            "direction": cstr(call.get("direction") or ""),
            "lite": True,
        }
        for user in target_users:
            frappe.publish_realtime("maqsam_incoming_call", event_data, user=user)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Maqsam Fast Notification Failed")


def _dispatch_incoming_call_popup(log_name: str, call: dict[str, Any], agent_email: str) -> None:
    """Resolve the caller profile and publish the heavy realtime popup event.

    Runs asynchronously after the webhook returns so the lookup latency
    (4-doctype matching + invoices + appointments) doesn't block Maqsam's
    HTTP timeout. Tagged numbers (Wrong Number / Spam / Blocked) skip the
    popup but the call log is still saved for reporting.

    Wrapped in try/except so a profile-lookup failure (bad data, missing
    DocType, transient DB hiccup) gets logged instead of leaving the agent
    staring at the skeleton drawer with no diagnostic trail.
    """
    try:
        settings = _get_maqsam_settings()
        if not settings or not settings.get("enable_incoming_call_popup"):
            return

        target_users = _resolve_popup_target_users(agent_email, settings)
        if not target_users:
            frappe.log_error(
                title="Maqsam Profile Dispatch Skipped",
                message=(
                    f"No target users resolved for call {call.get('id')}. "
                    f"agent_email={agent_email!r}, "
                    f"default_agent_email={cstr(settings.get('default_agent_email'))!r}. "
                    "Either map the agent's email to a Frappe user or assign "
                    "the Maqsam Agent role to call-center staff."
                ),
            )
            return

        profile_phone = _get_customer_phone_from_call(call)
        if _is_blocked(profile_phone):
            return

        original_user = frappe.session.user
        for user in target_users:
            try:
                frappe.set_user(user)
                profile = get_caller_profile(phone=profile_phone) if profile_phone else {}
                event_data = {
                    "call_log": log_name,
                    "maqsam_call_id": call.get("id"),
                    "agent_email": agent_email,
                    "state": _get_latest_call_state(log_name, call.get("state") or "ringing"),
                    "profile": profile,
                }
                frappe.publish_realtime("maqsam_incoming_call", event_data, user=user)
            finally:
                frappe.set_user(original_user)
    except Exception:
        # Don't silently swallow lookup errors — without this log the agent
        # would just see the skeleton drawer forever with no clue why.
        frappe.log_error(
            title="Maqsam Profile Dispatch Failed",
            message=(
                f"call_log={log_name}, maqsam_call_id={call.get('id')}, "
                f"agent_email={agent_email!r}\n\n{frappe.get_traceback()}"
            ),
        )


@frappe.whitelist()
def maqsam_tag_call(call_log: str, label: str, reason: str | None = None) -> dict[str, Any]:
    """Tag a call log as Wrong Number / Spam and add the caller to the block list.

    Future incoming calls from the same digits will set outcome but skip the
    realtime popup.
    """
    _only_maqsam_user()
    allowed = {"Wrong Number", "Spam", "Blocked"}
    if label not in allowed:
        frappe.throw(f"Label must be one of: {', '.join(sorted(allowed))}")

    doc = enforce_call_log_access(call_log, "write")
    doc.outcome = "Wrong Number" if label == "Wrong Number" else "Other"
    note_line = f"[{label}] {cstr(reason).strip()}".strip()
    doc.notes = "\n".join(filter(None, [doc.notes, note_line]))
    doc.save()

    customer_phone = doc.caller_number if doc.direction == "inbound" else doc.callee_number
    digits = re.sub(r"\D", "", cstr(customer_phone))
    if digits and not frappe.db.exists("Maqsam Blocked Number", digits):
        frappe.get_doc(
            {
                "doctype": "Maqsam Blocked Number",
                "phone_digits": digits,
                "label": label,
                "reason": cstr(reason).strip() or None,
                "tagged_by_call_log": doc.name,
            }
        ).insert(ignore_permissions=True)

    frappe.db.commit()
    return {"ok": True, "call_log": doc.name, "blocked": digits or None, "label": label}


@frappe.whitelist()
def maqsam_save_call_recording(call_log: str) -> dict[str, Any]:
    _only_maqsam_user()

    doc = _get_call_log_for_recording(call_log, permission="write")
    file_doc = _get_recording_file_doc(doc.recording_file)
    if file_doc:
        return {
            "ok": True,
            "already_saved": True,
            "call_log": doc.name,
            "file_url": file_doc.file_url,
            "file_size": file_doc.file_size or doc.recording_file_size,
            "content_type": doc.recording_content_type or "audio/mpeg",
        }

    content, content_type = get_client().get_recording(doc.maqsam_call_id)
    file_doc = save_file(
        _recording_filename(doc),
        content,
        "Maqsam Call Log",
        doc.name,
        is_private=1,
        df="recording_file",
    )

    doc.recording_file = file_doc.file_url
    doc.recording_fetched_at = now_datetime()
    doc.recording_file_size = len(content)
    doc.recording_content_type = content_type or "audio/mpeg"
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "ok": True,
        "already_saved": False,
        "call_log": doc.name,
        "file_url": file_doc.file_url,
        "file_size": len(content),
        "content_type": doc.recording_content_type,
    }


@frappe.whitelist()
def maqsam_get_call_recording(call_log: str, download: int = 0) -> None:
    _only_maqsam_user()

    doc = _get_call_log_for_recording(call_log, permission="read")
    file_doc = _get_recording_file_doc(doc.recording_file)
    if file_doc:
        _send_recording_response(
            doc,
            file_doc.get_content(),
            doc.recording_content_type or "audio/mpeg",
            download=download,
        )
        return

    content, content_type = get_client().get_recording(doc.maqsam_call_id)
    _send_recording_response(doc, content, content_type, download=download)


@frappe.whitelist()
def maqsam_get_autologin_url(continue_path: str | None = None) -> dict[str, str]:
    _only_maqsam_user()
    client = get_client()
    return {
        "url": client.get_autologin_url(
            user_email=_get_current_user_email(),
            continue_path=cstr(continue_path).strip() or None,
        )
    }


@frappe.whitelist()
def maqsam_create_click_to_call(
    agent_email: str | None = None,
    phone: str | None = None,
    caller: str | None = None,
    doctype: str | None = None,
    docname: str | None = None,
) -> dict[str, Any]:
    _only_maqsam_user()
    if not cstr(phone).strip():
        frappe.throw("Phone Number is required")

    current_user_email = _get_current_user_email()
    client = get_client()
    normalized_phone = client.normalize_outbound_phone(cstr(phone).strip(), caller=cstr(caller).strip() or None)
    call_log = create_gain_call_log(
        doctype=doctype,
        docname=docname,
        agent_email=current_user_email,
        phone=cstr(phone).strip(),
        caller=cstr(caller).strip() or client.default_caller,
        normalized_phone=normalized_phone,
    )

    try:
        agent_status = client.get_agent_status(current_user_email)
        if not agent_status.get("can_make_outbound_calls"):
            message = cstr(agent_status.get("message"))
            mark_call_log_failed(call_log, message, state="agent_not_ready")
            frappe.db.commit()
            frappe.throw(message)

        response = client.create_call(
            agent_email=current_user_email,
            phone=normalized_phone,
            caller=cstr(caller).strip() or None,
        )
        update_gain_call_log_from_response(call_log, response)
        return {"call_log": call_log, "maqsam": response}
    except Exception as exc:
        if frappe.db.exists("Maqsam Call Log", call_log):
            state = frappe.db.get_value("Maqsam Call Log", call_log, "state")
            if state != "agent_not_ready":
                mark_call_log_failed(call_log, cstr(exc) or "Maqsam call request failed.")
            frappe.db.commit()
        raise


@frappe.whitelist()
def maqsam_update_call_outcome(
    call_log: str,
    outcome: str | None = None,
    notes: str | None = None,
    follow_up_required: int = 0,
    follow_up_date: str | None = None,
) -> dict[str, Any]:
    _only_maqsam_user()
    allowed_outcomes = {"Answered", "No Answer", "Busy", "Wrong Number", "Follow Up", "Other"}
    if outcome and outcome not in allowed_outcomes:
        frappe.throw("Invalid call outcome.")

    doc = enforce_call_log_access(call_log, "write")
    doc.outcome = outcome or doc.outcome
    doc.notes = cstr(notes).strip() or doc.notes
    doc.follow_up_required = 1 if int(follow_up_required or 0) else 0
    doc.follow_up_date = follow_up_date if doc.follow_up_required else None
    doc.save()
    return {"ok": True, "call_log": doc.name}


@frappe.whitelist()
def maqsam_link_call_to_record(call_log: str, doctype: str, docname: str) -> dict[str, Any]:
    _only_maqsam_user()
    allowed_doctypes = {"Patient", "Customer", "Lead", "Contact", "Patient Appointment"}
    if doctype not in allowed_doctypes:
        frappe.throw("Unsupported DocType for Maqsam call linking.")

    target = frappe.get_doc(doctype, docname)
    target.check_permission("read")

    doc = enforce_call_log_access(call_log, "write")
    doc.linked_doctype = doctype
    doc.linked_docname = docname
    doc.linked_title = target.get_title()
    doc.save()
    return {
        "ok": True,
        "call_log": doc.name,
        "linked_doctype": doctype,
        "linked_docname": docname,
        "linked_title": doc.linked_title,
    }


@frappe.whitelist()
def maqsam_sync_recent_calls(page: int = 1) -> dict[str, Any]:
    _only_system_manager()
    if not _maqsam_integration_enabled():
        frappe.throw("Maqsam integration is disabled.")

    return _sync_recent_calls_page(page=int(page))


def _resolve_retention_days(setting_disable: str, setting_days: str, default_days: int, override: int | None) -> int | None:
    """Pick the effective retention window from settings or an explicit override.

    Returns None if cleanup is disabled. Otherwise returns the positive number
    of days to retain.
    """
    if override is not None:
        days = int(override)
        return days if days > 0 else None

    settings = _get_maqsam_settings()
    if settings and settings.get(setting_disable):
        return None

    days = int((settings and settings.get(setting_days)) or default_days)
    return days if days > 0 else None


def maqsam_trim_old_payloads(days: int | None = None) -> dict[str, Any]:
    """Clear raw_payload on call logs older than the configured retention window.

    Wired to the daily scheduler. Reads `payload_retention_days` /
    `disable_payload_cleanup` from Maqsam Settings. Pass `days` to override.
    """
    retention = _resolve_retention_days(
        "disable_payload_cleanup", "payload_retention_days", 90, days
    )
    if retention is None:
        return {"ok": True, "skipped": True, "reason": "payload cleanup disabled"}

    cutoff = frappe.utils.add_days(frappe.utils.today(), -retention)
    frappe.db.sql(
        """
        UPDATE `tabMaqsam Call Log`
        SET raw_payload = NULL
        WHERE raw_payload IS NOT NULL
          AND raw_payload != ''
          AND timestamp < %s
        """,
        (cutoff,),
    )
    affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0]
    frappe.db.commit()
    return {"ok": True, "cutoff": cutoff, "retention_days": retention, "rows_affected": affected}


def maqsam_cleanup_old_recordings(days: int | None = None) -> dict[str, Any]:
    """Delete call-recording files older than the configured retention window.

    Reads `recording_retention_days` / `disable_recording_cleanup` from Maqsam
    Settings. Pass `days` to override. Structured fields (duration, agent,
    summary, ...) are always preserved.
    """
    retention = _resolve_retention_days(
        "disable_recording_cleanup", "recording_retention_days", 90, days
    )
    if retention is None:
        return {"ok": True, "skipped": True, "reason": "recording cleanup disabled"}

    cutoff = frappe.utils.add_days(frappe.utils.today(), -retention)
    candidates = frappe.db.sql(
        """
        SELECT cl.name AS call_log, cl.recording_file
        FROM `tabMaqsam Call Log` cl
        WHERE cl.recording_file IS NOT NULL
          AND cl.recording_file != ''
          AND cl.timestamp < %s
        """,
        (cutoff,),
        as_dict=True,
    )
    deleted = 0
    for row in candidates:
        file_name = frappe.db.get_value("File", {"file_url": row.recording_file}, "name")
        if file_name:
            try:
                frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
                deleted += 1
            except Exception:
                frappe.log_error(
                    title="Maqsam Recording Cleanup",
                    message=f"Failed to delete File {file_name} for {row.call_log}",
                )
                continue

        frappe.db.set_value(
            "Maqsam Call Log",
            row.call_log,
            {
                "recording_file": None,
                "recording_file_size": 0,
                "recording_content_type": None,
                "recording_fetched_at": None,
            },
            update_modified=False,
        )

    frappe.db.commit()
    return {
        "ok": True,
        "cutoff": cutoff,
        "retention_days": retention,
        "deleted": deleted,
        "scanned": len(candidates),
    }


def maqsam_auto_sync_recent_calls() -> dict[str, Any]:
    if not _maqsam_integration_enabled():
        return {"ok": False, "skipped": "disabled"}

    try:
        return _sync_recent_calls_page(page=1)
    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Maqsam Auto Sync Failed")
        return {"ok": False, "skipped": "error"}
