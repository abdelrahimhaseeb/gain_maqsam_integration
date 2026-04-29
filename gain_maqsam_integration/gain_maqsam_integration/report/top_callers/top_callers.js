// Copyright (c) 2026, Ghain and contributors
// For license information, please see license.txt

frappe.query_reports["Top Callers"] = {
	filters: [
		{
			fieldname: "days",
			label: __("Last N Days"),
			fieldtype: "Int",
			default: 30,
			reqd: 1,
		},
		{
			fieldname: "limit",
			label: __("Limit"),
			fieldtype: "Int",
			default: 50,
		},
	],
};
