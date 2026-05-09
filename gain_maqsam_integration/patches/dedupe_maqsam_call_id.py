from __future__ import annotations

import frappe


def execute() -> None:
    """Fail safely on duplicate Maqsam IDs and enforce a unique index.

    Duplicate call logs can carry independent recordings, notes, links, and raw
    payloads. The patch intentionally refuses to choose a winner during migrate;
    an operator must resolve duplicates explicitly before the unique constraint is
    added.
    """
    if not frappe.db.table_exists("Maqsam Call Log"):
        return

    frappe.db.sql(
        """
        UPDATE `tabMaqsam Call Log`
        SET maqsam_call_id = NULL
        WHERE maqsam_call_id = ''
        """
    )

    duplicates = frappe.db.sql(
        """
        SELECT
            maqsam_call_id,
            COUNT(*) AS duplicate_count,
            GROUP_CONCAT(name ORDER BY creation ASC SEPARATOR ', ') AS call_logs
        FROM `tabMaqsam Call Log`
        WHERE maqsam_call_id IS NOT NULL AND maqsam_call_id != ''
        GROUP BY maqsam_call_id
        HAVING COUNT(*) > 1
        ORDER BY duplicate_count DESC, maqsam_call_id ASC
        LIMIT 10
        """,
        as_dict=True,
    )
    if duplicates:
        details = "\n".join(
            f"- {row.maqsam_call_id}: {row.duplicate_count} rows ({row.call_logs})"
            for row in duplicates
        )
        raise Exception(
            "Cannot add the Maqsam Call ID unique index while duplicate call logs exist. "
            "Resolve or merge these records manually, preserving recordings, notes, links, "
            f"and raw payloads, then rerun migrate. Duplicates found:\n{details}"
        )

    indexes = frappe.db.sql(
        "SHOW INDEXES FROM `tabMaqsam Call Log` WHERE Column_name = 'maqsam_call_id'",
        as_dict=True,
    )
    if any(idx.get("Non_unique") == 0 for idx in indexes):
        frappe.db.commit()
        return

    for idx in indexes:
        if idx.get("Key_name") == "maqsam_call_id":
            frappe.db.sql_ddl("ALTER TABLE `tabMaqsam Call Log` DROP INDEX `maqsam_call_id`")
            break

    frappe.db.sql_ddl(
        "ALTER TABLE `tabMaqsam Call Log` "
        "ADD UNIQUE INDEX `maqsam_call_id` (`maqsam_call_id`)"
    )
    frappe.db.commit()
