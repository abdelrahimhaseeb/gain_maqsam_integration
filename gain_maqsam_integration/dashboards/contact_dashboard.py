from __future__ import annotations

from typing import Any

from gain_maqsam_integration.dashboards.maqsam_section import add_maqsam_calls_section


def get_data(data: dict[str, Any] | None = None) -> dict[str, Any]:
    return add_maqsam_calls_section(data)
