// Copyright (c) 2026, Ghain and contributors
// For license information, please see license.txt

frappe.query_reports["Missed Calls Queue"] = {
	filters: [
		{
			fieldname: "days",
			label: __("Last N Days"),
			fieldtype: "Int",
			default: 7,
			reqd: 1,
		},
		{
			fieldname: "agent_email",
			label: __("Agent Email"),
			fieldtype: "Data",
		},
		{
			fieldname: "only_pending_followup",
			label: __("Only Pending Follow-up"),
			fieldtype: "Check",
			default: 0,
		},
	],
};
