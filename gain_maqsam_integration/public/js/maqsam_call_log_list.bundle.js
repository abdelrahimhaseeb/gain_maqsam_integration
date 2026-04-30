(() => {
	const AUTO_SYNC_KEY = "gain_maqsam_call_log_last_auto_sync";
	const AUTO_SYNC_INTERVAL_MS = 60 * 1000;

	function canSyncCalls() {
		return Boolean(
			frappe.user?.has_role?.("System Manager") ||
				(frappe.user_roles || []).includes("System Manager"),
		);
	}

	async function syncRecentCalls({ silent = false } = {}) {
		if (!canSyncCalls()) {
			return null;
		}

		if (silent) {
			const lastSync = Number(localStorage.getItem(AUTO_SYNC_KEY) || 0);
			if (Date.now() - lastSync < AUTO_SYNC_INTERVAL_MS) {
				return null;
			}
			localStorage.setItem(AUTO_SYNC_KEY, String(Date.now()));
		}

		const response = await frappe.call({
			method: "gain_maqsam_integration.api.maqsam_sync_recent_calls",
			args: { page: 1 },
			freeze: !silent,
		});
		const result = response.message || {};

		if (!silent || result.created) {
			frappe.show_alert({
				message: __("Synced {0} new and {1} existing calls.", [
					result.created || 0,
					result.updated || 0,
				]),
				indicator: result.created ? "green" : "blue",
			});
		}

		return result;
	}

	frappe.listview_settings["Maqsam Call Log"] = {
		onload(listview) {
			if (!canSyncCalls()) {
				return;
			}

			listview.page.add_inner_button(__("Sync Recent Calls"), async () => {
				await syncRecentCalls();
				listview.refresh();
			});

			syncRecentCalls({ silent: true })
				.then((result) => {
					if (result && (result.created || result.updated)) {
						listview.refresh();
					}
				})
				.catch((error) => {
					console.error("Failed to auto-sync Maqsam calls", error);
				});
		},
	};
})();
