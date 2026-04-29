// Copyright (c) 2026, Ghain and contributors
// For license information, please see license.txt

frappe.query_reports["Call to Appointment Conversion"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -30),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "window_hours",
			label: __("Booking Window (hours)"),
			fieldtype: "Int",
			default: 24,
			description: __("Count appointments created within this window after a call as 'converted'."),
		},
	],
};
