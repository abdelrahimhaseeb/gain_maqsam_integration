"""Shared helper that injects a "Communication / Maqsam Calls" section
into the dashboard of any linked record (Patient, Customer, Lead, Contact).

Maqsam Call Log uses a Dynamic Link (linked_doctype + linked_docname) to point
back at the originating record, so we tell Frappe's dashboard widget to filter
by `linked_docname` via `non_standard_fieldnames`.
"""

from __future__ import annotations

from typing import Any

from frappe import _


SECTION_LABEL = "Communication"
ITEM_DOCTYPE = "Maqsam Call Log"
LINK_FIELDNAME = "linked_docname"


def add_maqsam_calls_section(data: dict[str, Any]) -> dict[str, Any]:
    data = data or {}
    transactions = data.setdefault("transactions", [])

    existing = next(
        (block for block in transactions if block.get("label") == _(SECTION_LABEL)),
        None,
    )
    if existing is None:
        transactions.append({"label": _(SECTION_LABEL), "items": [ITEM_DOCTYPE]})
    else:
        items = existing.setdefault("items", [])
        if ITEM_DOCTYPE not in items:
            items.append(ITEM_DOCTYPE)

    non_standard = data.setdefault("non_standard_fieldnames", {})
    non_standard.setdefault(ITEM_DOCTYPE, LINK_FIELDNAME)

    return data
