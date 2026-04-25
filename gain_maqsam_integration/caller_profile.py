from __future__ import annotations

import re
from typing import Any

import frappe
from frappe.utils import cint, flt, format_datetime, get_datetime, now_datetime


MATCH_PRIORITY = {"Patient": 10, "Customer": 20, "Lead": 30, "Contact": 40}
PHONE_LINK_FIELDS = {
    "Patient": ("mobile", "phone"),
    "Customer": ("mobile_no", "phone", "default_phone"),
    "Lead": ("mobile_no", "phone", "whatsapp_no"),
    "Contact": ("mobile_no", "phone"),
}
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
INVOICE_FIELDS = [
    "name",
    "customer",
    "customer_name",
    "patient",
    "patient_name",
    "posting_date",
    "due_date",
    "grand_total",
    "outstanding_amount",
    "status",
    "docstatus",
]


def digits_only(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def phone_matches(left: Any, right: Any) -> bool:
    left_digits = digits_only(left)
    right_digits = digits_only(right)
    if not left_digits or not right_digits:
        return False

    if left_digits == right_digits:
        return True

    suffix_length = min(9, len(left_digits), len(right_digits))
    return suffix_length >= 7 and left_digits[-suffix_length:] == right_digits[-suffix_length:]


def phone_matches_any(value: Any, candidates: list[Any]) -> bool:
    return any(phone_matches(value, candidate) for candidate in candidates)


def get_customer_facing_number(call_log) -> str:
    direction = str(call_log.get("direction") or "").lower()
    if direction == "inbound":
        return call_log.get("caller_number") or call_log.get("normalized_phone") or ""
    if direction == "outbound":
        return call_log.get("callee_number") or call_log.get("normalized_phone") or ""
    return call_log.get("normalized_phone") or call_log.get("caller_number") or call_log.get("callee_number") or ""


def resolve_lookup_phone(phone: str | None = None, call_log: str | None = None, maqsam_call_id: str | None = None) -> str:
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


def _match_standard_doctype(doctype: str, lookup_numbers: list[str], matches: list[dict[str, Any]], seen: set[tuple[str, str]]) -> None:
    if not frappe.db.exists("DocType", doctype):
        return

    meta = frappe.get_meta(doctype)
    available_fields = [field for field in PHONE_LINK_FIELDS.get(doctype, ()) if meta.has_field(field)]
    if not available_fields:
        return

    extra_fields = []
    for field in ("patient_name", "customer_name", "lead_name", "first_name", "status", "customer"):
        if meta.has_field(field):
            extra_fields.append(field)

    records = frappe.get_all(
        doctype,
        fields=["name", *available_fields, *extra_fields],
        limit_page_length=1000,
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


def _match_contact_child_numbers(lookup_numbers: list[str], matches: list[dict[str, Any]], seen: set[tuple[str, str]]) -> None:
    if not frappe.db.exists("DocType", "Contact Phone"):
        return

    rows = frappe.get_all(
        "Contact Phone",
        fields=["parent", "phone"],
        filters={"parenttype": "Contact"},
        limit_page_length=1000,
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
    lookup_numbers = [phone, digits_only(phone)]
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for doctype in ("Patient", "Customer", "Lead", "Contact"):
        _match_standard_doctype(doctype, lookup_numbers, matches, seen)

    _match_contact_child_numbers(lookup_numbers, matches, seen)
    _append_customers_from_contacts(matches, seen)
    return sorted(matches, key=lambda item: (item.get("priority", 99), item.get("title") or item.get("name")))


def get_recent_calls(phone: str, limit: int = 10) -> list[dict[str, Any]]:
    lookup_numbers = [phone, digits_only(phone)]
    rows = frappe.get_all(
        "Maqsam Call Log",
        fields=CALL_LOG_FIELDS,
        order_by="timestamp desc, creation desc",
        limit_page_length=300,
        ignore_permissions=True,
    )
    calls = []
    for row in rows:
        if not any(
            phone_matches_any(row.get(field), lookup_numbers)
            for field in ("caller_number", "callee_number", "normalized_phone")
        ):
            continue

        row = dict(row)
        row["timestamp_display"] = format_datetime(row.get("timestamp")) if row.get("timestamp") else ""
        calls.append(row)
        if len(calls) >= limit:
            break

    return calls


def _get_related_patients_and_customers(matches: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    patients = {match["name"] for match in matches if match["doctype"] == "Patient"}
    customers = {match["name"] for match in matches if match["doctype"] == "Customer"}
    for patient in list(patients):
        customer = frappe.db.get_value("Patient", patient, "customer")
        if customer:
            customers.add(customer)

    return patients, customers


def get_invoice_summary(matches: list[dict[str, Any]]) -> dict[str, Any]:
    patients, customers = _get_related_patients_and_customers(matches)
    if not patients and not customers or not frappe.db.exists("DocType", "Sales Invoice"):
        return {"total_outstanding": 0, "unpaid_count": 0, "unpaid": [], "recent": []}

    invoice_meta = frappe.get_meta("Sales Invoice")
    invoice_fields = ["name", "docstatus", *[field for field in INVOICE_FIELDS if field not in {"name", "docstatus"} and invoice_meta.has_field(field)]]
    rows = frappe.get_all(
        "Sales Invoice",
        fields=invoice_fields,
        filters={"docstatus": ["!=", 2]},
        order_by="posting_date desc, creation desc",
        limit_page_length=500,
        ignore_permissions=True,
    )
    related = []
    for row in rows:
        if (row.get("patient") and row.get("patient") in patients) or (row.get("customer") and row.get("customer") in customers):
            item = dict(row)
            item["grand_total"] = flt(item.get("grand_total"))
            item["outstanding_amount"] = flt(item.get("outstanding_amount"))
            related.append(item)

    unpaid = [row for row in related if flt(row.get("outstanding_amount")) > 0]
    unpaid.sort(key=lambda row: (row.get("due_date") or row.get("posting_date") or now_datetime().date()))
    recent = related[:10]
    return {
        "total_outstanding": sum(flt(row.get("outstanding_amount")) for row in unpaid),
        "unpaid_count": len(unpaid),
        "unpaid": unpaid[:10],
        "recent": recent,
    }


def get_appointments(matches: list[dict[str, Any]]) -> dict[str, Any]:
    patients, _customers = _get_related_patients_and_customers(matches)
    if not patients or not frappe.db.exists("DocType", "Patient Appointment"):
        return {"upcoming": [], "recent": []}

    appointment_meta = frappe.get_meta("Patient Appointment")
    appointment_fields = [
        "name",
        *[
            field
            for field in (
                "patient",
                "patient_name",
                "status",
                "appointment_date",
                "appointment_time",
                "appointment_datetime",
                "practitioner",
                "department",
                "ref_sales_invoice",
            )
            if appointment_meta.has_field(field)
        ],
    ]
    rows = frappe.get_all(
        "Patient Appointment",
        fields=appointment_fields,
        filters={"patient": ["in", list(patients)], "docstatus": ["!=", 2]},
        order_by="appointment_datetime desc, appointment_date desc, creation desc",
        limit_page_length=100,
        ignore_permissions=True,
    )
    now = now_datetime()
    upcoming = []
    recent = []
    for row in rows:
        item = dict(row)
        when = item.get("appointment_datetime")
        if not when and item.get("appointment_date"):
            when = get_datetime(item.get("appointment_date"))
        item["appointment_display"] = format_datetime(when) if when else ""
        if when and get_datetime(when) >= now:
            upcoming.append(item)
        else:
            recent.append(item)

    upcoming.sort(key=lambda row: get_datetime(row.get("appointment_datetime") or row.get("appointment_date") or now))
    return {"upcoming": upcoming[:5], "recent": recent[:5]}


def build_profile_summary(phone: str, matches: list[dict[str, Any]], recent_calls: list[dict[str, Any]]) -> dict[str, Any]:
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


def get_caller_profile(phone: str | None = None, call_log: str | None = None, maqsam_call_id: str | None = None) -> dict[str, Any]:
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
