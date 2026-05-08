(() => {
	frappe.provide("gain_maqsam.caller360");

	const RECENT_EVENT_TTL_MS = 15 * 1000;
	const RECENT_CALLS_LIMIT = 3;
	const AGENT_ENABLED_KEY = "gain_maqsam_agent_enabled";
	const INCOMING_AGENT_ROLES = ["Maqsam Agent", "System Manager"];
	let lastEventKey = "";
	let lastEventAt = 0;

	function consumeEventKey(key) {
		if (!key) return false;
		if (key === lastEventKey && Date.now() - lastEventAt < RECENT_EVENT_TTL_MS) {
			return false;
		}
		lastEventKey = key;
		lastEventAt = Date.now();
		return true;
	}

	function userCanReceiveIncomingCalls() {
		const roles = frappe.user_roles || [];
		return INCOMING_AGENT_ROLES.some((role) => roles.includes(role));
	}

	function incomingCallPopupsEnabled() {
		const dialer = window.gain_maqsam?.dialer;
		if (dialer?.isEnabled) {
			return Boolean(dialer.isEnabled());
		}
		if (window.gain_maqsam?.isAgentEnabled) {
			return Boolean(window.gain_maqsam.isAgentEnabled());
		}
		try {
			const stored = localStorage.getItem(AGENT_ENABLED_KEY);
			if (stored === null) return userCanReceiveIncomingCalls();
			return stored === "1";
		} catch (_) {
			return userCanReceiveIncomingCalls();
		}
	}

	function escapeHtml(value) {
		return String(value ?? "")
			.replaceAll("&", "&amp;")
			.replaceAll("<", "&lt;")
			.replaceAll(">", "&gt;")
			.replaceAll('"', "&quot;")
			.replaceAll("'", "&#39;");
	}

	function routeUrl(doctype, name) {
		if (!doctype || !name) return "#";
		return `/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}`;
	}

	function routeLink(doctype, name, label) {
		if (!doctype || !name) return escapeHtml(label || name || "");
		return `<a href="${routeUrl(doctype, name)}">${escapeHtml(label || name)}</a>`;
	}

	function money(value) {
		return window.format_currency ? window.format_currency(value || 0) : escapeHtml(value || 0);
	}

	function duration(seconds) {
		const total = Number(seconds || 0);
		if (!total) return "0s";
		const m = Math.floor(total / 60);
		const s = total % 60;
		return m ? `${m}m ${s}s` : `${s}s`;
	}

	function formatPhone(raw) {
		const digits = String(raw || "").replace(/\D/g, "");
		if (!digits) return "";
		if (digits.startsWith("966") && digits.length === 12) {
			return `+966 ${digits.slice(3, 5)} ${digits.slice(5, 8)} ${digits.slice(8)}`;
		}
		if (digits.length >= 10) {
			return `+${digits.slice(0, digits.length - 9)} ${digits.slice(-9, -6)} ${digits.slice(-6, -3)} ${digits.slice(-3)}`;
		}
		return `+${digits}`;
	}

	const STATE_LABELS = {
		ringing: { text: __("Ringing"), tone: "orange", icon: "📞" },
		in_progress: { text: __("Active call"), tone: "green", icon: "🟢" },
		answered: { text: __("Answered"), tone: "green", icon: "✓" },
		queued: { text: __("Queued"), tone: "gray", icon: "⏳" },
		dropped: { text: __("Dropped"), tone: "orange", icon: "⚠" },
		abandoned: { text: __("Abandoned"), tone: "orange", icon: "⚠" },
		no_answer: { text: __("No Answer"), tone: "orange", icon: "✗" },
		busy: { text: __("Busy"), tone: "orange", icon: "⛔" },
		failed: { text: __("Failed"), tone: "red", icon: "✗" },
		serviced: { text: __("Serviced"), tone: "green", icon: "✓" },
	};

	function stateBadge(state) {
		const key = String(state || "").toLowerCase().replace(/[\s-]/g, "_");
		const meta = STATE_LABELS[key] || { text: state || __("Unknown"), tone: "gray", icon: "•" };
		// data-state preserves the raw key so handlers (outcome default,
		// terminal-state checks) don't have to round-trip through the
		// localized label text.
		return `<span class="m360-state ${meta.tone}" data-state="${escapeHtml(key)}">${meta.icon} ${escapeHtml(meta.text)}</span>`;
	}

	function badge(text, tone = "gray") {
		return `<span class="m360-badge ${tone}">${escapeHtml(text || "")}</span>`;
	}

	function empty(text) {
		return `<div class="m360-empty">${escapeHtml(text)}</div>`;
	}

	function renderMatches(matches, primary) {
		if (!matches || !matches.length) {
			return empty(__("No matching record was found."));
		}
		return matches
			.map((match) => {
				const isPrimary = primary && match.doctype === primary.doctype && match.name === primary.name;
				return `
					<div class="m360-match ${isPrimary ? "primary" : ""}">
						<div class="m360-match-info">
							<div class="m360-match-title">
								${routeLink(match.doctype, match.name, match.title || match.name)}
								${isPrimary ? badge(__("Primary"), "green") : ""}
							</div>
							<div class="m360-muted">${escapeHtml(match.doctype)} · ${escapeHtml(match.matched_phone || match.source || "")}</div>
						</div>
						${match.status ? badge(match.status, "blue") : ""}
					</div>
				`;
			})
			.join("");
	}

	function renderRecentCalls(calls) {
		const list = (calls || []).slice(0, RECENT_CALLS_LIMIT);
		if (!list.length) {
			return empty(__("No recent calls for this number."));
		}
		const total = (calls || []).length;
		const rows = list
			.map((call) => `
				<div class="m360-row">
					<div class="m360-call-info">
						<div class="m360-strong">${routeLink("Maqsam Call Log", call.name, call.name)} · ${escapeHtml(call.direction || "")}</div>
						<div class="m360-muted">${escapeHtml(call.timestamp_display || "")}${call.agent_email ? " · " + escapeHtml(call.agent_email) : ""}</div>
					</div>
					<div class="m360-call-right">
						${badge(call.outcome || call.state || __("Unknown"), call.outcome === "Answered" ? "green" : "orange")}
						<div class="m360-muted">${duration(call.duration)}</div>
					</div>
				</div>
			`)
			.join("");
		const more = total > RECENT_CALLS_LIMIT
			? `<a class="m360-link" href="/app/maqsam-call-log?caller_number=${encodeURIComponent(calls[0]?.caller_number || "")}">${__("View all calls ({0})", [total])}</a>`
			: "";
		return rows + more;
	}

	function renderInvoicesCompact(invoices) {
		const inv = invoices || {};
		const unpaidCount = inv.unpaid_count || 0;
		const outstanding = inv.total_outstanding || 0;
		const recent = (inv.recent || []).slice(0, 3);
		if (!unpaidCount && !recent.length) {
			return empty(__("No invoices."));
		}
		const summary = `
			<div class="m360-money-card">
				<div>
					<div class="m360-muted">${__("Outstanding")}</div>
					<div class="m360-money">${money(outstanding)}</div>
				</div>
				${badge(__("{0} unpaid", [unpaidCount]), unpaidCount ? "orange" : "green")}
			</div>
		`;
		const list = recent
			.map((invoice) => `
				<div class="m360-row compact">
					<div>${routeLink("Sales Invoice", invoice.name, invoice.name)}<div class="m360-muted">${escapeHtml(invoice.posting_date || "")}</div></div>
					<div class="m360-call-right">${money(invoice.grand_total)}<div class="m360-muted">${escapeHtml(invoice.status || "")}</div></div>
				</div>
			`)
			.join("");
		return summary + list;
	}

	function renderAppointmentsCompact(appointments) {
		const apt = appointments || {};
		const upcoming = (apt.upcoming || []).slice(0, 3);
		const recent = (apt.recent || []).slice(0, 2);
		if (!upcoming.length && !recent.length) {
			return empty(__("No appointments."));
		}
		const renderList = (rows) =>
			rows
				.map((appointment) => `
					<div class="m360-row compact">
						<div>${routeLink("Patient Appointment", appointment.name, appointment.name)}<div class="m360-muted">${escapeHtml(appointment.appointment_display || "")}</div></div>
						${badge(appointment.status || __("Unknown"), "blue")}
					</div>
				`)
				.join("");
		let html = "";
		if (upcoming.length) {
			html += `<div class="m360-subtitle">${__("Upcoming")}</div>${renderList(upcoming)}`;
		}
		if (recent.length) {
			html += `<div class="m360-subtitle">${__("Recent")}</div>${renderList(recent)}`;
		}
		return html;
	}

	function renderActions(profile) {
		const primary = profile.primary_match;
		const summary = profile.profile_summary || {};
		const phone = String(summary.input_phone || "").replace(/\D/g, "");
		const buttons = [];

		if (primary && primary.doctype && primary.name) {
			const labelMap = {
				Patient: __("Open Patient File"),
				Customer: __("Open Customer"),
				Lead: __("Open Lead"),
				Contact: __("Open Contact"),
			};
			const label = labelMap[primary.doctype] || __("Open {0}", [primary.doctype]);
			buttons.push(`<a class="m360-btn primary" href="${routeUrl(primary.doctype, primary.name)}">📂 ${escapeHtml(label)}</a>`);

			if (primary.doctype === "Patient") {
				const url = `/app/patient-appointment/new?patient=${encodeURIComponent(primary.name)}`;
				buttons.push(`<a class="m360-btn" href="${url}">📅 ${__("New Appointment")}</a>`);
			}
		} else {
			buttons.push(`<button type="button" class="m360-btn primary" data-new-doc="Patient" data-phone="${escapeHtml(phone)}">🩺 ${__("New Patient")}</button>`);
			buttons.push(`<button type="button" class="m360-btn" data-new-doc="Lead" data-phone="${escapeHtml(phone)}">👤 ${__("New Lead")}</button>`);
		}

		return buttons.join("");
	}

	function renderSkeletonBody(profile, ctx) {
		// Compact skeleton for the lite/fast event: header + hero + answer
		// hint + a single loading indicator. The data sections (matches,
		// calls, invoices, appointments) are rendered only after the heavy
		// profile arrives via `upgradeSkeletonWithProfile`, so we don't
		// flash misleading "no records found" / "New Patient" actions
		// before the matcher has actually run.
		const summary = profile.profile_summary || {};
		const phone = formatPhone(summary.input_phone);
		const stateKey = String(ctx.state || "").toLowerCase().replace(/[\s-]/g, "_");
		const isAfterCall = TERMINAL_STATES.has(stateKey);
		const callLogHref = ctx.callLog ? routeUrl("Maqsam Call Log", ctx.callLog) : "#";

		return `
			<div class="m360-header">
				<div class="m360-header-left">
					${stateBadge(ctx.state || "ringing")}
					<span class="m360-timer" data-timer>00:00</span>
				</div>
				<div class="m360-header-right">
					<button class="m360-icon-btn ${isRingtoneMuted() ? "muted" : ""}" data-mute-toggle title="${
						isRingtoneMuted()
							? __("Unmute ringtone")
							: __("Mute ringtone (drawer still appears)")
					}" aria-label="${__("Mute ringtone")}">${isRingtoneMuted() ? "🔕" : "🔔"}</button>
					<button class="m360-close" data-close aria-label="${__("Close")}">×</button>
				</div>
			</div>

			<div class="m360-hero unknown">
				<div class="m360-name">${escapeHtml(summary.display_name || __("Looking up caller…"))}</div>
				<div class="m360-phone">${escapeHtml(phone || summary.input_phone || "")}</div>
				<div class="m360-meta">
					${badge(__("Loading"), "blue")}
				</div>
			</div>

				<div class="m360-answer-hint ${isAfterCall ? "hidden" : ""}" data-answer-hint>
					<span class="m360-answer-hint-text">${__("Answer and end the call inside Maqsam")}</span>
					<button type="button" class="m360-btn primary" data-open-dialer>${__("Show Dialer")}</button>
				</div>

			<div class="m360-after-call ${isAfterCall ? "show" : ""}" data-after-call>
				<div class="m360-after-title">
					<strong>${__("After Call")}</strong>
					<span data-after-call-state>${escapeHtml(ctx.state || "")}</span>
				</div>
				<div class="m360-after-duration" data-final-duration></div>
				<div class="m360-after-actions">
					${ctx.callLog ? `<button type="button" class="m360-btn primary" data-save-outcome>${__("Save Outcome / Note")}</button>` : ""}
					<button type="button" class="m360-btn" data-close-after-call>${__("Done")}</button>
				</div>
			</div>

			<div class="m360-actions">
				<a class="m360-btn ghost" href="${callLogHref}">${__("Call Log")}</a>
			</div>

			${ctx.callLog ? `
				<div class="m360-tag-row">
					<button type="button" class="m360-tag" data-tag="Wrong Number">🚫 ${__("Wrong Number")}</button>
					<button type="button" class="m360-tag" data-tag="Spam">⛔ ${__("Spam")}</button>
				</div>
			` : ""}

			<section class="m360-section m360-skeleton-block">
				<div class="m360-skeleton-row"></div>
				<div class="m360-skeleton-row"></div>
				<div class="m360-skeleton-row"></div>
				<div class="m360-skeleton-hint">${__("Fetching caller history…")}</div>
			</section>
		`;
	}

	function renderDrawerContent(profile, ctx) {
		if (profile && profile.__lite) {
			return renderSkeletonBody(profile, ctx);
		}

		const summary = profile.profile_summary || {};
		const known = Boolean(summary.known_caller);
		const phone = formatPhone(summary.input_phone);
		const matches = profile.matches || [];
		const primary = profile.primary_match;
		const invoices = profile.invoices || {};
		const apt = profile.appointments || {};
		const hasInvoices = (invoices.unpaid_count || 0) > 0 || (invoices.recent || []).length > 0;
		const hasApt = (apt.upcoming || []).length > 0 || (apt.recent || []).length > 0;
		const callLogHref = ctx.callLog ? routeUrl("Maqsam Call Log", ctx.callLog) : "#";
		const stateKey = String(ctx.state || "").toLowerCase().replace(/[\s-]/g, "_");
		const isAfterCall = TERMINAL_STATES.has(stateKey);

		return `
			<div class="m360-header">
				<div class="m360-header-left">
					${stateBadge(ctx.state || "ringing")}
					<span class="m360-timer" data-timer>00:00</span>
				</div>
				<button class="m360-close" data-close aria-label="${__("Close")}">×</button>
			</div>

			<div class="m360-hero ${known ? "known" : "unknown"}">
				<div class="m360-name">${escapeHtml(summary.display_name || __("Unknown Caller"))}</div>
				<div class="m360-phone">${escapeHtml(phone || summary.input_phone || "")}</div>
				<div class="m360-meta">
					${badge(summary.display_type || __("Unknown"), known ? "green" : "orange")}
					${badge(__("{0} matches", [summary.match_count || 0]), "blue")}
					${summary.last_outcome ? badge(summary.last_outcome, "orange") : ""}
				</div>
			</div>

				<div class="m360-answer-hint ${isAfterCall ? "hidden" : ""}" data-answer-hint>
					<span class="m360-answer-hint-text">${__("Answer and end the call inside Maqsam")}</span>
					<button type="button" class="m360-btn primary" data-open-dialer>${__("Show Dialer")}</button>
				</div>

			<div class="m360-after-call ${isAfterCall ? "show" : ""}" data-after-call>
				<div class="m360-after-title">
					<strong>${__("After Call")}</strong>
					<span data-after-call-state>${escapeHtml(ctx.state || "")}</span>
				</div>
				<div class="m360-after-duration" data-final-duration></div>
				<div class="m360-after-actions">
					${ctx.callLog ? `<button type="button" class="m360-btn primary" data-save-outcome>${__("Save Outcome / Note")}</button>` : ""}
					<button type="button" class="m360-btn" data-close-after-call>${__("Done")}</button>
				</div>
			</div>

			<div class="m360-actions">${renderActions(profile)}
				<a class="m360-btn ghost" href="${callLogHref}">${__("Call Log")}</a>
			</div>

			${ctx.callLog ? `
				<div class="m360-quick-row">
					<button type="button" class="m360-btn small" data-save-outcome>📝 ${__("Add Note / Outcome")}</button>
				</div>
				<div class="m360-tag-row">
					<button type="button" class="m360-tag" data-tag="Wrong Number">🚫 ${__("Wrong Number")}</button>
					<button type="button" class="m360-tag" data-tag="Spam">⛔ ${__("Spam")}</button>
				</div>
			` : ""}

			<section class="m360-section">
				<h4>${__("Matched Records")}${matches.length > 1 ? ` <span class="m360-count">${matches.length}</span>` : ""}</h4>
				${renderMatches(matches, primary)}
			</section>

			<section class="m360-section">
				<h4>${__("Recent Calls")}</h4>
				${renderRecentCalls(profile.recent_calls)}
			</section>

			<details class="m360-section collapsible" ${hasInvoices ? "open" : ""}>
				<summary><h4>${__("Invoices")}${(invoices.unpaid_count || 0) > 0 ? ` <span class="m360-count orange">${invoices.unpaid_count}</span>` : ""}</h4></summary>
				${renderInvoicesCompact(invoices)}
			</details>

			<details class="m360-section collapsible" ${hasApt ? "open" : ""}>
				<summary><h4>${__("Appointments")}${(apt.upcoming || []).length ? ` <span class="m360-count">${apt.upcoming.length}</span>` : ""}</h4></summary>
				${renderAppointmentsCompact(apt)}
			</details>
		`;
	}

	function injectStyles() {
		if (document.getElementById("m360-styles")) return;
		const style = document.createElement("style");
		style.id = "m360-styles";
		style.textContent = `
			.m360-drawer { position: fixed; top: 70px; inset-inline-end: 16px; width: 400px; max-width: calc(100vw - 32px); max-height: calc(100vh - 100px); background: #fff; border: 1px solid #e5e7eb; border-radius: 16px; box-shadow: 0 24px 48px rgba(15,23,42,.18), 0 4px 12px rgba(15,23,42,.08); z-index: 1050; overflow: hidden; display: flex; flex-direction: column; color: #0f172a; font-size: 13px; animation: m360-slide-in .25s ease-out; }
			@keyframes m360-slide-in { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: translateX(0); } }
			.m360-drawer.closing { animation: m360-slide-out .2s ease-in forwards; }
			@keyframes m360-slide-out { to { opacity: 0; transform: translateX(20px); } }
			.m360-drawer * { box-sizing: border-box; }
			.m360-drawer-body { overflow-y: auto; padding: 0 14px 14px; flex: 1; }
			.m360-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; border-bottom: 1px solid #f1f5f9; background: #fafbfc; }
			.m360-header-left { display: flex; gap: 10px; align-items: center; }
			.m360-timer { font-variant-numeric: tabular-nums; font-weight: 700; color: #475569; font-size: 14px; }
			.m360-close { border: 0; background: transparent; font-size: 22px; line-height: 1; cursor: pointer; color: #64748b; padding: 4px 10px; border-radius: 8px; }
			.m360-close:hover { background: #f1f5f9; color: #0f172a; }
			.m360-header-right { display: flex; gap: 4px; align-items: center; }
			.m360-icon-btn { border: 0; background: transparent; font-size: 16px; line-height: 1; cursor: pointer; color: #64748b; padding: 4px 8px; border-radius: 8px; transition: background .15s; }
			.m360-icon-btn:hover { background: #f1f5f9; color: #0f172a; }
			.m360-icon-btn.muted { color: #b45309; background: #fef3c7; }
			.m360-icon-btn.muted:hover { background: #fde68a; }
			.m360-hero { padding: 14px; border-radius: 12px; margin: 12px 0; background: linear-gradient(135deg, #f0fdfa, #f8fafc); border: 1px solid #d9e2dc; }
			.m360-hero.unknown { background: linear-gradient(135deg, #fef3c7, #fffbeb); border-color: #fde68a; }
			.m360-name { font-size: 18px; font-weight: 800; line-height: 1.2; }
			.m360-phone { color: #475569; font-size: 13px; margin-top: 4px; font-variant-numeric: tabular-nums; }
			.m360-meta { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
			.m360-answer-hint { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; margin-bottom: 12px; background: linear-gradient(135deg, #ecfeff, #f0fdfa); border: 1px solid #99f6e4; border-radius: 10px; font-size: 12px; color: #0f766e; font-weight: 600; }
			.m360-answer-hint.hidden { display: none; }
			.m360-answer-hint-text { flex: 1; min-width: 0; }
			.m360-answer-hint .m360-btn { padding: 6px 10px; font-size: 12px; flex-shrink: 0; }
			.m360-answer-hint .m360-btn:disabled { cursor: default; opacity: .85; }
			.m360-after-call { display: none; padding: 10px 12px; margin-bottom: 12px; background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 10px; }
			.m360-after-call.show { display: block; }
			.m360-after-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #334155; font-size: 12px; margin-bottom: 8px; }
			.m360-after-title span { color: #64748b; }
			.m360-after-duration { font-size: 13px; font-weight: 700; color: #0f172a; margin-bottom: 10px; font-variant-numeric: tabular-nums; }
			.m360-after-duration:empty { display: none; }
			.m360-after-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
			.m360-after-actions .m360-btn { padding: 8px 10px; font-size: 12px; }
			.m360-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 14px; }
			.m360-actions .m360-btn:first-child:nth-last-child(odd) { grid-column: 1 / -1; }
			.m360-btn { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 10px 12px; border-radius: 10px; border: 1px solid #e5e7eb; background: #fff; color: #0f172a; font-weight: 600; text-decoration: none; cursor: pointer; transition: all .15s; font-size: 13px; }
			.m360-btn:hover { background: #f8fafc; border-color: #cbd5e1; text-decoration: none; }
			.m360-btn.primary { background: #0f766e; color: #fff; border-color: #0f766e; }
			.m360-btn.primary:hover { background: #115e59; color: #fff; }
			.m360-btn.ghost { background: transparent; }
			.m360-section { margin-bottom: 14px; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; background: #fff; }
			.m360-section h4 { margin: 0 0 8px; font-size: 13px; font-weight: 800; color: #0f172a; display: inline-flex; align-items: center; gap: 6px; }
			.m360-section.collapsible { padding: 0; }
			.m360-section.collapsible > summary { padding: 12px; cursor: pointer; list-style: none; }
			.m360-section.collapsible > summary::-webkit-details-marker { display: none; }
			.m360-section.collapsible > summary::after { content: "▾"; float: right; color: #94a3b8; transition: transform .2s; }
			.m360-section.collapsible[open] > summary::after { transform: rotate(180deg); }
			.m360-section.collapsible > *:not(summary) { padding: 0 12px 12px; }
			.m360-count { background: #e0f2fe; color: #075985; border-radius: 999px; padding: 1px 7px; font-size: 11px; font-weight: 700; }
			.m360-count.orange { background: #ffedd5; color: #9a3412; }
			.m360-match, .m360-row { display: flex; justify-content: space-between; gap: 10px; padding: 8px 0; border-bottom: 1px solid #f1f5f9; }
			.m360-match:last-child, .m360-row:last-child { border-bottom: 0; }
			.m360-match.primary { background: #ecfdf5; border: 1px solid #bbf7d0; border-radius: 8px; padding: 9px; margin-bottom: 6px; }
			.m360-match-info, .m360-call-info { min-width: 0; flex: 1; }
			.m360-match-title, .m360-strong { font-weight: 700; }
			.m360-muted { color: #64748b; font-size: 11px; line-height: 1.5; margin-top: 2px; }
			.m360-call-right { text-align: end; min-width: 80px; }
			.m360-badge { display: inline-flex; align-items: center; border-radius: 999px; padding: 2px 8px; font-size: 10px; font-weight: 700; background: #f1f5f9; color: #475569; white-space: nowrap; }
			.m360-badge.green { background: #dcfce7; color: #166534; }
			.m360-badge.orange { background: #ffedd5; color: #9a3412; }
			.m360-badge.blue { background: #dbeafe; color: #1d4ed8; }
			.m360-badge.red { background: #fee2e2; color: #991b1b; }
			.m360-state { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; background: #f1f5f9; color: #475569; }
			.m360-state.green { background: #dcfce7; color: #166534; animation: m360-pulse 2s infinite; }
			.m360-state.orange { background: #ffedd5; color: #9a3412; animation: m360-pulse 1s infinite; }
			.m360-state.red { background: #fee2e2; color: #991b1b; }
			@keyframes m360-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .6; } }
			.m360-empty { color: #94a3b8; background: #f8fafc; border-radius: 8px; padding: 10px; font-size: 12px; text-align: center; }
			.m360-money-card { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; border-radius: 10px; background: #fff7ed; margin-bottom: 8px; }
			.m360-money { font-size: 16px; font-weight: 800; color: #9a3412; }
			.m360-subtitle { margin: 8px 0 4px; color: #334155; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .04em; }
			.m360-row.compact { padding: 6px 0; }
			.m360-link { display: block; padding: 8px 0 0; text-align: center; font-size: 12px; color: #0f766e; font-weight: 600; }
			.m360-quick-row { display: flex; gap: 6px; margin-bottom: 8px; }
			.m360-quick-row .m360-btn { flex: 1; padding: 7px 10px; font-size: 12px; background: #f0fdf4; border-color: #bbf7d0; color: #166534; }
			.m360-quick-row .m360-btn:hover { background: #dcfce7; border-color: #86efac; }
			.m360-tag-row { display: flex; gap: 6px; margin-bottom: 12px; }
			.m360-tag { flex: 1; padding: 6px 8px; border-radius: 8px; border: 1px solid #fecaca; background: #fff; color: #991b1b; font-size: 11px; font-weight: 600; cursor: pointer; transition: all .15s; }
			.m360-tag:hover { background: #fee2e2; border-color: #fca5a5; }
			[dir="rtl"] .m360-drawer { animation-name: m360-slide-in-rtl; }
			@keyframes m360-slide-in-rtl { from { opacity: 0; transform: translateX(-20px); } to { opacity: 1; transform: translateX(0); } }
			.m360-skeleton-block { padding: 12px; }
			.m360-skeleton-row { height: 14px; border-radius: 6px; background: linear-gradient(90deg, #f1f5f9, #e2e8f0, #f1f5f9); background-size: 200% 100%; animation: m360-skel 1.4s linear infinite; margin-bottom: 8px; }
			.m360-skeleton-row:nth-child(1) { width: 65%; }
			.m360-skeleton-row:nth-child(2) { width: 80%; }
			.m360-skeleton-row:nth-child(3) { width: 50%; }
			.m360-skeleton-hint { color: #94a3b8; font-size: 11px; text-align: center; margin-top: 6px; }
			@keyframes m360-skel { from { background-position: 200% 0; } to { background-position: -200% 0; } }
		`;
		document.head.appendChild(style);
	}

	function startTimer(el, since) {
		// `since` lets the caller resume an existing call's elapsed time after
		// re-rendering the drawer body (e.g. when the heavy profile arrives).
		const start = since || Date.now();
		const tick = () => {
			const s = Math.floor((Date.now() - start) / 1000);
			const m = Math.floor(s / 60);
			el.textContent = `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
		};
		tick();
		return setInterval(tick, 1000);
	}

	let activeRingtone = null;
	// Browsers (Chrome/Firefox/Safari) suspend any AudioContext created
	// without a prior user gesture. If the agent loads Frappe and waits for a
	// call without clicking anything, `new AudioContext()` produces silence.
	// Solution: hold a single shared context and resume it on the first user
	// interaction so the first ringtone actually plays.
	let sharedAudioContext = null;
	let audioContextPrimed = false;

	// Per-browser mute flag — independent of the agent's active/inactive
	// state on the floating dialer. When muted, the drawer still appears
	// (so the agent doesn't miss the call entirely), but the synthesized
	// ringtone is suppressed. Useful for meetings, training, open offices.
	const RINGTONE_MUTED_KEY = "gain_maqsam_ringtone_muted";

	function isRingtoneMuted() {
		try {
			return localStorage.getItem(RINGTONE_MUTED_KEY) === "1";
		} catch (_) {
			return false;
		}
	}

	function setRingtoneMuted(muted) {
		try {
			localStorage.setItem(RINGTONE_MUTED_KEY, muted ? "1" : "0");
		} catch (_) {}
		if (muted) stopRingtone();
		// Update any open drawer's mute button without re-rendering everything.
		if (activeDrawer) {
			const btn = activeDrawer.querySelector("[data-mute-toggle]");
			if (btn) {
				btn.textContent = muted ? "🔕" : "🔔";
				btn.title = muted
					? __("Unmute ringtone")
					: __("Mute ringtone (drawer still appears)");
				btn.classList.toggle("muted", muted);
			}
		}
	}

	function getAudioContext() {
		if (sharedAudioContext) return sharedAudioContext;
		const Ctx = window.AudioContext || window.webkitAudioContext;
		if (!Ctx) return null;
		try {
			sharedAudioContext = new Ctx();
		} catch (_) {
			return null;
		}
		return sharedAudioContext;
	}

	function primeAudioContext() {
		if (audioContextPrimed) return;
		const context = getAudioContext();
		if (!context) return;
		if (context.state === "suspended") {
			context.resume().catch(() => {});
		}
		audioContextPrimed = true;
	}

	const _primeOnGesture = () => {
		primeAudioContext();
		document.removeEventListener("click", _primeOnGesture, true);
		document.removeEventListener("keydown", _primeOnGesture, true);
		document.removeEventListener("touchstart", _primeOnGesture, true);
	};
	document.addEventListener("click", _primeOnGesture, true);
	document.addEventListener("keydown", _primeOnGesture, true);
	document.addEventListener("touchstart", _primeOnGesture, true);

	function stopRingtone() {
		if (!activeRingtone) return;
		try {
			if (activeRingtone.beat) clearInterval(activeRingtone.beat);
			activeRingtone.oscillator.stop();
			activeRingtone.oscillator.disconnect();
			activeRingtone.gain?.disconnect();
		} catch (_) {}
		// Don't close the shared context — we reuse it for the next call.
		activeRingtone = null;
	}

	function startRingtone() {
		stopRingtone();
		// Honor the per-browser mute toggle: drawer still opens (so the
		// agent sees the call), but no audible ringtone.
		if (isRingtoneMuted()) return;
		try {
			const context = getAudioContext();
			if (!context) return;
			if (context.state === "suspended") {
				context.resume().catch(() => {});
			}
			const oscillator = context.createOscillator();
			const gain = context.createGain();
			oscillator.type = "sine";
			oscillator.frequency.value = 660;
			gain.gain.value = 0;
			oscillator.connect(gain);
			gain.connect(context.destination);
			oscillator.start();
			let on = true;
			const beat = setInterval(() => {
				gain.gain.setTargetAtTime(on ? 0.08 : 0, context.currentTime, 0.02);
				on = !on;
			}, 500);
			activeRingtone = { oscillator, gain, beat };
			setTimeout(stopRingtone, 12000);
		} catch (_) {}
	}

	function closeDrawer(drawer) {
		stopRingtone();
		if (!drawer || !drawer.parentNode) return;
		clearTimeout(autoCloseId);
		autoCloseId = null;
		clearSkeletonFallback();
		if (activeTimer) {
			clearInterval(activeTimer);
			activeTimer = null;
		}
		stopLivePoll();
		drawer.classList.add("closing");
		setTimeout(() => {
			drawer.remove();
			if (!activeDrawer) showPendingDrawer();
		}, 200);
		if (activeDrawer === drawer) {
			activeDrawer = null;
			activeCallId = null;
			activeTimerStart = null;
			activeIsLite = false;
			activeStateKey = "";
		}
	}

	let activeDrawer = null;
	let activeTimer = null;
	let activeTimerStart = null;
	let activeCallId = null;
	let activeIsLite = false;
	let activeStateKey = "";
	let autoCloseId = null;
	let livePollTimer = null;

	const TERMINAL_STATES = new Set(["ended", "completed", "answered", "serviced", "abandoned", "dropped", "no_answer", "busy", "failed"]);
	const LIVE_STATES = new Set(["ringing", "in_progress", "active", "ongoing"]);

	function normalizeStateKey(state) {
		return String(state || "").toLowerCase().replace(/[\s-]/g, "_");
	}

	function preserveTerminalState(previousState, incomingState) {
		const previousKey = normalizeStateKey(previousState);
		const incomingKey = normalizeStateKey(incomingState);
		if (TERMINAL_STATES.has(previousKey) && !TERMINAL_STATES.has(incomingKey)) {
			return previousState;
		}
		return incomingState || previousState;
	}

	function stateForRender(state) {
		return preserveTerminalState(activeStateKey, state);
	}

	function syncDialerBusy(callLog, state) {
		if (!callLog) return;
		const dialer = window.gain_maqsam?.dialer;
		if (!dialer) return;

		const key = normalizeStateKey(state);
		if (TERMINAL_STATES.has(key)) {
			dialer.clearBusy?.(callLog);
			return;
		}
		if (LIVE_STATES.has(key)) {
			dialer.setBusy?.(callLog);
			setTimeout(() => dialer.clearBusy?.(callLog), 2 * 60 * 60 * 1000);
		}
	}

	function stopLivePoll() {
		if (!livePollTimer) return;
		clearInterval(livePollTimer);
		livePollTimer = null;
	}

	function refreshLiveCallState(callLog) {
		// Polled every 4s while a non-terminal call is on screen. Wrapped in
		// the callback-style frappe.call so server errors (e.g. the call log
		// got deleted, permissions revoked, Maqsam API 5xx) don't surface as
		// user-facing toasts. If the call is gone for good, stop polling so
		// we don't keep hammering a missing endpoint.
		if (!callLog || !activeDrawer || activeCallId !== callLog) return;
		frappe.call({
			method: "gain_maqsam_integration.api.maqsam_refresh_call_state",
			args: { call_log: callLog },
			freeze: false,
			callback: (response) => {
				const payload = response?.message || {};
				if (!payload.state || !activeDrawer || activeCallId !== callLog) return;
				updateDrawerState(payload.state);
			},
			error: (xhr) => {
				// 404/410-ish: the call log no longer exists — abandon polling
				// rather than spamming the channel with failed lookups.
				const status = xhr?.status || xhr?.statusCode;
				if (status === 404 || status === 410 || status === 417) {
					stopLivePoll();
				}
				// Otherwise stay quiet; next tick may succeed.
			},
		});
	}

	function startLivePoll(callLog, state) {
		const key = normalizeStateKey(state);
		if (!callLog || TERMINAL_STATES.has(key)) return;
		if (livePollTimer) return;
		livePollTimer = setInterval(() => refreshLiveCallState(callLog), 4000);
		setTimeout(() => refreshLiveCallState(callLog), 2500);
	}

	function setAfterCallMode(state) {
		if (!activeDrawer) return;
		activeStateKey = normalizeStateKey(state) || activeStateKey;
		stopLivePoll();
		if (activeCallId) {
			window.gain_maqsam?.dialer?.clearBusy?.(activeCallId);
		}
		// Freeze the call timer so the displayed duration matches reality.
		// The header timer keeps showing the final value; the after-call panel
		// surfaces it prominently for note-taking.
		const timerEl = activeDrawer.querySelector("[data-timer]");
		const finalDuration = timerEl ? timerEl.textContent : "";
		if (activeTimer) {
			clearInterval(activeTimer);
			activeTimer = null;
		}
		activeDrawer.querySelector("[data-answer-hint]")?.classList.add("hidden");
		const afterCall = activeDrawer.querySelector("[data-after-call]");
		if (afterCall) {
			afterCall.classList.add("show");
			const stateEl = afterCall.querySelector("[data-after-call-state]");
			if (stateEl) stateEl.textContent = state || "";
			const durEl = afterCall.querySelector("[data-final-duration]");
			if (durEl && finalDuration) durEl.textContent = __("Call duration: {0}", [finalDuration]);
		}
		const closeBtn = activeDrawer.querySelector("[data-close-after-call]");
		if (closeBtn) closeBtn.focus?.();
	}

	function updateDrawerState(state) {
		if (!activeDrawer) return;
		const currentKey = activeStateKey || activeDrawer.querySelector(".m360-state")?.dataset?.state || "";
		const nextState = preserveTerminalState(currentKey, state);
		const key = normalizeStateKey(nextState);
		if (currentKey && TERMINAL_STATES.has(normalizeStateKey(currentKey)) && !TERMINAL_STATES.has(key)) {
			return;
		}
		activeStateKey = key;
		const stateEl = activeDrawer.querySelector(".m360-state");
		if (stateEl) {
			const wrapper = document.createElement("span");
			wrapper.innerHTML = stateBadge(nextState);
			const fresh = wrapper.firstElementChild;
			if (fresh) stateEl.replaceWith(fresh);
		}
		if (key !== "ringing") stopRingtone();
		syncDialerBusy(activeCallId, nextState);
		if (TERMINAL_STATES.has(key)) {
			clearTimeout(autoCloseId);
			autoCloseId = null;
			setAfterCallMode(nextState);
		} else {
			startLivePoll(activeCallId, nextState);
		}
	}

	function linkCallToCreatedRecord(callLog, doctype, docname) {
		if (!callLog || !doctype || !docname) return;
		try {
			frappe.call({
				method: "gain_maqsam_integration.api.maqsam_link_call_to_record",
				args: { call_log: callLog, doctype, docname },
				freeze: false,
				silent: true,
				error: () => {},
			});
		} catch (_) {}
	}

	function wireDrawerHandlers(drawer, ctx) {
		// Re-attached on initial render AND after the body is re-rendered to
		// upgrade a skeleton drawer with the full profile. All handlers
		// reference module-level `activeTimer` via `closeDrawer`, so a fresh
		// timer ID after re-render is picked up automatically.
		drawer.querySelector("[data-close]")?.addEventListener("click", () => closeDrawer(drawer));

		drawer.querySelector("[data-mute-toggle]")?.addEventListener("click", () => {
			const next = !isRingtoneMuted();
			setRingtoneMuted(next);
			frappe.show_alert(
				{
					message: next
						? __("Ringtone muted. Drawer will still appear for incoming calls.")
						: __("Ringtone unmuted."),
					indicator: next ? "orange" : "green",
				},
				4,
			);
		});

		const openDialerBtn = drawer.querySelector("[data-open-dialer]");
		const reflectDialerState = () => {
			if (!openDialerBtn) return;
			const dialerApi = window.gain_maqsam?.dialer;
			const dialerOpen = !!dialerApi?.isOpen?.();
			if (dialerOpen) {
				openDialerBtn.textContent = "✓ " + __("Dialer open");
				openDialerBtn.classList.remove("primary");
				openDialerBtn.classList.add("ghost");
				openDialerBtn.disabled = true;
			} else {
				openDialerBtn.textContent = __("Show Dialer");
				openDialerBtn.classList.add("primary");
				openDialerBtn.classList.remove("ghost");
				openDialerBtn.disabled = false;
			}
		};
		reflectDialerState();
		openDialerBtn?.addEventListener("click", async () => {
			const dialer = window.gain_maqsam?.dialer;
			if (dialer?.open) await dialer.open();
			reflectDialerState();
		});
		// Outcome dialog: read the latest state directly from the badge so we
		// pre-fill with what actually happened (e.g. if the call moved from
		// `ringing` to `abandoned` while the drawer was open, default outcome
		// becomes "No Answer", not blank).
		drawer.querySelectorAll("[data-save-outcome]").forEach((btn) => {
			btn.addEventListener("click", () => {
				const liveState = drawer.querySelector(".m360-state")?.dataset?.state || ctx.state || "";
				openOutcomeDialog(ctx.callLog, { state: liveState });
			});
		});
		drawer.querySelector("[data-close-after-call]")?.addEventListener("click", () => {
			closeDrawer(drawer);
		});

		drawer.querySelectorAll("[data-tag]").forEach((btn) => {
			btn.addEventListener("click", () => {
				if (!ctx.callLog) return;
				const label = btn.dataset.tag;
				// Tagging permanently blocklists the number — a misclick costs
				// the agent a real customer until someone manually deletes
				// the row from `Maqsam Blocked Number`. Always confirm.
				const message = label === "Spam"
					? __("Mark this number as Spam? It will be blocked from future popups until manually unblocked.")
					: __("Mark this number as a Wrong Number? It will be blocked from future popups until manually unblocked.");

				frappe.confirm(
					message,
					async () => {
						btn.disabled = true;
						try {
							await frappe.call({
								method: "gain_maqsam_integration.api.maqsam_tag_call",
								args: { call_log: ctx.callLog, label },
							});
							frappe.show_alert(
								{
									message: __("Marked as {0}. The number is now blocked.", [label]),
									indicator: "orange",
								},
								8,
							);
							closeDrawer(drawer);
						} catch (e) {
							btn.disabled = false;
						}
					},
					() => {
						// User cancelled — leave button enabled.
					},
				);
			});
		});

		drawer.querySelectorAll("[data-new-doc]").forEach((btn) => {
			btn.addEventListener("click", () => {
				const doctype = btn.dataset.newDoc;
				const phone = btn.dataset.phone || "";
				const fieldMap = {
					Patient: { mobile: phone },
					Lead: { mobile_no: phone },
					Customer: { mobile_no: phone },
					Contact: { mobile_no: phone },
				};
				const values = fieldMap[doctype] || { mobile_no: phone };
				closeDrawer(drawer);

				frappe.route_options = { ...values };
				frappe.model.with_doctype(doctype, () => {
					const newDoc = frappe.model.get_new_doc(doctype, null, null, true);
					Object.assign(newDoc, values);

					const afterInsert = (doc) => {
						linkCallToCreatedRecord(ctx.callLog, doctype, doc?.name);
						if (doctype !== "Patient" || !doc?.name) return;
						frappe.confirm(
							__("Create an appointment for {0}?", [doc.patient_name || doc.name]),
							() => {
								frappe.model.with_doctype("Patient Appointment", () => {
									const aptDoc = frappe.model.get_new_doc("Patient Appointment", null, null, true);
									aptDoc.patient = doc.name;
									aptDoc.patient_name = doc.patient_name;
									aptDoc.patient_sex = doc.sex;
									aptDoc.patient_age = doc.dob;
									frappe.route_options = {
										patient: doc.name,
										patient_name: doc.patient_name,
									};
									frappe.ui.form.make_quick_entry(
										"Patient Appointment",
										null,
										(dlg) => {
											if (!dlg) return;
											if (dlg.fields_dict?.patient) dlg.set_value("patient", doc.name);
										},
										aptDoc,
										true,
									);
								});
							},
						);
					};

					frappe.ui.form.make_quick_entry(doctype, afterInsert, (dialog) => {
						if (!dialog) return;
						Object.entries(values).forEach(([k, v]) => {
							if (v && dialog.fields_dict?.[k]) dialog.set_value(k, v);
						});
					}, newDoc, true);
				});
			});
		});
	}

	const SKELETON_FALLBACK_MS = 4000;
	let skeletonFallbackTimer = null;
	let skeletonFallbackCall = null;

	function clearSkeletonFallback() {
		if (skeletonFallbackTimer) {
			clearTimeout(skeletonFallbackTimer);
			skeletonFallbackTimer = null;
		}
		skeletonFallbackCall = null;
	}

	async function fetchProfileSilent(args) {
		// Like fetchProfile, but suppresses the user-facing error toast that
		// frappe.call shows on DoesNotExistError or similar — the fallback is
		// a best-effort backstop, agents shouldn't see "Not found" if it
		// fails. Returns null instead of throwing.
		return new Promise((resolve) => {
			frappe.call({
				method: "gain_maqsam_integration.api.maqsam_get_caller_profile",
				args,
				freeze: false,
				callback: (response) => resolve(response?.message || null),
				error: () => resolve(null),
			});
		});
	}

	function scheduleSkeletonFallback(ctx) {
		// Backstop for the queued profile dispatcher: if the worker is slow,
		// errored, or the realtime channel dropped the heavy event, the
		// drawer would otherwise sit on the skeleton forever. After a short
		// grace period, fetch the profile directly from the API and upgrade.
		clearSkeletonFallback();
		if (!ctx.callLog && !ctx.phone) return;
		skeletonFallbackCall = ctx.callLog || ctx.phone;
		skeletonFallbackTimer = setTimeout(async () => {
			if (!activeIsLite || !activeDrawer || activeCallId !== ctx.callLog) return;
			// Prefer phone over call_log: call_log may not exist (test events)
			// or the user may lack read permission on the underlying doc.
			// Phone is always safe — get_caller_profile only uses it for the
			// matcher/recent-calls/invoice lookup.
			const args = ctx.phone ? { phone: ctx.phone } : { call_log: ctx.callLog };
			const fetched = await fetchProfileSilent(args);
			if (!fetched || !fetched.profile_summary) return;
			if (!activeIsLite || !activeDrawer || activeCallId !== ctx.callLog) return;
			upgradeSkeletonWithProfile(fetched, ctx);
		}, SKELETON_FALLBACK_MS);
	}

	function upgradeSkeletonWithProfile(profile, ctx) {
		// The fast lite event opened a skeleton drawer; the heavy event has
		// now arrived with the real profile. Re-render the body in place so
		// the agent sees the full content without losing the timer's elapsed
		// time or starting a second ringtone.
		if (!activeDrawer) return;
		clearSkeletonFallback();
		const body = activeDrawer.querySelector(".m360-drawer-body");
		if (!body) return;
		const effectiveCtx = { ...ctx, state: stateForRender(ctx.state) };
		body.innerHTML = renderDrawerContent(profile, effectiveCtx);
		activeIsLite = false;

		// Restart the timer against the original start time so the ticker
		// keeps counting from where it was, not from 00:00.
		if (activeTimer) {
			clearInterval(activeTimer);
			activeTimer = null;
		}
		const newTimerEl = activeDrawer.querySelector("[data-timer]");
		if (newTimerEl && activeTimerStart) {
			activeTimer = startTimer(newTimerEl, activeTimerStart);
		}
		wireDrawerHandlers(activeDrawer, effectiveCtx);

		// If state is already terminal, immediately freeze the (just-restarted)
		// timer and surface After Call mode.
		const stateKey = normalizeStateKey(effectiveCtx.state);
		if (TERMINAL_STATES.has(stateKey)) {
			setAfterCallMode(effectiveCtx.state);
		} else {
			syncDialerBusy(ctx.callLog, effectiveCtx.state);
			startLivePoll(ctx.callLog, effectiveCtx.state);
		}
	}

	function showDrawer(profile, ctx = {}) {
		injectStyles();
		if (activeDrawer && activeCallId && activeCallId === ctx.callLog) {
			// Same call. Three sub-cases:
			//  1. lite arrived for an already-rendered drawer → state badge update only
			//  2. full arrived while drawer is still skeleton → upgrade body in place
			//  3. duplicate full → state update is the only safe op
			const incomingHasProfile = !ctx.lite && profile && profile.profile_summary && !profile.__lite;
			if (activeIsLite && incomingHasProfile) {
				upgradeSkeletonWithProfile(profile, ctx);
			}
			updateDrawerState(ctx.state || "ringing");
			return activeDrawer;
		}
		// Keep the active call drawer stable. Additional calls are queued so
		// agents don't lose their current call context or half-written notes.
		if (activeDrawer && activeCallId && ctx.callLog && activeCallId !== ctx.callLog) {
			queuePendingDrawer(profile, ctx);
			return activeDrawer;
		}
		if (activeDrawer) closeDrawer(activeDrawer);
		clearTimeout(autoCloseId);

		const effectiveCtx = { ...ctx, state: stateForRender(ctx.state) };
		const drawer = document.createElement("div");
		drawer.className = "m360-drawer";
		drawer.innerHTML = `<div class="m360-drawer-body">${renderDrawerContent(profile, effectiveCtx)}</div>`;
		document.body.appendChild(drawer);

		const timerEl = drawer.querySelector("[data-timer]");
		activeTimerStart = Date.now();
		activeTimer = timerEl ? startTimer(timerEl, activeTimerStart) : null;

		wireDrawerHandlers(drawer, effectiveCtx);

		activeDrawer = drawer;
		activeCallId = effectiveCtx.callLog || null;
		activeIsLite = !!(ctx.lite || profile?.__lite);
		activeStateKey = normalizeStateKey(effectiveCtx.state);

		// Safety net: if we opened a skeleton drawer but the queued heavy
		// dispatch never publishes (worker stuck, dispatcher errored, no
		// listeners on the channel), fetch the profile directly via API
		// after a short grace period so the agent isn't stuck staring at
		// "Looking up caller…" forever.
		if (activeIsLite && ctx.callLog) {
			scheduleSkeletonFallback(effectiveCtx);
		}

		// If the drawer is opened with a state that's already terminal (e.g.
		// clicking "Caller Profile" on a finished call log, or a missed-call
		// webhook arriving as `ended`), freeze the timer immediately so the
		// 00:00 ticker doesn't run as if the call were live.
		const initialKey = normalizeStateKey(effectiveCtx.state);
		if (TERMINAL_STATES.has(initialKey)) {
			setAfterCallMode(effectiveCtx.state);
		} else {
			syncDialerBusy(effectiveCtx.callLog, effectiveCtx.state);
			startLivePoll(effectiveCtx.callLog, effectiveCtx.state);
		}

		// Only ring when this is an active inbound call event — manual opens
		// (clicking "Caller Profile" on a saved call log) must stay silent.
		if (effectiveCtx.state === "ringing") startRingtone();

		const escHandler = (event) => {
			if (event.key !== "Escape" || !activeDrawer) return;
			closeDrawer(drawer);
			document.removeEventListener("keydown", escHandler);
		};
		document.addEventListener("keydown", escHandler);

		return drawer;
	}

	function showDialog(profile, opts = {}) {
		showDrawer(profile, { title: opts.title, callLog: opts.callLog, state: opts.state });
	}

	// Track the outcome dialog so we can defer opening a new drawer if the
	// agent is in the middle of saving notes for the previous call.
	// Without this, an incoming call B closes drawer A out from under the
	// dialog → A's notes silently lose their context.
	let outcomeDialogOpen = false;
	let pendingDrawers = []; // queued { profile, ctx } calls behind the active drawer

	function pendingDrawerKey(ctx) {
		return ctx?.callLog || ctx?.maqsamCallId || ctx?.phone || "";
	}

	function queuePendingDrawer(profile, ctx) {
		const key = pendingDrawerKey(ctx);
		const index = pendingDrawers.findIndex((item) => pendingDrawerKey(item.ctx) === key);
		const incomingHasProfile = profile && profile.profile_summary && !profile.__lite;
		if (index >= 0) {
			const existing = pendingDrawers[index];
			pendingDrawers[index] = {
				profile: incomingHasProfile ? profile : existing.profile,
				ctx: {
					...existing.ctx,
					...ctx,
					state: preserveTerminalState(existing.ctx?.state, ctx?.state),
				},
			};
			return;
		}

		pendingDrawers.push({ profile, ctx });
		const phone = ctx.phone || profile?.profile_summary?.input_phone || __("a new caller");
		frappe.show_alert(
			{
				message: __("📞 New call from {0} queued behind the active call.", [phone]),
				indicator: "blue",
			},
			12,
		);
	}

	function showPendingDrawer() {
		if (!pendingDrawers.length) return;
		const { profile, ctx } = pendingDrawers.shift();
		showDrawer(profile, ctx);
	}

	// Map call state → most likely outcome the agent will pick. Used to
	// pre-fill the outcome dialog so abandoned calls aren't logged as
	// blank, and so the agent saves 5 seconds in every form they fill.
	const STATE_TO_OUTCOME = {
		answered: "Answered",
		serviced: "Answered",
		completed: "Answered",
		no_answer: "No Answer",
		abandoned: "No Answer",
		dropped: "No Answer",
		missed: "No Answer",
		busy: "Busy",
		failed: "Other",
	};

	function inferDefaultOutcome(state) {
		const key = normalizeStateKey(state);
		return STATE_TO_OUTCOME[key] || "";
	}

	function openOutcomeDialog(callLog, opts = {}) {
		if (!callLog) return;

		const currentState = opts.state || "";
		const defaultOutcome = inferDefaultOutcome(currentState);

		const dialog = new frappe.ui.Dialog({
			title: __("Call Outcome"),
			fields: [
				{
					fieldname: "outcome",
					fieldtype: "Select",
					label: __("Outcome"),
					options: "\nAnswered\nNo Answer\nBusy\nWrong Number\nFollow Up\nOther",
					default: defaultOutcome,
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
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				await frappe.call({
					method: "gain_maqsam_integration.api.maqsam_update_call_outcome",
					args: { call_log: callLog, ...values },
				});
				dialog.hide();
				frappe.show_alert({ message: __("Call outcome saved."), indicator: "green" });
			},
		});

		// Track the dialog so a new incoming call doesn't ambush the agent
		// mid-note. We hook both the standard hide event and the explicit
		// onhide override so cancel and save both release the lock.
		outcomeDialogOpen = true;
		const releaseLock = () => {
			outcomeDialogOpen = false;
			if (!activeDrawer) showPendingDrawer();
		};
		dialog.$wrapper.on("hidden.bs.modal", releaseLock);

		dialog.show();
	}

	async function fetchProfile(args) {
		const response = await frappe.call({
			method: "gain_maqsam_integration.api.maqsam_get_caller_profile",
			args,
		});
		return response.message || {};
	}

	function renderProfile(profile) {
		return renderDrawerContent(profile, {});
	}

	function buildLiteProfile(event) {
		// Synthetic placeholder profile so the skeleton drawer can render via
		// the same code path as the full one. Filled with whatever the lite
		// payload knows (phone + direction); the heavy event will overwrite
		// this once the matcher/invoice/appointment lookups complete.
		return {
			profile_summary: {
				input_phone: event?.phone || "",
				display_name: __("Looking up caller…"),
				display_type: __("Loading"),
				known_caller: false,
				match_count: 0,
			},
			matches: [],
			recent_calls: [],
			invoices: {},
			appointments: {},
			__lite: true,
		};
	}

	function handleIncomingEvent(event) {
		const id = event?.call_log || event?.maqsam_call_id || "";
		const state = event?.state || "ringing";
		const sameActiveCall = activeCallId && activeCallId === event?.call_log;
		if (!sameActiveCall && !incomingCallPopupsEnabled()) {
			return false;
		}
		const isLite = event?.lite === true || !event?.profile;
		// Different keys for lite vs full so both fire for the same call:
		// lite opens the skeleton fast; full upgrades it once the heavy
		// lookup completes. Same-variant duplicates within 15s still dedupe.
		const variant = isLite ? "lite" : "full";
		const key = `${id}::${state}::${variant}`;
		if (!consumeEventKey(key)) return false;
		const profile = isLite ? buildLiteProfile(event) : event.profile;
		showDrawer(profile, {
			callLog: event.call_log,
			maqsamCallId: event.maqsam_call_id,
			state,
			lite: isLite,
			phone: event.phone || profile?.profile_summary?.input_phone || "",
		});
		return true;
	}

	function registerRealtime() {
		if (gain_maqsam.caller360._registered) return true;
		if (!frappe.realtime || !frappe.realtime.socket) return false;
		gain_maqsam.caller360._registered = true;
		frappe.realtime.on("maqsam_incoming_call", handleIncomingEvent);
		return true;
	}

	function keepRealtimeAlive() {
		const socket = frappe.realtime?.socket;
		if (!socket) {
			registerRealtime();
			return;
		}

		if (socket.disconnected) {
			try {
				frappe.realtime.connect();
			} catch (_) {
				try {
					socket.connect();
				} catch (_) {}
			}
		}
		registerRealtime();
	}

	Object.assign(gain_maqsam.caller360, {
		fetchProfile,
		renderProfile,
		showDialog,
		showDrawer,
		registerRealtime,
	});

	$(document).on("app_ready", registerRealtime);
	if (!registerRealtime()) {
		const interval = setInterval(() => {
			if (registerRealtime()) clearInterval(interval);
		}, 500);
		setTimeout(() => clearInterval(interval), 30000);
	}
	setInterval(keepRealtimeAlive, 10000);
	setTimeout(keepRealtimeAlive, 1000);
})();
