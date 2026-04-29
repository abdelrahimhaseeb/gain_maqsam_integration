// Copyright (c) 2026, Ghain and contributors
// For license information, please see license.txt

frappe.query_reports["Hourly Call Heatmap"] = {
	filters: [
		{
			fieldname: "days",
			label: __("Last N Days"),
			fieldtype: "Int",
			default: 30,
			reqd: 1,
		},
	],
	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (column.fieldname && column.fieldname.startsWith("h") && typeof value === "number" && value > 0) {
			// Heat scale: pale teal -> deep teal based on value vs row max
			const rowMax = Math.max(
				...Object.keys(data || {})
					.filter((k) => k.startsWith("h"))
					.map((k) => Number(data[k] || 0)),
			);
			const ratio = rowMax ? value / rowMax : 0;
			const alpha = Math.max(0.08, Math.min(0.85, ratio));
			return `<div style="background: rgba(15, 118, 110, ${alpha}); color: ${ratio > 0.5 ? "#fff" : "#0f172a"}; text-align: center; font-weight: 600; border-radius: 4px;">${formatted}</div>`;
		}
		return formatted;
	},
};
