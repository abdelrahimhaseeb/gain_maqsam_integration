from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt, now_datetime

from gain_maqsam_integration.permissions import can_read_document


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


def get_related_patients_and_customers(matches: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    patients = {
        match["name"]
        for match in matches
        if match["doctype"] == "Patient" and can_read_document("Patient", match["name"])
    }
    customers = {
        match["name"]
        for match in matches
        if match["doctype"] == "Customer" and can_read_document("Customer", match["name"])
    }

    if patients:
        rows = frappe.get_all(
            "Patient",
            filters={"name": ["in", list(patients)]},
            fields=["name", "customer"],
            ignore_permissions=True,
        )
        for row in rows:
            if row.customer and can_read_document("Customer", row.customer):
                customers.add(row.customer)

    return patients, customers


def get_invoice_summary(matches: list[dict[str, Any]]) -> dict[str, Any]:
    patients, customers = get_related_patients_and_customers(matches)
    if not patients and not customers or not frappe.db.exists("DocType", "Sales Invoice"):
        return {"total_outstanding": 0, "unpaid_count": 0, "unpaid": [], "recent": []}

    invoice_meta = frappe.get_meta("Sales Invoice")
    invoice_fields = [
        "name",
        "docstatus",
        *[
            field
            for field in INVOICE_FIELDS
            if field not in {"name", "docstatus"} and invoice_meta.has_field(field)
        ],
    ]

    or_filters: list[list[Any]] = []
    if customers and invoice_meta.has_field("customer"):
        or_filters.append(["customer", "in", list(customers)])
    if patients and invoice_meta.has_field("patient"):
        or_filters.append(["patient", "in", list(patients)])

    if not or_filters:
        return {"total_outstanding": 0, "unpaid_count": 0, "unpaid": [], "recent": []}

    rows = frappe.get_all(
        "Sales Invoice",
        fields=invoice_fields,
        filters={"docstatus": ["!=", 2]},
        or_filters=or_filters,
        order_by="posting_date desc, creation desc",
        limit=100,
        ignore_permissions=True,
    )
    related: list[dict[str, Any]] = []
    for row in rows:
        if not can_read_document("Sales Invoice", row.name):
            continue
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
