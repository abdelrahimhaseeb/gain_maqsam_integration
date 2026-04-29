from __future__ import annotations

from typing import Any

import frappe
from frappe import _


# MySQL DAYOFWEEK: 1=Sunday ... 7=Saturday
DAY_NAMES = {
    1: _("Sunday"),
    2: _("Monday"),
    3: _("Tuesday"),
    4: _("Wednesday"),
    5: _("Thursday"),
    6: _("Friday"),
    7: _("Saturday"),
}


def execute(filters: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], None, dict[str, Any]]:
    filters = filters or {}
    days = int(filters.get("days") or 30)
    since = frappe.utils.add_days(frappe.utils.now_datetime(), -days)

    rows = frappe.db.sql(
        """
        SELECT DAYOFWEEK(timestamp) AS dow, HOUR(timestamp) AS hour, COUNT(*) AS calls
        FROM `tabMaqsam Call Log`
        WHERE timestamp >= %(since)s
        GROUP BY DAYOFWEEK(timestamp), HOUR(timestamp)
        """,
        {"since": since},
        as_dict=True,
    )

    grid: dict[int, dict[int, int]] = {dow: {hour: 0 for hour in range(24)} for dow in range(1, 8)}
    for row in rows:
        grid[int(row.dow)][int(row.hour)] = int(row.calls)

    columns = [{"label": _("Day"), "fieldname": "day", "fieldtype": "Data", "width": 120}]
    for hour in range(24):
        columns.append({
            "label": f"{hour:02d}",
            "fieldname": f"h{hour:02d}",
            "fieldtype": "Int",
            "width": 60,
        })
    columns.append({"label": _("Total"), "fieldname": "total", "fieldtype": "Int", "width": 90})

    data: list[dict[str, Any]] = []
    hour_totals = [0] * 24
    for dow in (1, 2, 3, 4, 5, 6, 7):
        row: dict[str, Any] = {"day": str(DAY_NAMES[dow])}
        total = 0
        for hour in range(24):
            value = grid[dow][hour]
            row[f"h{hour:02d}"] = value
            total += value
            hour_totals[hour] += value
        row["total"] = total
        data.append(row)

    chart = {
        "data": {
            "labels": [f"{hour:02d}" for hour in range(24)],
            "datasets": [{"name": _("Calls"), "values": hour_totals}],
        },
        "type": "bar",
        "colors": ["#0f766e"],
        "axisOptions": {"shortenYAxisNumbers": 1},
    }

    return columns, data, None, chart
