from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import cint, cstr, get_datetime, now_datetime

from gain_maqsam_integration.permissions import (
    can_read_document,
    is_maqsam_agent,
    is_maqsam_superuser,
    only_maqsam_user,
)
from gain_maqsam_integration.maqsam_whatsapp.client import (
    get_client,
    get_default_whatsapp_country_code,
    validate_whatsapp_phone,
)
from gain_maqsam_integration.maqsam_whatsapp.permissions import can_access_whatsapp_record
from gain_maqsam_integration.profile.phone import phone_matches

PHONE_FIELDS = (
    "mobile_no",
    "mobile",
    "phone",
    "phone_no",
    "contact_number",
    "whatsapp_no",
    "whatsapp_number",
)

AGENT_ALLOWED_REFERENCE_DOCTYPES = {"Lead", "Contact", "Customer", "Patient", "Patient Appointment"}


def _ensure_whatsapp_enabled() -> None:
    only_maqsam_user()
    if not frappe.db.exists("DocType", "Maqsam Settings"):
        frappe.throw("Maqsam Settings are not installed.", frappe.PermissionError)
    if not cint(frappe.db.get_single_value("Maqsam Settings", "enabled")):
        frappe.throw("Maqsam integration is disabled.", frappe.PermissionError)


def _as_check(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if value in (None, ""):
        return 0
    return 1 if cstr(value).strip().lower() in {"1", "true", "yes", "y", "active", "enabled"} else 0


def _coerce_datetime(value: Any):
    if value in (None, ""):
        return None
    try:
        return get_datetime(value)
    except Exception:
        return None


def _stringify_safe(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    return cstr(value)


def _is_approved_active_template(doc: Any) -> bool:
    return cstr(doc.get("status") if hasattr(doc, "get") else getattr(doc, "status", "")).strip().lower() == "approved" and bool(
        cint(doc.get("active") if hasattr(doc, "get") else getattr(doc, "active", 0))
    )


def _template_projection(doc: Any) -> dict[str, Any]:
    return {
        "name": doc.get("name"),
        "template_id": doc.get("template_id"),
        "template_name": doc.get("template_name"),
        "identity_number": doc.get("identity_number"),
        "active": cint(doc.get("active")),
        "status": doc.get("status"),
        "language": doc.get("language"),
        "category": doc.get("category"),
        "maqsam_created_at": cstr(doc.get("maqsam_created_at") or ""),
        "content": doc.get("content"),
    }


def _get_local_approved_active_templates() -> list[dict[str, Any]]:
    rows = frappe.get_all(
        "Maqsam WhatsApp Template",
        fields=[
            "name",
            "template_id",
            "template_name",
            "identity_number",
            "active",
            "status",
            "language",
            "category",
            "maqsam_created_at",
            "content",
        ],
        order_by="template_name asc, template_id asc",
    )
    return [_template_projection(row) for row in rows if _is_approved_active_template(row)]


def _get_suggested_templates(limit: int = 5) -> list[str]:
    templates = _get_local_approved_active_templates()
    return [row["name"] for row in templates[:limit] if row.get("name")]


def _enforce_agent_reference_allowlist(reference_doctype: str) -> None:
    if is_maqsam_agent() and not is_maqsam_superuser() and reference_doctype not in AGENT_ALLOWED_REFERENCE_DOCTYPES:
        frappe.throw("Maqsam Agents can only send WhatsApp messages for Lead, Contact, Customer, Patient, or Patient Appointment records.", frappe.PermissionError)


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=True, sort_keys=True, default=str)


def _parse_json(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            frappe.throw("Invalid JSON payload.", frappe.ValidationError)
    return value


def _extract_items(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_items(value, keys)
            if nested:
                return nested
    for key in ("message", "result", "data"):
        value = payload.get(key)
        if isinstance(value, (dict, list)):
            nested = _extract_items(value, keys)
            if nested:
                return nested
    return []


def _has_items_container(payload: Any, keys: tuple[str, ...]) -> bool:
    if isinstance(payload, list):
        return True
    if not isinstance(payload, dict):
        return False
    for key in keys:
        if isinstance(payload.get(key), list):
            return True
    for key in ("message", "result", "data"):
        value = payload.get(key)
        if isinstance(value, (dict, list)) and _has_items_container(value, keys):
            return True
    return False


def _first_value(payload: Any, *keys: str) -> Any:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for nested_key in ("message", "result", "data"):
            value = payload.get(nested_key)
            if isinstance(value, dict):
                nested = _first_value(value, *keys)
                if nested not in (None, ""):
                    return nested
    return None


def _conversation_id_from_response(payload: Any) -> str:
    direct = _first_value(payload, "conversation_id", "conversationId")
    if direct not in (None, ""):
        return cstr(direct).strip()

    containers = [payload]
    if isinstance(payload, dict):
        containers.extend(value for key in ("message", "result", "data") if isinstance((value := payload.get(key)), dict))

    for container in containers:
        if not isinstance(container, dict):
            continue
        conversation = container.get("conversation")
        if isinstance(conversation, dict):
            value = conversation.get("id") or conversation.get("conversation_id") or conversation.get("conversationId")
            if value not in (None, ""):
                return cstr(value).strip()
        elif conversation not in (None, ""):
            return cstr(conversation).strip()

    return ""


def _template_external_id(template_payload: dict[str, Any]) -> str:
    return cstr(
        template_payload.get("template_id")
        or template_payload.get("templateId")
        or template_payload.get("id")
        or template_payload.get("name")
        or template_payload.get("template_name")
        or template_payload.get("templateName")
    ).strip()


def _upsert_template(template_payload: dict[str, Any]) -> str | None:
    template_id = _template_external_id(template_payload)
    if not template_id:
        return None

    existing = frappe.db.exists("Maqsam WhatsApp Template", {"template_id": template_id})
    doc = frappe.get_doc("Maqsam WhatsApp Template", existing) if existing else frappe.new_doc("Maqsam WhatsApp Template")
    doc.template_id = template_id
    doc.template_name = cstr(
        template_payload.get("template_name")
        or template_payload.get("templateName")
        or template_payload.get("name")
        or template_id
    )[:140]
    doc.identity_number = cstr(
        template_payload.get("identity_number")
        or template_payload.get("identityNumber")
        or template_payload.get("identity")
        or template_payload.get("identityId")
    )[:140]
    doc.active = _as_check(template_payload.get("active") if "active" in template_payload else template_payload.get("isActive"))
    doc.language = cstr(template_payload.get("language") or template_payload.get("lang"))[:40]
    doc.status = cstr(template_payload.get("status") or template_payload.get("state"))[:40]
    doc.category = cstr(template_payload.get("category") or template_payload.get("type"))[:80]
    doc.maqsam_created_at = _coerce_datetime(
        template_payload.get("maqsam_created_at")
        or template_payload.get("created_at")
        or template_payload.get("createdAt")
    )
    doc.content = cstr(template_payload.get("content") or template_payload.get("body") or template_payload.get("text"))
    doc.raw_payload = _json_dumps(template_payload)
    if existing:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)
    return doc.name


def _deactivate_templates_missing_from_remote(remote_template_ids: set[str]) -> int:
    rows = frappe.get_all(
        "Maqsam WhatsApp Template",
        fields=["name", "template_id", "active", "status"],
        filters={"active": 1},
    )
    deactivated = 0
    for row in rows:
        template_id = cstr(row.get("template_id") or row.get("name")).strip()
        if template_id in remote_template_ids:
            continue
        doc = frappe.get_doc("Maqsam WhatsApp Template", row.name)
        doc.active = 0
        doc.status = "missing_from_maqsam"
        doc.save(ignore_permissions=True)
        deactivated += 1
    return deactivated


def _phones_match(left: str, right: str) -> bool:
    return phone_matches(left, right)


def _append_unique_phone(candidates: list[str], seen: set[str], value: Any) -> None:
    phone = cstr(value).strip()
    if not phone:
        return
    key = "".join(ch for ch in phone if ch.isdigit()) or phone
    if key in seen:
        return
    seen.add(key)
    candidates.append(phone)


def _get_reference_phone_candidates(reference_doctype: str, reference_name: str) -> list[str]:
    doc = frappe.get_doc(reference_doctype, reference_name)
    candidates: list[str] = []
    seen: set[str] = set()
    meta = frappe.get_meta(reference_doctype)
    for fieldname in PHONE_FIELDS:
        if meta.has_field(fieldname):
            value = doc.get(fieldname)
            _append_unique_phone(candidates, seen, value)

    if reference_doctype == "Patient Appointment" and doc.get("patient") and can_read_document("Patient", doc.patient):
        for patient_phone in _get_reference_phone_candidates("Patient", doc.patient):
            _append_unique_phone(candidates, seen, patient_phone)

    return candidates


def _resolve_template(template: str | None = None, template_id: str | None = None) -> tuple[str, str]:
    template_key = cstr(template_id or template).strip()
    if not template_key:
        frappe.throw("WhatsApp template is required.", frappe.ValidationError)

    local_name = template_key if frappe.db.exists("Maqsam WhatsApp Template", template_key) else frappe.db.exists(
        "Maqsam WhatsApp Template", {"template_id": template_key}
    )
    if not local_name:
        frappe.throw("WhatsApp template must be synced locally before sending.", frappe.PermissionError)

    doc = frappe.get_doc("Maqsam WhatsApp Template", local_name)
    if cstr(doc.status).strip().lower() != "approved" or not cint(doc.active):
        frappe.throw("Only approved and active WhatsApp templates can be sent.", frappe.PermissionError)

    return doc.name, cstr(doc.template_id or template_key).strip()


def _resolve_recipient_phone(
    *,
    phone: str | None = None,
    reference_doctype: str | None = None,
    reference_name: str | None = None,
) -> str:
    phone = cstr(phone).strip()
    reference_doctype = cstr(reference_doctype).strip()
    reference_name = cstr(reference_name).strip()

    if not reference_doctype and not reference_name:
        if not phone:
            frappe.throw("Recipient phone or readable reference is required.", frappe.ValidationError)
        if not is_maqsam_superuser():
            frappe.throw("Direct WhatsApp phone sends require Maqsam Supervisor or System Manager.", frappe.PermissionError)
        return phone

    if not reference_doctype or not reference_name:
        frappe.throw("Both reference_doctype and reference_name are required.", frappe.ValidationError)

    _enforce_agent_reference_allowlist(reference_doctype)

    if not can_read_document(reference_doctype, reference_name):
        frappe.throw("You do not have permission to send WhatsApp messages for this record.", frappe.PermissionError)

    candidates = _get_reference_phone_candidates(reference_doctype, reference_name)
    if phone:
        if is_maqsam_superuser() or any(_phones_match(phone, candidate) for candidate in candidates):
            return phone
        frappe.throw("The supplied phone does not belong to the readable reference record.", frappe.PermissionError)

    if candidates:
        return candidates[0]

    frappe.throw("The selected reference record has no supported phone field.", frappe.ValidationError)


def _upsert_conversation(
    *,
    conversation_id: str,
    payload: Any,
    phone: str | None = None,
    reference_doctype: str | None = None,
    reference_name: str | None = None,
    sent_by_user: str | None = None,
) -> str:
    existing = frappe.db.exists("Maqsam WhatsApp Conversation", {"conversation_id": conversation_id})
    doc = frappe.get_doc("Maqsam WhatsApp Conversation", existing) if existing else frappe.new_doc("Maqsam WhatsApp Conversation")
    doc.conversation_id = conversation_id
    if phone:
        doc.phone = phone
    status = _first_value(payload, "status", "state")
    if status:
        doc.status = cstr(status)[:40]
    if reference_doctype:
        doc.reference_doctype = reference_doctype
    if reference_name:
        doc.reference_name = reference_name
    if sent_by_user and not doc.sent_by_user:
        doc.sent_by_user = sent_by_user
    doc.last_message_at = now_datetime()
    preview = _first_value(payload, "last_message", "lastMessage", "preview", "text")
    if preview:
        doc.last_message_preview = cstr(preview)[:1000]
    doc.raw_payload = _json_dumps(payload)
    if existing:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)
    return doc.name


def _extract_conversation_messages(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        message_items = payload
    elif isinstance(payload, dict):
        message_items = []
        for key in ("messages", "conversation_messages", "conversationMessages", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                message_items = value
                break
        if not message_items:
            for key in ("conversation", "message", "result", "data"):
                value = payload.get(key)
                if isinstance(value, (dict, list)):
                    message_items = _extract_conversation_messages(value)
                    if message_items:
                        break
    else:
        message_items = []

    summaries: list[dict[str, Any]] = []
    for item in message_items:
        if not isinstance(item, dict):
            continue
        summary = {
            "message_id": _stringify_safe(_first_value(item, "message_id", "messageId", "id")),
            "timestamp": _stringify_safe(_first_value(item, "timestamp", "created_at", "createdAt", "sent_at", "sentAt")),
            "direction": _stringify_safe(_first_value(item, "direction", "type")),
            "state": _stringify_safe(_first_value(item, "state")),
            "status": _stringify_safe(_first_value(item, "status")),
            "content": _stringify_safe(_first_value(item, "content", "text", "body", "message")),
        }
        summaries.append({key: value for key, value in summary.items() if value not in (None, "")})
    return summaries


def _conversation_projection(local_name: str | None, conversation_id: str, payload: Any) -> dict[str, Any]:
    status = _first_value(payload, "status", "state")
    last_message_at = _first_value(payload, "last_message_at", "lastMessageAt", "updated_at", "updatedAt", "created_at", "createdAt")
    if local_name and frappe.db.exists("Maqsam WhatsApp Conversation", local_name):
        local_doc = frappe.get_doc("Maqsam WhatsApp Conversation", local_name)
        status = status or local_doc.status
        last_message_at = last_message_at or local_doc.last_message_at

    return {
        "ok": True,
        "conversation": local_name,
        "conversation_id": conversation_id,
        "status": _stringify_safe(status),
        "last_message_at": _stringify_safe(last_message_at),
        "messages": _extract_conversation_messages(payload),
    }


def _enforce_conversation_access(conversation_id: str) -> str | None:
    only_maqsam_user()
    if is_maqsam_superuser():
        return frappe.db.exists("Maqsam WhatsApp Conversation", {"conversation_id": conversation_id})

    existing = frappe.db.exists("Maqsam WhatsApp Conversation", {"conversation_id": conversation_id})
    if not existing:
        frappe.throw("You can only access WhatsApp conversations already linked to your readable records.", frappe.PermissionError)

    doc = frappe.get_doc("Maqsam WhatsApp Conversation", existing)
    if not can_access_whatsapp_record(doc, permission_type="read"):
        frappe.throw("You do not have permission to access this WhatsApp conversation.", frappe.PermissionError)
    return existing


@frappe.whitelist()
def maqsam_whatsapp_list_templates(sync: int | str = 0) -> dict[str, Any]:
    _ensure_whatsapp_enabled()
    synced = 0
    deactivated = 0
    if cint(sync):
        if not is_maqsam_superuser():
            frappe.throw("Only Maqsam Supervisor or System Manager can sync WhatsApp templates from Maqsam.", frappe.PermissionError)
        payload = get_client().list_templates()
        item_keys = ("templates", "data", "items", "results")
        if not _has_items_container(payload, item_keys):
            frappe.throw("Maqsam templates response did not include a templates list.", frappe.ValidationError)
        templates = _extract_items(payload, item_keys)
        remote_template_ids = {_template_external_id(item) for item in templates if _template_external_id(item)}
        synced = len([name for item in templates if (name := _upsert_template(item))])
        deactivated = _deactivate_templates_missing_from_remote(remote_template_ids)
        frappe.db.commit()

    return {"ok": True, "templates": _get_local_approved_active_templates(), "synced": synced, "deactivated": deactivated}


@frappe.whitelist()
def maqsam_whatsapp_send_template(
    template: str | None = None,
    template_id: str | None = None,
    phone: str | None = None,
    reference_doctype: str | None = None,
    reference_name: str | None = None,
    variables: Any = None,
    language: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    _ensure_whatsapp_enabled()
    local_template, external_template_id = _resolve_template(template=template, template_id=template_id)
    recipient_phone = _resolve_recipient_phone(
        phone=phone,
        reference_doctype=reference_doctype,
        reference_name=reference_name,
    )
    variables_payload = _parse_json(variables, default={})
    client = get_client()
    normalized_phone = validate_whatsapp_phone(
        recipient_phone,
        base_client=getattr(client, "base_client", None),
    )

    request_payload = client._build_send_payload(
        phone=normalized_phone,
        template_id=external_template_id,
        variables=variables_payload,
    ) if hasattr(client, "_build_send_payload") else {
        "RecipientPhone": normalized_phone,
        "TemplateId": external_template_id,
        **({"TemplateVariables": json.dumps(variables_payload, ensure_ascii=True, sort_keys=True)} if variables_payload not in (None, {}, []) else {}),
    }
    message_doc = frappe.get_doc(
        {
            "doctype": "Maqsam WhatsApp Message",
            "direction": "Outbound",
            "status": "Pending",
            "template": local_template,
            "template_id": external_template_id,
            "recipient_phone": normalized_phone,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "sent_by_user": frappe.session.user,
            "request_payload": _json_dumps(request_payload),
        }
    )
    message_doc.insert(ignore_permissions=True)
    frappe.db.commit()

    try:
        response = client.send_template_message(
            phone=normalized_phone,
            template_id=external_template_id,
            variables=variables_payload,
        )
    except Exception as exc:
        message_doc.status = "Failed"
        message_doc.error = cstr(exc)[:1000]
        message_doc.save(ignore_permissions=True)
        frappe.db.commit()
        raise

    external_message_id = cstr(_first_value(response, "message_id", "messageId", "id") or "")
    external_conversation_id = _conversation_id_from_response(response) or cstr(conversation_id).strip()
    conversation_name = None
    if external_conversation_id:
        conversation_name = _upsert_conversation(
            conversation_id=external_conversation_id,
            payload=response,
            phone=normalized_phone,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
            sent_by_user=frappe.session.user,
        )

    message_doc.status = "Sent"
    message_doc.message_id = external_message_id
    message_doc.conversation_id = external_conversation_id
    message_doc.conversation = conversation_name
    message_doc.response_payload = _json_dumps(response)
    message_doc.sent_at = now_datetime()
    message_doc.save(ignore_permissions=True)
    frappe.db.commit()

    result = {
        "ok": True,
        "message": message_doc.name,
        "message_id": external_message_id,
        "conversation": conversation_name,
        "conversation_id": external_conversation_id,
    }
    status = _first_value(response, "status", "state")
    message_status = _first_value(response, "message_status", "messageStatus")
    if status not in (None, ""):
        result["status"] = cstr(status)
    if message_status not in (None, ""):
        result["message_status"] = cstr(message_status)
    return result


@frappe.whitelist()
def maqsam_whatsapp_get_conversation(conversation_id: str) -> dict[str, Any]:
    _ensure_whatsapp_enabled()
    conversation_id = cstr(conversation_id).strip()
    if not conversation_id:
        frappe.throw("Conversation ID is required.", frappe.ValidationError)

    existing_name = _enforce_conversation_access(conversation_id)
    payload = get_client().get_conversation(conversation_id)
    local_name = existing_name or _upsert_conversation(
        conversation_id=conversation_id,
        payload=payload,
        sent_by_user=frappe.session.user if is_maqsam_agent() else None,
    )
    if existing_name:
        doc = frappe.get_doc("Maqsam WhatsApp Conversation", existing_name)
        doc.raw_payload = _json_dumps(payload)
        status = _first_value(payload, "status", "state")
        if status:
            doc.status = cstr(status)[:40]
        doc.last_message_at = now_datetime()
        doc.save(ignore_permissions=True)
    frappe.db.commit()
    return _conversation_projection(local_name, conversation_id, payload)


@frappe.whitelist()
def maqsam_whatsapp_get_defaults(doctype: str, docname: str) -> dict[str, Any]:
    _ensure_whatsapp_enabled()

    doctype = cstr(doctype).strip()
    docname = cstr(docname).strip()

    if not doctype or not docname:
        frappe.throw("DocType and DocName are required.", frappe.ValidationError)

    _enforce_agent_reference_allowlist(doctype)

    if not frappe.has_permission(doctype, "read", docname):
        frappe.throw(f"No permission to read {doctype} {docname}", frappe.PermissionError)

    doc = frappe.get_doc(doctype, docname)
    variable_defaults: dict[str, Any] = {}

    candidates = _get_reference_phone_candidates(doctype, docname)

    if doctype == "Patient Appointment":
        variable_defaults["patient_name"] = cstr(doc.get("patient_name") or "")
        variable_defaults["appointment_date"] = cstr(doc.get("appointment_date") or "")
        variable_defaults["appointment_time"] = cstr(doc.get("appointment_time") or "")

        if not candidates and doc.get("patient"):
            try:
                if frappe.has_permission("Patient", "read", doc.patient):
                    candidates = _get_reference_phone_candidates("Patient", doc.patient)
                    if not variable_defaults["patient_name"]:
                        patient = frappe.get_doc("Patient", doc.patient)
                        variable_defaults["patient_name"] = cstr(patient.get("patient_name") or "")
            except Exception:
                pass

    elif doctype == "Lead":
        variable_defaults["lead_name"] = cstr(doc.get("lead_name") or "")
        variable_defaults["company"] = cstr(doc.get("company_name") or "")
    elif doctype == "Patient":
        variable_defaults["patient_name"] = cstr(doc.get("patient_name") or "")
    elif doctype in ("Customer", "Contact"):
        variable_defaults["name"] = cstr(doc.get("customer_name") or doc.get("first_name") or getattr(doc, "name", ""))

    client = get_client()
    country_code = get_default_whatsapp_country_code()
    normalized_candidates: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        if not candidate:
            continue
        try:
            val = validate_whatsapp_phone(
                candidate,
                base_client=getattr(client, "base_client", None),
                default_country_code=country_code,
            )
            if val and val not in seen:
                seen.add(val)
                normalized_candidates.append(val)
        except Exception:
            pass

    clean_variables = {k: v for k, v in variable_defaults.items() if v}

    return {
        "phone_candidates": normalized_candidates,
        "suggested_templates": _get_suggested_templates(),
        "variable_defaults": clean_variables,
    }
