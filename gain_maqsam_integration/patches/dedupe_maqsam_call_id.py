from __future__ import annotations

import frappe


def execute() -> None:
    """Drop duplicate Maqsam Call Log rows that share a maqsam_call_id and
    enforce a UNIQUE index on the column.

    Frappe's DocType sync upgrades a non-unique index to UNIQUE only when the
    column has no duplicates, so we deduplicate first and add the constraint
    explicitly to make the intent durable across sites.
    """
    if not frappe.db.table_exists("Maqsam Call Log"):
        return

    duplicates = frappe.db.sql(
        """
        SELECT maqsam_call_id
        FROM `tabMaqsam Call Log`
        WHERE maqsam_call_id IS NOT NULL AND maqsam_call_id != ''
        GROUP BY maqsam_call_id
        HAVING COUNT(*) > 1
        """,
        as_dict=True,
    )

    for row in duplicates:
        rows = frappe.get_all(
            "Maqsam Call Log",
            filters={"maqsam_call_id": row.maqsam_call_id},
            fields=["name"],
            order_by="creation asc",
        )
        for stale in rows[1:]:
            frappe.db.delete("Maqsam Call Log", stale.name)

    indexes = frappe.db.sql(
        "SHOW INDEXES FROM `tabMaqsam Call Log` WHERE Column_name = 'maqsam_call_id'",
        as_dict=True,
    )
    is_unique = any(idx.get("Non_unique") == 0 for idx in indexes)
    if not is_unique:
        for idx in indexes:
            frappe.db.sql_ddl(
                f"ALTER TABLE `tabMaqsam Call Log` DROP INDEX `{idx['Key_name']}`"
            )
        frappe.db.sql_ddl(
            "ALTER TABLE `tabMaqsam Call Log` "
            "ADD UNIQUE INDEX `maqsam_call_id` (`maqsam_call_id`)"
        )

    frappe.db.commit()
