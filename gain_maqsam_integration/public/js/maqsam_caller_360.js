(() => {
	frappe.provide("gain_maqsam.caller360");

	const RECENT_EVENT_TTL_MS = 15 * 1000;
	let lastEventKey = "";
	let lastEventAt = 0;

	function consumeEventKey(key) {
		if (!key) {
			return false;
		}
		if (key === lastEventKey && Date.now() - lastEventAt < RECENT_EVENT_TTL_MS) {
			return false;
		}
		lastEventKey = key;
		lastEventAt = Date.now();
		return true;
	}

	function escapeHtml(value) {
		return String(value ?? "")
			.replaceAll("&", "&amp;")
			.replaceAll("<", "&lt;")
			.replaceAll(">", "&gt;")
			.replaceAll('"', "&quot;")
			.replaceAll("'", "&#39;");
	}

	function routeLink(doctype, name, label) {
		if (!doctype || !name) {
			return escapeHtml(label || name || "");
		}
		return `<a href="/desk/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}">${escapeHtml(label || name)}</a>`;
	}

	function money(value) {
		return window.format_currency ? window.format_currency(value || 0) : escapeHtml(value || 0);
	}

	function duration(seconds) {
		const total = Number(seconds || 0);
		if (!total) return "0s";
		const minutes = Math.floor(total / 60);
		const remaining = total % 60;
		return minutes ? `${minutes}m ${remaining}s` : `${remaining}s`;
	}

	function badge(text, tone = "gray") {
		return `<span class="caller360-badge ${tone}">${escapeHtml(text || "")}</span>`;
	}

	function empty(text) {
		return `<div class="caller360-empty">${escapeHtml(text)}</div>`;
	}

	function renderMatches(matches = [], primary) {
		if (!matches.length) {
			return empty(__("No matching Patient, Customer, Lead, or Contact was found."));
		}
		return matches
			.map((match) => {
				const isPrimary = primary && match.doctype === primary.doctype && match.name === primary.name;
				return `
					<div class="caller360-match ${isPrimary ? "primary" : ""}">
						<div>
							<div class="caller360-match-title">
								${routeLink(match.doctype, match.name, match.title || match.name)}
								${isPrimary ? badge(__("Primary"), "green") : ""}
							</div>
							<div class="caller360-muted">${escapeHtml(match.doctype)} · ${escapeHtml(match.matched_phone || match.source || "")}</div>
						</div>
						${match.status ? badge(match.status, "blue") : ""}
					</div>
				`;
			})
			.join("");
	}

	function renderCalls(calls = []) {
		if (!calls.length) {
			return empty(__("No recent calls were found for this number."));
		}
		return calls
			.map((call) => `
				<div class="caller360-row">
					<div>
						<div class="caller360-strong">${routeLink("Maqsam Call Log", call.name, call.name)} · ${escapeHtml(call.direction || "")}</div>
						<div class="caller360-muted">${escapeHtml(call.timestamp_display || "")} · ${escapeHtml(call.agent_email || "")}</div>
					</div>
					<div class="caller360-right">
						${badge(call.outcome || call.state || __("Unknown"), call.outcome === "Answered" ? "green" : "orange")}
						<div class="caller360-muted">${duration(call.duration)}</div>
					</div>
				</div>
			`)
			.join("");
	}

	function renderInvoices(invoices = {}) {
		const unpaid = invoices.unpaid || [];
		const recent = invoices.recent || [];
		return `
			<div class="caller360-money-card">
				<div>
					<div class="caller360-muted">${__("Outstanding")}</div>
					<div class="caller360-money">${money(invoices.total_outstanding || 0)}</div>
				</div>
				${badge(__("{0} unpaid", [invoices.unpaid_count || 0]), invoices.unpaid_count ? "orange" : "green")}
			</div>
			<div class="caller360-subtitle">${__("Unpaid Invoices")}</div>
			${
				unpaid.length
					? unpaid
							.map((invoice) => `
								<div class="caller360-row compact">
									<div>${routeLink("Sales Invoice", invoice.name, invoice.name)}<div class="caller360-muted">${escapeHtml(invoice.status || "")}</div></div>
									<div class="caller360-right">${money(invoice.outstanding_amount)}</div>
								</div>
							`)
							.join("")
					: empty(__("No unpaid invoices."))
			}
			<div class="caller360-subtitle">${__("Last 10 Invoices")}</div>
			${
				recent.length
					? recent
							.map((invoice) => `
								<div class="caller360-row compact">
									<div>${routeLink("Sales Invoice", invoice.name, invoice.name)}<div class="caller360-muted">${escapeHtml(invoice.posting_date || "")}</div></div>
									<div class="caller360-right">${money(invoice.grand_total)}<div class="caller360-muted">${escapeHtml(invoice.status || "")}</div></div>
								</div>
							`)
							.join("")
					: empty(__("No invoices found."))
			}
		`;
	}

	function renderAppointments(appointments = {}) {
		const upcoming = appointments.upcoming || [];
		const recent = appointments.recent || [];
		const renderList = (rows, fallback) =>
			rows.length
				? rows
						.map((appointment) => `
							<div class="caller360-row compact">
								<div>${routeLink("Patient Appointment", appointment.name, appointment.name)}<div class="caller360-muted">${escapeHtml(appointment.appointment_display || "")}</div></div>
								${badge(appointment.status || __("Unknown"), "blue")}
							</div>
						`)
						.join("")
				: empty(fallback);

		return `
			<div class="caller360-subtitle">${__("Upcoming")}</div>
			${renderList(upcoming, __("No upcoming appointments."))}
			<div class="caller360-subtitle">${__("Recent")}</div>
			${renderList(recent, __("No recent appointments."))}
		`;
	}

	function renderProfile(profile = {}) {
		const summary = profile.profile_summary || {};
		const primary = profile.primary_match;
		const known = Boolean(summary.known_caller);
		return `
			<style>
				.caller360 { display: grid; gap: 14px; color: #111827; }
				.caller360-hero { border: 1px solid #d9e2dc; border-radius: 18px; padding: 18px; background: linear-gradient(135deg, #f0fdfa, #f8fafc); display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; }
				.caller360-title { font-size: 22px; font-weight: 850; line-height: 1.15; }
				.caller360-phone { color: #475569; font-size: 13px; margin-top: 5px; }
				.caller360-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
				.caller360-card { border: 1px solid #e5e7eb; border-radius: 14px; background: #fff; padding: 14px; box-shadow: 0 6px 18px rgba(15, 23, 42, .04); }
				.caller360-card h4 { font-size: 14px; margin: 0 0 10px; font-weight: 800; color: #0f172a; }
				.caller360-match, .caller360-row { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid #f1f5f9; }
				.caller360-match:last-child, .caller360-row:last-child { border-bottom: 0; }
				.caller360-match.primary { background: #ecfdf5; border: 1px solid #bbf7d0; border-radius: 10px; padding: 10px; margin-bottom: 8px; }
				.caller360-match-title, .caller360-strong { font-weight: 750; }
				.caller360-muted { color: #64748b; font-size: 12px; line-height: 1.5; }
				.caller360-right { text-align: right; min-width: 90px; }
				.caller360-badge { display: inline-flex; align-items: center; border-radius: 999px; padding: 3px 8px; font-size: 11px; font-weight: 800; background: #f1f5f9; color: #475569; white-space: nowrap; }
				.caller360-badge.green { background: #dcfce7; color: #166534; }
				.caller360-badge.orange { background: #ffedd5; color: #9a3412; }
				.caller360-badge.blue { background: #dbeafe; color: #1d4ed8; }
				.caller360-empty { color: #94a3b8; background: #f8fafc; border-radius: 10px; padding: 10px; font-size: 13px; }
				.caller360-money-card { display: flex; justify-content: space-between; align-items: center; padding: 12px; border-radius: 12px; background: #fff7ed; margin-bottom: 10px; }
				.caller360-money { font-size: 20px; font-weight: 850; color: #9a3412; }
				.caller360-subtitle { margin: 12px 0 4px; color: #334155; font-size: 12px; font-weight: 850; text-transform: uppercase; letter-spacing: .04em; }
				.caller360-row.compact { padding: 7px 0; }
				@media (max-width: 900px) { .caller360-grid { grid-template-columns: 1fr; } .caller360-hero { flex-direction: column; } }
			</style>
			<div class="caller360">
				<div class="caller360-hero">
					<div>
						<div class="caller360-title">${escapeHtml(summary.display_name || __("Unknown Caller"))}</div>
						<div class="caller360-phone">${escapeHtml(summary.input_phone || "")}</div>
						<div class="caller360-phone">${known ? __("Known caller") : __("No linked record found yet")}</div>
					</div>
					<div class="caller360-right">
						${badge(summary.display_type || __("Unknown"), known ? "green" : "orange")}
						<div style="margin-top: 8px;">${badge(__("{0} matches", [summary.match_count || 0]), "blue")}</div>
						${summary.last_outcome ? `<div style="margin-top: 8px;">${badge(summary.last_outcome, "orange")}</div>` : ""}
					</div>
				</div>
				<div class="caller360-grid">
					<div class="caller360-card"><h4>${__("Matched Records")}</h4>${renderMatches(profile.matches || [], primary)}</div>
					<div class="caller360-card"><h4>${__("Recent Calls")}</h4>${renderCalls(profile.recent_calls || [])}</div>
					<div class="caller360-card"><h4>${__("Invoices")}</h4>${renderInvoices(profile.invoices || {})}</div>
					<div class="caller360-card"><h4>${__("Appointments")}</h4>${renderAppointments(profile.appointments || {})}</div>
				</div>
			</div>
		`;
	}

	async function fetchProfile(args) {
		const response = await frappe.call({
			method: "gain_maqsam_integration.api.maqsam_get_caller_profile",
			args,
		});
		return response.message || {};
	}

	function showDialog(profile, opts = {}) {
		const dialog = new frappe.ui.Dialog({
      title: opts.title || __("Caller Profile"),
			size: "extra-large",
			fields: [{ fieldname: "profile_html", fieldtype: "HTML" }],
			primary_action_label: __("Close"),
			primary_action: () => dialog.hide(),
		});
		dialog.show();
		dialog.fields_dict.profile_html.$wrapper.html(renderProfile(profile));
	}

	function registerRealtime() {
		if (!frappe.realtime || gain_maqsam.caller360._registered) {
			return;
		}
		gain_maqsam.caller360._registered = true;
		frappe.realtime.on("maqsam_incoming_call", (event) => {
			const key = event?.call_log || event?.maqsam_call_id || JSON.stringify(event || {});
			if (!consumeEventKey(key)) {
				return;
			}
			showDialog(event.profile || {}, { title: __("Incoming Call - Caller Profile") });
		});
	}

	Object.assign(gain_maqsam.caller360, {
		fetchProfile,
		renderProfile,
		showDialog,
		registerRealtime,
	});

	$(document).on("app_ready", registerRealtime);
	registerRealtime();
})();
