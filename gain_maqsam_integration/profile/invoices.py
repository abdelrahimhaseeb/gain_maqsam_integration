from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt, now_datetime


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
    patients = {match["name"] for match in matches if match["doctype"] == "Patient"}
    customers = {match["name"] for match in matches if match["doctype"] == "Customer"}
    for patient in list(patients):
        customer = frappe.db.get_value("Patient", patient, "customer")
        if customer:
            customers.add(customer)
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
    rows = frappe.get_all(
        "Sales Invoice",
        fields=invoice_fields,
        filters={"docstatus": ["!=", 2]},
        order_by="posting_date desc, creation desc",
        limit_page_length=500,
        ignore_permissions=True,
    )
    related: list[dict[str, Any]] = []
    for row in rows:
        if (row.get("patient") and row.get("patient") in patients) or (
            row.get("customer") and row.get("customer") in customers
        ):
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
