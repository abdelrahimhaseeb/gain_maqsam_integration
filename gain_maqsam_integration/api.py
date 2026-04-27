from __future__ import annotations

import json
import re
from typing import Any

import frappe
from frappe.utils import cstr, now_datetime
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


CLICK_TO_CALL_FIELDS = {
    "Lead": ("mobile_no", "phone", "whatsapp_no"),
    "Contact": ("mobile_no", "phone"),
    "Customer": ("mobile_no", "phone", "default_phone"),
    "Patient": ("mobile", "phone"),
    "Patient Appointment": ("mobile", "phone"),
}


def _only_system_manager() -> None:
    frappe.only_for("System Manager")


def _only_logged_in_user() -> None:
    if frappe.session.user == "Guest":
        frappe.throw("Login required", frappe.PermissionError)


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


def _sync_recent_calls_page(page: int = 1) -> dict[str, Any]:
    calls = get_client().list_calls(page=int(page))
    if not isinstance(calls, list):
        frappe.throw("Maqsam recent calls response was not a list.")

    result = sync_recent_calls(calls)
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
    doc = frappe.get_doc("Maqsam Call Log", call_log)
    doc.check_permission(permission)
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
def maqsam_list_agents(page: int = 0) -> list[dict[str, Any]] | Any:
    _only_system_manager()
    return get_client().list_agents(page=int(page))


@frappe.whitelist()
def maqsam_get_click_to_call_defaults(
    doctype: str | None = None, docname: str | None = None
) -> dict[str, Any]:
    _only_logged_in_user()
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
    _only_logged_in_user()
    client = get_client()
    status = client.get_agent_status(_get_current_user_email())
    status["portal_url"] = client.get_portal_url()
    return status


@frappe.whitelist()
def maqsam_get_caller_profile(
    phone: str | None = None,
    call_log: str | None = None,
    maqsam_call_id: str | None = None,
) -> dict[str, Any]:
    _only_logged_in_user()
    return get_caller_profile(phone=phone, call_log=call_log, maqsam_call_id=maqsam_call_id)


@frappe.whitelist(allow_guest=True)
def maqsam_receive_call_event() -> dict[str, Any]:
    expected_token = _get_incoming_webhook_token()
    received_token = _get_request_token()
    if not expected_token or not received_token or received_token != expected_token:
        frappe.throw("Invalid Maqsam webhook token.", frappe.PermissionError)

    payload = _get_request_payload()
    call = _extract_webhook_call(payload)
    if not call.get("id"):
        frappe.throw("Maqsam webhook payload does not include a call id.")

    log_name, created = upsert_maqsam_call(call)
    frappe.db.commit()

    profile_phone = _get_customer_phone_from_call(call)
    profile = get_caller_profile(phone=profile_phone) if profile_phone else {}
    settings = _get_maqsam_settings()
    agent_email = _extract_agent_email(payload, call)
    target_user = _resolve_user_from_email(agent_email)

    if not target_user and settings:
        target_user = _resolve_user_from_email(cstr(settings.get("default_agent_email")))

    target_users: list[str] = []
    if target_user:
        target_users = [target_user]
    elif settings and settings.get("enable_incoming_call_popup"):
        target_users = [
            u.name
            for u in frappe.get_all(
                "User",
                filters={"enabled": 1, "user_type": "System User", "name": ["!=", "Administrator"]},
                fields=["name"],
            )
        ]

    popup_sent = False
    if settings and settings.get("enable_incoming_call_popup") and target_users:
        event_data = {
            "call_log": log_name,
            "maqsam_call_id": call.get("id"),
            "agent_email": agent_email,
            "state": cstr(call.get("state") or "ringing"),
            "profile": profile,
        }
        for user in target_users:
            frappe.publish_realtime("maqsam_incoming_call", event_data, user=user)
        popup_sent = True

    return {
        "ok": True,
        "call_log": log_name,
        "created": created,
        "popup_sent": popup_sent,
        "target_user": target_user,
        "broadcast_count": len(target_users),
    }


@frappe.whitelist()
def maqsam_save_call_recording(call_log: str) -> dict[str, Any]:
    _only_logged_in_user()

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
    _only_logged_in_user()

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
    _only_logged_in_user()
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
    _only_logged_in_user()
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
    _only_logged_in_user()
    allowed_outcomes = {"Answered", "No Answer", "Busy", "Wrong Number", "Follow Up", "Other"}
    if outcome and outcome not in allowed_outcomes:
        frappe.throw("Invalid call outcome.")

    doc = frappe.get_doc("Maqsam Call Log", call_log)
    doc.check_permission("write")
    doc.outcome = outcome or doc.outcome
    doc.notes = cstr(notes).strip() or doc.notes
    doc.follow_up_required = 1 if int(follow_up_required or 0) else 0
    doc.follow_up_date = follow_up_date if doc.follow_up_required else None
    doc.save()
    return {"ok": True, "call_log": doc.name}


@frappe.whitelist()
def maqsam_sync_recent_calls(page: int = 1) -> dict[str, Any]:
    _only_system_manager()
    if not _maqsam_integration_enabled():
        frappe.throw("Maqsam integration is disabled.")

    return _sync_recent_calls_page(page=int(page))


def maqsam_auto_sync_recent_calls() -> dict[str, Any]:
    if not _maqsam_integration_enabled():
        return {"ok": False, "skipped": "disabled"}

    try:
        return _sync_recent_calls_page(page=1)
    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Maqsam Auto Sync Failed")
        return {"ok": False, "skipped": "error"}
