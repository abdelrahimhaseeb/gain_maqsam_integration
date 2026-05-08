async function openMaqsamDirect(continuePath = "/phone/dialer") {
	const dialerWindow = window.open("", "_blank");
	if (dialerWindow?.document) {
		dialerWindow.document.write(
			`<html><head><title>${__("Opening Maqsam")}</title></head><body style="font-family: sans-serif; padding: 24px;">${__("Opening Maqsam...")}</body></html>`
		);
		dialerWindow.document.close();
	}

	try {
		const response = await frappe.call({
			method: "gain_maqsam_integration.api.maqsam_get_autologin_url",
			args: { continue_path: continuePath },
		});
		const url = response.message?.url;
		if (!url) {
			frappe.throw(__("Maqsam auto-login URL was not generated."));
		}
		if (dialerWindow) {
			dialerWindow.location.href = url;
		} else {
			window.open(url, "_blank", "noopener,noreferrer");
		}
	} catch (error) {
		if (dialerWindow && !dialerWindow.closed) {
			dialerWindow.close();
		}
		throw error;
	}
}

frappe.ui.form.on("Maqsam Settings", {
	refresh(frm) {
		const currentWebhookUrl = `${window.location.origin}/api/method/gain_maqsam_integration.api.maqsam_receive_call_event`;
		const savedWebhookUrl = (frm.doc.incoming_webhook_url || "").trim();
		if (!savedWebhookUrl && !frm.is_new()) {
			frm.set_value("incoming_webhook_url", currentWebhookUrl);
		} else if (savedWebhookUrl && savedWebhookUrl !== currentWebhookUrl) {
			frm.set_intro(
				__("Saved webhook URL does not match this site's current URL. Update it before copying the URL into Maqsam."),
				"orange",
			);
			frm.add_custom_button(__("Use Current Webhook URL"), async () => {
				await frm.set_value("incoming_webhook_url", currentWebhookUrl);
				await frm.save();
				frappe.show_alert({ message: __("Webhook URL updated."), indicator: "green" });
			}, __("Webhook"));
		} else {
			frm.set_intro("");
		}
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

			frm.add_custom_button(__("Open Maqsam Dialer"), () => {
				openMaqsamDirect("/phone/dialer");
			}, __("Maqsam"));

			frm.add_custom_button(__("Open Maqsam Portal"), () => {
				openMaqsamDirect("/");
			}, __("Maqsam"));

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

		frm.add_custom_button(__("Copy Current Webhook URL"), () => {
			frappe.utils.copy_to_clipboard(currentWebhookUrl);
			frappe.show_alert({ message: __("Current webhook URL copied."), indicator: "green" });
		}, __("Webhook"));
	},
});
