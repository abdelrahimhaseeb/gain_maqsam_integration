(() => {
	const STATUS_COLORS = {
		available: "green",
		busy: "orange",
		away: "orange",
		absent: "red",
		offline: "red",
	};

	function escapeHtml(value) {
		return String(value || "")
			.replaceAll("&", "&amp;")
			.replaceAll("<", "&lt;")
			.replaceAll(">", "&gt;")
			.replaceAll('"', "&quot;")
			.replaceAll("'", "&#39;");
	}

	function normalizeStatus(state) {
		return String(state || "").trim().toLowerCase();
	}

	function formatStatus(state) {
		const normalized = normalizeStatus(state);
		if (!normalized) {
			return __("Unknown");
		}

		return normalized
			.split("_")
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
			.join(" ");
	}

	function getStatusIndicator(state) {
		return STATUS_COLORS[normalizeStatus(state)] || "gray";
	}

	function sleep(ms) {
		return new Promise((resolve) => {
			setTimeout(resolve, ms);
		});
	}

	function buildAgentStatusHtml(defaults) {
		const status = defaults.agent_status || {};
		const portalUrl = defaults.portal_url;
		const isReady = Boolean(status.can_make_outbound_calls);
		const badgeColor = isReady ? "#166534" : "#991b1b";
		const badgeBg = isReady ? "#dcfce7" : "#fee2e2";
		const messageColor = isReady ? "#166534" : "#7f1d1d";
		const stateText = status.state ? escapeHtml(status.state) : __("unknown");
		const linkHtml = portalUrl
			? `<a href="${escapeHtml(portalUrl)}" target="_blank" rel="noreferrer">${__("Open Maqsam Portal")}</a>`
			: "";

		return `
			<div style="border:1px solid ${isReady ? "#bbf7d0" : "#fecaca"}; background:${isReady ? "#f0fdf4" : "#fef2f2"}; color:${messageColor}; border-radius:10px; padding:12px 14px; margin-top:4px;">
				<div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
					<span style="display:inline-block; padding:2px 10px; border-radius:999px; background:${badgeBg}; color:${badgeColor}; font-weight:700; font-size:12px;">
						${isReady ? __("Ready") : __("Not Ready")}
					</span>
					<span style="font-size:12px; opacity:.85;">${__("Agent state")}: <strong>${stateText}</strong></span>
				</div>
				<div style="font-size:13px; line-height:1.5;">
					${escapeHtml(status.message || "")}
				</div>
				${linkHtml ? `<div style="margin-top:8px; font-size:13px;">${linkHtml}</div>` : ""}
			</div>
		`;
	}

	function showAgentStatusDialog(status) {
		const indicator = getStatusIndicator(status.state);
		const portalUrl = status.portal_url;
		const message = `
			<div style="line-height:1.7;">
				<div><strong>${__("Agent Email")}:</strong> ${escapeHtml(status.email || "")}</div>
				<div><strong>${__("Agent State")}:</strong> ${escapeHtml(formatStatus(status.state))}</div>
				<div><strong>${__("Status")}</strong>: ${escapeHtml(status.message || "")}</div>
				${portalUrl ? `<div style="margin-top:8px;"><a href="${escapeHtml(portalUrl)}" target="_blank" rel="noreferrer">${__("Open Maqsam Portal")}</a></div>` : ""}
			</div>
		`;

		frappe.msgprint({
			title: __("Maqsam Agent Status"),
			indicator,
			message,
		});
	}

	function openPendingDialerWindow() {
		const dialerWindow = window.open("", "_blank");
		if (dialerWindow?.document) {
			dialerWindow.document.write(
				`<html><head><title>${__("Opening Maqsam")}</title></head><body style="font-family: sans-serif; padding: 24px;">${__("Opening Maqsam dialer...")}</body></html>`
			);
			dialerWindow.document.close();
		}
		return dialerWindow;
	}

	async function getMaqsamAutoLoginUrl(continuePath = "/phone/dialer") {
		const response = await frappe.call({
			method: "gain_maqsam_integration.api.maqsam_get_autologin_url",
			args: {
				continue_path: continuePath,
			},
		});
		const payload = response.message || {};
		if (!payload.url) {
			frappe.throw(__("Maqsam auto-login URL was not generated."));
		}

		return payload.url;
	}

	async function openMaqsamAutoLogin(continuePath = "/phone/dialer") {
		// Prefer the embedded floating dialer so the agent stays in the desk and
		// the outbound call lands in the same dialer the system is showing.
		const embedded = window.gain_maqsam?.dialer;
		if (embedded?.open) {
			try {
				await embedded.open();
				return;
			} catch (error) {
				// Fall through to the standalone-window fallback below.
			}
		}

		const dialerWindow = openPendingDialerWindow();
		try {
			const url = await getMaqsamAutoLoginUrl(continuePath);
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

	async function fetchAgentStatus({ silent = false } = {}) {
		const response = await frappe.call({
			method: "gain_maqsam_integration.api.maqsam_get_agent_status",
			silent,
		});
		return response.message || {};
	}

	async function waitForAgentReady({ attempts = 12, delayMs = 1000 } = {}) {
		let lastStatus = {};

		for (let index = 0; index < attempts; index += 1) {
			lastStatus = await fetchAgentStatus();
			if (lastStatus.can_make_outbound_calls) {
				return lastStatus;
			}

			if (index < attempts - 1) {
				await sleep(delayMs);
			}
		}

		return lastStatus;
	}

	async function openClickToCallDialog(frm) {
		const defaultsResponse = await frappe.call({
			method: "gain_maqsam_integration.api.maqsam_get_click_to_call_defaults",
			args: {
				doctype: frm.doctype,
				docname: frm.doc.name,
			},
		});
		const defaults = defaultsResponse.message || {};
		const phoneCandidates = defaults.phone_candidates || [];
		const rawPhoneCandidates = defaults.raw_phone_candidates || [];
		const callerOptions = defaults.caller_options || [];
		const phoneFieldtype = phoneCandidates.length ? "Autocomplete" : "Data";
		const callerFieldtype = callerOptions.length ? "Select" : "Data";
		const agentStatus = defaults.agent_status || {};
		const phoneWasNormalized =
			phoneCandidates.length &&
			rawPhoneCandidates.length &&
			JSON.stringify(phoneCandidates) !== JSON.stringify(rawPhoneCandidates);

		const dialog = new frappe.ui.Dialog({
			title: __("Call via Maqsam"),
			fields: [
				{
					fieldname: "phone",
					fieldtype: phoneFieldtype,
					label: __("Phone Number"),
					reqd: 1,
					default: defaults.default_phone || "",
					options: phoneCandidates.join("\n"),
					description: phoneCandidates.length
						? phoneWasNormalized
							? __("Loaded from the record's contact numbers and normalized to Maqsam international format. You can still edit it.")
							: __("Loaded from the record's contact numbers. You can still edit it.")
						: __("No saved contact number was found on this record. You can enter one manually."),
				},
				{
					fieldname: "agent_email",
					fieldtype: "Data",
					label: __("Agent Email"),
					reqd: 1,
					read_only: 1,
					default: defaults.default_agent_email || frappe.session.user_email || frappe.session.user || "",
				},
				{
					fieldname: "agent_status_html",
					fieldtype: "HTML",
					options: buildAgentStatusHtml(defaults),
				},
				{
					fieldname: "caller",
					fieldtype: callerFieldtype,
					label: __("Caller Number"),
					default: defaults.default_caller || "",
					options: callerOptions.join("\n"),
					description: callerOptions.length
						? __("Choose one of the caller numbers available in Maqsam.")
						: __("No caller numbers were detected from Maqsam yet. You can enter one manually."),
				},
			],
			primary_action_label: __("Start Call"),
			primary_action: async (values) => {
				const dialer = window.gain_maqsam?.dialer;
				let dialerWindow = null;
				try {
					if (dialer?.open) {
						await dialer.open();
					} else {
						dialerWindow = openPendingDialerWindow();
						const dialerUrl = await getMaqsamAutoLoginUrl("/phone/dialer");
						if (dialerWindow) dialerWindow.location.href = dialerUrl;
						else window.open(dialerUrl, "_blank", "noopener,noreferrer");
					}

					frappe.show_alert({
						message: __("Opening Maqsam dialer and waiting for the agent to become ready..."),
						indicator: "blue",
					});

					const readyStatus = await waitForAgentReady();
					if (!readyStatus.can_make_outbound_calls) {
						frappe.throw(
							__(
								"The dialer was opened, but the Maqsam agent is still not ready. Please make sure the agent becomes online in Maqsam, then try again."
							)
						);
					}

					const callResponse = await frappe.call({
						method: "gain_maqsam_integration.api.maqsam_create_click_to_call",
						args: {
							...values,
							doctype: frm.doctype,
							docname: frm.doc.name,
						},
					});

					dialog.hide();
					frappe.show_alert({ message: __("Call request sent to Maqsam and dialer opened."), indicator: "green" });
					const callLog = callResponse.message?.call_log;
					const dialer = window.gain_maqsam?.dialer;
					if (dialer?.setBusy && callLog) {
						dialer.setBusy(callLog);
						setTimeout(() => dialer.clearBusy?.(callLog), 5 * 60 * 1000);
					}
					openOutcomeDialog(callLog);
				} catch (error) {
					throw error;
				}
			},
		});

		dialog.show();
	}

	function openOutcomeDialog(callLog) {
		if (!callLog) {
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Call Outcome"),
			fields: [
				{
					fieldname: "outcome",
					fieldtype: "Select",
					label: __("Outcome"),
					options: "\nAnswered\nNo Answer\nBusy\nWrong Number\nFollow Up\nOther",
				},
				{
					fieldname: "follow_up_required",
					fieldtype: "Check",
					label: __("Follow-up Required"),
				},
				{
					fieldname: "follow_up_date",
					fieldtype: "Date",
					label: __("Follow-up Date"),
					depends_on: "eval:doc.follow_up_required",
				},
				{
					fieldname: "notes",
					fieldtype: "Small Text",
					label: __("Notes"),
				},
			],
			primary_action_label: __("Save Outcome"),
			primary_action: async (values) => {
				await frappe.call({
					method: "gain_maqsam_integration.api.maqsam_update_call_outcome",
					args: {
						call_log: callLog,
						outcome: values.outcome,
						notes: values.notes,
						follow_up_required: values.follow_up_required,
						follow_up_date: values.follow_up_date,
					},
				});
				dialog.hide();
				frappe.show_alert({ message: __("Call outcome saved."), indicator: "green" });
			},
		});

		dialog.show();
	}

	function addButton(frm) {
		if (frm.is_new()) {
			return;
		}

		let agentStatus = {};
		if (frm.page?.set_secondary_action) {
			frm.page.set_secondary_action(__("Maqsam"), () => openClickToCallDialog(frm), "phone-call");
		}

		frm.add_custom_button(__("Enable Calling Status"), () => openMaqsamAutoLogin("/phone/dialer"), __("Maqsam"));
		frm.add_custom_button(__("Call Customer"), () => openClickToCallDialog(frm), __("Maqsam"));
		frm.add_custom_button(__("Open Maqsam Home"), () => openMaqsamAutoLogin("/"), __("Maqsam"));
		const statusButton = frm.add_custom_button(
			__("Status: Loading"),
			() => showAgentStatusDialog(agentStatus),
			__("Maqsam")
		);

		fetchAgentStatus({ silent: true })
			.then((status) => {
				agentStatus = status || {};
				statusButton.text(__("Status: {0}", [formatStatus(agentStatus.state)]));
			})
			.catch((error) => {
				console.error("Failed to load Maqsam agent status", error);
				statusButton.text(__("Status: Unknown"));
			});
	}

	frappe.ui.form.on("Lead", {
		refresh(frm) {
			addButton(frm);
		},
	});

	frappe.ui.form.on("Contact", {
		refresh(frm) {
			addButton(frm);
		},
	});

	frappe.ui.form.on("Customer", {
		refresh(frm) {
			addButton(frm);
		},
	});

	frappe.ui.form.on("Patient", {
		refresh(frm) {
			addButton(frm);
		},
	});

	frappe.ui.form.on("Patient Appointment", {
		refresh(frm) {
			addButton(frm);
		},
	});
})();
