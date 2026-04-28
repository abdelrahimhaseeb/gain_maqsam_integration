app_name = "gain_maqsam_integration"
app_title = "Gain Maqsam Integration"
app_publisher = "Ghain"
app_description = "Maqsam integration for Gain"
app_email = "ops@ghain.local"
app_license = "mit"

required_apps = ["erpnext"]

app_include_js = ["maqsam_caller_360.bundle.js"]

doctype_js = {
	"Maqsam Settings": "public/js/maqsam_settings.js",
	"Maqsam Call Log": "public/js/maqsam_call_log.js",
	"Lead": "public/js/maqsam_click_to_call.js",
	"Contact": "public/js/maqsam_click_to_call.js",
	"Customer": "public/js/maqsam_click_to_call.js",
	"Patient": "public/js/maqsam_click_to_call.js",
	"Patient Appointment": "public/js/maqsam_click_to_call.js",
}

doctype_list_js = {
	"Maqsam Call Log": "public/js/maqsam_call_log_list.js",
}

scheduler_events = {
	"cron": {
		"*/5 * * * *": [
			"gain_maqsam_integration.api.maqsam_auto_sync_recent_calls",
		],
	},
	"daily": [
		"gain_maqsam_integration.api.maqsam_trim_old_payloads",
		"gain_maqsam_integration.api.maqsam_cleanup_old_recordings",
	],
}
