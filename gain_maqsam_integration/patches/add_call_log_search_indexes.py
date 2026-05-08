"""Add search indexes on Maqsam Call Log columns that are queried hot.

Frappe's DocType sync only adds an index when the column is created. For
existing installs the column is already there, so toggling `search_index: 1`
in the JSON does not retroactively create the index — we have to do it
explicitly here.

Indexed columns:
- `caller_number`, `callee_number`: filtered via LIKE %suffix% by Caller 360
  and the missed-calls / top-callers / hourly-heatmap reports.
- `linked_docname`: looked up by the Communication section that's injected
  into Patient/Customer/Lead/Contact dashboards (one query per page open).
- `normalized_phone`: filtered via LIKE in `get_recent_calls`.
- `timestamp`: every report filters by date range, the daily cleanup jobs
  filter by it, and the list view sorts by it.

Idempotent: each index is only created if it doesn't already exist, so
re-running the patch (e.g. after a failed migrate) is safe.
"""

from __future__ import annotations

import frappe


INDEX_COLUMNS = (
    "caller_number",
    "callee_number",
    "linked_docname",
    "normalized_phone",
    "timestamp",
)


def execute() -> None:
    if not frappe.db.table_exists("Maqsam Call Log"):
        return

    for column in INDEX_COLUMNS:
        if not _column_exists(column):
            # Column hasn't been synced yet (very fresh install) — skip;
            # Frappe's DocType sync will create it with the index thanks to
            # the `search_index: 1` flag in the JSON.
            continue
        if _index_exists(column):
            continue
        try:
            # `key_length=191` is safe across utf8mb4 (max key prefix in
            # MariaDB without innodb_large_prefix); Frappe uses the same
            # value for its own search indexes.
            frappe.db.add_index("Maqsam Call Log", [column])
        except Exception as e:
            raise Exception(
                f"Failed to add index on column {column!r}. "
                f"Run manually:\n"
                f"ALTER TABLE `tabMaqsam Call Log` "
                f"ADD INDEX `{column}` (`{column}`);\n\n"
                f"{frappe.get_traceback()}"
            ) from e

    frappe.db.commit()


def _column_exists(column: str) -> bool:
    rows = frappe.db.sql(
        "SHOW COLUMNS FROM `tabMaqsam Call Log` LIKE %s",
        (column,),
    )
    return bool(rows)


def _index_exists(column: str) -> bool:
    rows = frappe.db.sql(
        "SHOW INDEXES FROM `tabMaqsam Call Log` WHERE Column_name = %s",
        (column,),
        as_dict=True,
    )
    return bool(rows)
