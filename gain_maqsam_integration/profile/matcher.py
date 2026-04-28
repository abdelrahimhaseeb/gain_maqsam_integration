from __future__ import annotations

from typing import Any

import frappe

from gain_maqsam_integration.profile.phone import phone_matches_any, phone_suffix


MATCH_PRIORITY = {"Patient": 10, "Customer": 20, "Lead": 30, "Contact": 40}
PHONE_LINK_FIELDS = {
    "Patient": ("mobile", "phone"),
    "Customer": ("mobile_no", "phone", "default_phone"),
    "Lead": ("mobile_no", "phone", "whatsapp_no"),
    "Contact": ("mobile_no", "phone"),
}


def _safe_get_title(doctype: str, name: str) -> str:
    try:
        doc = frappe.get_doc(doctype, name)
        if hasattr(doc, "check_permission"):
            doc.check_permission("read")
        return doc.get_title() or name
    except Exception:
        return name


def _append_match(
    matches: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    *,
    doctype: str,
    name: str,
    title: str | None = None,
    matched_phone: str | None = None,
    status: str | None = None,
    customer: str | None = None,
    source: str | None = None,
) -> None:
    key = (doctype, name)
    if key in seen:
        return

    seen.add(key)
    matches.append(
        {
            "doctype": doctype,
            "name": name,
            "title": title or _safe_get_title(doctype, name),
            "matched_phone": matched_phone or "",
            "status": status or "",
            "customer": customer or "",
            "source": source or "Direct Phone",
            "priority": MATCH_PRIORITY.get(doctype, 99),
        }
    )


def _match_standard_doctype(
    doctype: str,
    lookup_numbers: list[str],
    matches: list[dict[str, Any]],
    seen: set[tuple[str, str]],
) -> None:
    if not frappe.db.exists("DocType", doctype):
        return

    meta = frappe.get_meta(doctype)
    available_fields = [field for field in PHONE_LINK_FIELDS.get(doctype, ()) if meta.has_field(field)]
    if not available_fields:
        return

    suffix = phone_suffix(lookup_numbers[0] if lookup_numbers else "")
    if not suffix:
        return

    extra_fields = [
        field
        for field in ("patient_name", "customer_name", "lead_name", "first_name", "status", "customer")
        if meta.has_field(field)
    ]

    or_filters = [[field, "like", f"%{suffix}%"] for field in available_fields]
    records = frappe.get_all(
        doctype,
        fields=["name", *available_fields, *extra_fields],
        or_filters=or_filters,
        limit_page_length=50,
        ignore_permissions=True,
    )
    for record in records:
        for field in available_fields:
            value = record.get(field)
            if phone_matches_any(value, lookup_numbers):
                title = (
                    record.get("patient_name")
                    or record.get("customer_name")
                    or record.get("lead_name")
                    or record.get("first_name")
                    or _safe_get_title(doctype, record.name)
                )
                _append_match(
                    matches,
                    seen,
                    doctype=doctype,
                    name=record.name,
                    title=title,
                    matched_phone=value,
                    status=record.get("status"),
                    customer=record.get("customer"),
                )
                break


def _match_contact_child_numbers(
    lookup_numbers: list[str],
    matches: list[dict[str, Any]],
    seen: set[tuple[str, str]],
) -> None:
    if not frappe.db.exists("DocType", "Contact Phone"):
        return

    suffix = phone_suffix(lookup_numbers[0] if lookup_numbers else "")
    if not suffix:
        return

    rows = frappe.get_all(
        "Contact Phone",
        fields=["parent", "phone"],
        filters={"parenttype": "Contact", "phone": ["like", f"%{suffix}%"]},
        limit_page_length=50,
        ignore_permissions=True,
    )
    for row in rows:
        if phone_matches_any(row.phone, lookup_numbers):
            _append_match(
                matches,
                seen,
                doctype="Contact",
                name=row.parent,
                matched_phone=row.phone,
                source="Contact Numbers",
            )


def _append_customers_from_contacts(matches: list[dict[str, Any]], seen: set[tuple[str, str]]) -> None:
    contact_names = [match["name"] for match in matches if match["doctype"] == "Contact"]
    if not contact_names:
        return

    links = frappe.get_all(
        "Dynamic Link",
        fields=["parent", "link_name"],
        filters={"parenttype": "Contact", "parent": ["in", contact_names], "link_doctype": "Customer"},
        limit_page_length=500,
        ignore_permissions=True,
    )
    for link in links:
        if frappe.db.exists("Customer", link.link_name):
            _append_match(
                matches,
                seen,
                doctype="Customer",
                name=link.link_name,
                source=f"Linked Contact {link.parent}",
            )


def find_matches(phone: str) -> list[dict[str, Any]]:
    from gain_maqsam_integration.profile.phone import digits_only

    lookup_numbers = [phone, digits_only(phone)]
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for doctype in ("Patient", "Customer", "Lead", "Contact"):
        _match_standard_doctype(doctype, lookup_numbers, matches, seen)

    _match_contact_child_numbers(lookup_numbers, matches, seen)
    _append_customers_from_contacts(matches, seen)
    return sorted(matches, key=lambda item: (item.get("priority", 99), item.get("title") or item.get("name")))
