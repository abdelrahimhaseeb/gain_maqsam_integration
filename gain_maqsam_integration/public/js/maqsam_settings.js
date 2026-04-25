frappe.ui.form.on("Maqsam Settings", {
	refresh(frm) {
		const webhookUrl = `${window.location.origin}/api/method/gain_maqsam_integration.api.maqsam_receive_call_event`;
		frm.fields_dict.incoming_webhook_url?.set_input(webhookUrl);
		frm.set_df_property(
			"help_text",
			"options",
			[
				"<div class='text-muted'>",
				"<p>Use this screen to store the Maqsam API credentials for this Gain site.</p>",
        "<p>You can update credentials, test the connection, use click-to-call, and configure Caller Profile popups for incoming calls.</p>",
				"</div>",
			].join(""),
		);

		frm.add_custom_button(__("Test Connection"), async () => {
			const response = await frappe.call({
				method: "gain_maqsam_integration.api.maqsam_test_connection",
			});

			const result = response.message || {};
			frappe.msgprint({
				title: __("Maqsam Connection"),
				indicator: "green",
				message: `
					<div><strong>API Base:</strong> ${frappe.utils.escape_html(result.api_base || "")}</div>
					<div><strong>Agents:</strong> ${result.agents_count ?? "-"}</div>
					<div><strong>Contacts:</strong> ${result.contacts_count ?? "-"}</div>
				`,
			});
		});

		frm.add_custom_button(__("Sync Recent Calls"), async () => {
			const response = await frappe.call({
				method: "gain_maqsam_integration.api.maqsam_sync_recent_calls",
				args: { page: 1 },
			});

			const result = response.message || {};
			frappe.show_alert({
				message: __("Synced {0} new and {1} existing calls.", [
					result.created || 0,
					result.updated || 0,
				]),
				indicator: "green",
			});
		});

		frm.add_custom_button(__("Show Recent Calls"), async () => {
			const response = await frappe.call({
				method: "gain_maqsam_integration.api.maqsam_list_recent_calls",
				args: { page: 1 },
			});

			const calls = response.message || [];
			const rows = calls.slice(0, 10).map((call) => {
				return `
					<tr>
						<td>${call.id}</td>
						<td>${frappe.utils.escape_html(call.direction || "")}</td>
						<td>${frappe.utils.escape_html(call.state || "")}</td>
						<td>${frappe.utils.escape_html(call.callerNumber || "")}</td>
						<td>${frappe.utils.escape_html(call.calleeNumber || "")}</td>
						<td>${call.duration ?? 0}</td>
					</tr>
				`;
			});

			frappe.msgprint({
				title: __("Recent Calls"),
				wide: true,
				message: `
					<table class="table table-bordered">
						<thead>
							<tr>
								<th>ID</th>
								<th>Direction</th>
								<th>State</th>
								<th>Caller</th>
								<th>Callee</th>
								<th>Duration</th>
							</tr>
						</thead>
						<tbody>${rows.join("") || "<tr><td colspan='6'>No calls found.</td></tr>"}</tbody>
					</table>
				`,
			});
		});

		frm.add_custom_button(__("Open Caller Profile"), () => {
			frappe.set_route("maqsam-caller-profile");
		});

		frm.add_custom_button(__("Copy Webhook URL"), () => {
			frappe.utils.copy_to_clipboard(webhookUrl);
			frappe.show_alert({ message: __("Webhook URL copied."), indicator: "green" });
		});
	},
});
