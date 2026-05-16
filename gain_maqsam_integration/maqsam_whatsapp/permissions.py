from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cstr

from gain_maqsam_integration.permissions import (
    can_read_document,
    get_user_agent_identifiers,
    is_maqsam_agent,
    is_maqsam_superuser,
)


READ_ONLY_PERMISSION_TYPES = {"read", "select", "report", "print", "email"}


def _normalize(value: Any) -> str:
    return cstr(value).strip().lower()


def _value_from_doc(doc: Any, fieldname: str) -> str:
    if hasattr(doc, "get"):
        return cstr(doc.get(fieldname))
    return cstr(getattr(doc, fieldname, ""))


def _is_own_whatsapp_record(doc: Any, user: str) -> bool:
    identifiers = get_user_agent_identifiers(user)
    sent_by_user = _normalize(_value_from_doc(doc, "sent_by_user"))
    owner = _normalize(_value_from_doc(doc, "owner"))
    return bool((sent_by_user and sent_by_user in identifiers) or (owner and owner in identifiers))


def _has_readable_reference(doc: Any, user: str) -> bool:
    reference_doctype = _value_from_doc(doc, "reference_doctype")
    reference_name = _value_from_doc(doc, "reference_name")
    if not reference_doctype or not reference_name:
        return False
    return can_read_document(reference_doctype, reference_name, user=user)


def can_access_whatsapp_record(doc: Any, user: str | None = None, permission_type: str | None = None) -> bool:
    user = user or frappe.session.user
    if user == "Guest":
        return False
    if is_maqsam_superuser(user):
        return True
    if not is_maqsam_agent(user):
        return False

    ptype = _normalize(permission_type or "read")
    if ptype not in READ_ONLY_PERMISSION_TYPES:
        return False

    return _is_own_whatsapp_record(doc, user) or _has_readable_reference(doc, user)


def _reference_accessible_names(doctype: str, user: str) -> list[str]:
    """Return names of *doctype* records whose linked reference is readable by *user*.

    This bridges the gap between the SQL query-condition (which can only check
    ownership) and the object-level permission check (which also allows a record
    when the referenced document is readable). We fetch at most 500 names so the
    resulting IN-clause stays within reasonable SQL limits, which is safe in
    practice because agents typically have far fewer records than that.
    """
    rows = frappe.get_all(
        doctype,
        fields=["name", "reference_doctype", "reference_name"],
        filters={"reference_doctype": ["is", "set"], "reference_name": ["is", "set"]},
        limit=500,
        ignore_permissions=True,
    )
    accessible: list[str] = []
    for row in rows:
        ref_dt = cstr(row.get("reference_doctype")).strip()
        ref_name = cstr(row.get("reference_name")).strip()
        if ref_dt and ref_name and can_read_document(ref_dt, ref_name, user=user):
            accessible.append(row.name)
    return accessible


def _user_condition(doctype: str, user: str | None = None) -> str:
    user = user or frappe.session.user
    if is_maqsam_superuser(user):
        return ""
    if not is_maqsam_agent(user):
        return "1=0"

    identifiers = sorted(get_user_agent_identifiers(user))
    if not identifiers:
        return "1=0"

    escaped = ", ".join(frappe.db.escape(identifier) for identifier in identifiers)
    table = f"`tab{doctype}`"
    ownership_clause = (
        f"(LOWER(COALESCE({table}.`sent_by_user`, '')) IN ({escaped})"
        f" OR LOWER(COALESCE({table}.`owner`, '')) IN ({escaped}))"
    )

    # Also include records that are readable because their linked reference
    # document is accessible to this user (mirrors _has_readable_reference).
    ref_names = _reference_accessible_names(doctype, user)
    if not ref_names:
        return ownership_clause

    escaped_names = ", ".join(frappe.db.escape(n) for n in ref_names)
    return f"({ownership_clause} OR {table}.`name` IN ({escaped_names}))"


def whatsapp_conversation_query_conditions(user: str | None = None) -> str:
    return _user_condition("Maqsam WhatsApp Conversation", user=user)


def whatsapp_message_query_conditions(user: str | None = None) -> str:
    return _user_condition("Maqsam WhatsApp Message", user=user)


def has_whatsapp_conversation_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
    return can_access_whatsapp_record(doc, user=user, permission_type=permission_type)


def has_whatsapp_message_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
    return can_access_whatsapp_record(doc, user=user, permission_type=permission_type)
