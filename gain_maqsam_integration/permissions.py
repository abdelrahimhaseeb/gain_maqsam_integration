from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cstr


MAQSAM_AGENT_ROLE = "Maqsam Agent"
MAQSAM_SUPERVISOR_ROLE = "Maqsam Supervisor"


def get_user_roles(user: str | None = None) -> set[str]:
    return set(frappe.get_roles(user or frappe.session.user) or [])


def user_has_role(role: str, user: str | None = None) -> bool:
    return role in get_user_roles(user)


def is_maqsam_superuser(user: str | None = None) -> bool:
    return user_has_role("System Manager", user) or user_has_role(MAQSAM_SUPERVISOR_ROLE, user)


def is_maqsam_agent(user: str | None = None) -> bool:
    return user_has_role(MAQSAM_AGENT_ROLE, user)


def is_maqsam_user(user: str | None = None) -> bool:
    return is_maqsam_superuser(user) or is_maqsam_agent(user)


def only_maqsam_user() -> None:
    if frappe.session.user == "Guest":
        frappe.throw("Login required", frappe.PermissionError)
    if not is_maqsam_user():
        frappe.throw("Only Maqsam users can access Maqsam data.", frappe.PermissionError)


def _normalize_identifier(value: Any) -> str:
    return cstr(value).strip().lower()


def get_user_agent_identifiers(user: str | None = None) -> set[str]:
    user = user or frappe.session.user
    identifiers = {_normalize_identifier(user)}

    try:
        email = frappe.db.get_value("User", user, "email")
    except Exception:
        email = None

    if email:
        identifiers.add(_normalize_identifier(email))

    return {value for value in identifiers if value and value != "guest"}


def _get_call_log_agent_identifier(doc_or_name: Any) -> str:
    if not doc_or_name:
        return ""
    if isinstance(doc_or_name, str):
        return _normalize_identifier(frappe.db.get_value("Maqsam Call Log", doc_or_name, "agent_email"))
    return _normalize_identifier(doc_or_name.get("agent_email"))


def is_own_call_log(doc_or_name: Any, user: str | None = None) -> bool:
    agent_identifier = _get_call_log_agent_identifier(doc_or_name)
    if not agent_identifier:
        return False
    return agent_identifier in get_user_agent_identifiers(user)


def can_access_call_log(doc_or_name: Any, ptype: str = "read", user: str | None = None) -> bool:
    user = user or frappe.session.user
    if user == "Guest":
        return False
    if is_maqsam_superuser(user):
        return True
    if not is_maqsam_agent(user):
        return False

    ptype = cstr(ptype or "read").lower()
    if ptype in {"delete", "share", "export", "import"}:
        return False

    return is_own_call_log(doc_or_name, user)


def enforce_call_log_access(call_log: str, ptype: str = "read"):
    only_maqsam_user()
    doc = frappe.get_doc("Maqsam Call Log", call_log)
    if not can_access_call_log(doc, ptype=ptype):
        frappe.throw("You can only access Maqsam call logs assigned to your agent.", frappe.PermissionError)

    ptype = cstr(ptype or "read").lower()
    if ptype == "write" and is_maqsam_agent() and not is_maqsam_superuser():
        # Agents have no generic DocType write permission. Existing whitelisted
        # methods call this helper first, then save with ignore_permissions=True
        # for the specific business fields they are allowed to update.
        return doc

    doc.check_permission(ptype)
    return doc


def has_call_log_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
    ptype = cstr(permission_type or "read").lower()
    user = user or frappe.session.user
    if ptype == "write" and is_maqsam_agent(user) and not is_maqsam_superuser(user):
        return False
    return can_access_call_log(doc, ptype=ptype, user=user)


def call_log_query_conditions(user: str | None = None) -> str:
    user = user or frappe.session.user
    if is_maqsam_superuser(user):
        return ""
    if not is_maqsam_agent(user):
        return "1=0"

    identifiers = sorted(get_user_agent_identifiers(user))
    if not identifiers:
        return "1=0"

    escaped = ", ".join(frappe.db.escape(identifier) for identifier in identifiers)
    return f"LOWER(COALESCE(`tabMaqsam Call Log`.`agent_email`, '')) IN ({escaped})"


def get_call_log_report_scope(table_expr: str = "`tabMaqsam Call Log`", user: str | None = None) -> tuple[str, dict[str, Any]]:
    user = user or frappe.session.user
    if is_maqsam_superuser(user):
        return "", {}
    if not is_maqsam_agent(user):
        frappe.throw("Only Maqsam users can access Maqsam reports.", frappe.PermissionError)

    identifiers = sorted(get_user_agent_identifiers(user))
    if not identifiers:
        frappe.throw("Cannot safely scope Maqsam report rows for this user.", frappe.PermissionError)

    return (
        f"LOWER(COALESCE({table_expr}.agent_email, '')) IN %(maqsam_agent_emails)s",
        {"maqsam_agent_emails": tuple(identifiers)},
    )


def can_read_document(doctype: str, name: str, user: str | None = None) -> bool:
    if not doctype or not name:
        return False
    try:
        doc = frappe.get_doc(doctype, name)
        return bool(frappe.has_permission(doctype, "read", doc=doc, user=user or frappe.session.user))
    except Exception:
        return False



def prevent_agent_direct_call_log_write(doc, method: str | None = None) -> None:
    if getattr(doc.flags, "ignore_permissions", False):
        return
    user = frappe.session.user
    if is_maqsam_agent(user) and not is_maqsam_superuser(user):
        frappe.throw(
            "Maqsam Agents must update call logs through Maqsam whitelisted actions.",
            frappe.PermissionError,
        )
