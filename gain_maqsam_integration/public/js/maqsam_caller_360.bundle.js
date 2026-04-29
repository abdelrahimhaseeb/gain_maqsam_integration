(() => {
	frappe.provide("gain_maqsam.caller360");

	const RECENT_EVENT_TTL_MS = 15 * 1000;
	const RECENT_CALLS_LIMIT = 3;
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
		no_answer: { text: __("No Answer"), tone: "orange", icon: "✗" },
		busy: { text: __("Busy"), tone: "orange", icon: "⛔" },
		failed: { text: __("Failed"), tone: "red", icon: "✗" },
	};

	function stateBadge(state) {
		const key = String(state || "").toLowerCase().replace(/[\s-]/g, "_");
		const meta = STATE_LABELS[key] || { text: state || __("Unknown"), tone: "gray", icon: "•" };
		return `<span class="m360-state ${meta.tone}">${meta.icon} ${escapeHtml(meta.text)}</span>`;
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

	function renderDrawerContent(profile, ctx) {
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

			<div class="m360-actions">${renderActions(profile)}
				<a class="m360-btn ghost" href="${callLogHref}">📝 ${__("Call Log")}</a>
			</div>

			${ctx.callLog ? `
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
			.m360-hero { padding: 14px; border-radius: 12px; margin: 12px 0; background: linear-gradient(135deg, #f0fdfa, #f8fafc); border: 1px solid #d9e2dc; }
			.m360-hero.unknown { background: linear-gradient(135deg, #fef3c7, #fffbeb); border-color: #fde68a; }
			.m360-name { font-size: 18px; font-weight: 800; line-height: 1.2; }
			.m360-phone { color: #475569; font-size: 13px; margin-top: 4px; font-variant-numeric: tabular-nums; }
			.m360-meta { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
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
			.m360-tag-row { display: flex; gap: 6px; margin-bottom: 12px; }
			.m360-tag { flex: 1; padding: 6px 8px; border-radius: 8px; border: 1px solid #fecaca; background: #fff; color: #991b1b; font-size: 11px; font-weight: 600; cursor: pointer; transition: all .15s; }
			.m360-tag:hover { background: #fee2e2; border-color: #fca5a5; }
			[dir="rtl"] .m360-drawer { animation-name: m360-slide-in-rtl; }
			@keyframes m360-slide-in-rtl { from { opacity: 0; transform: translateX(-20px); } to { opacity: 1; transform: translateX(0); } }
		`;
		document.head.appendChild(style);
	}

	function startTimer(el) {
		const start = Date.now();
		const tick = () => {
			const s = Math.floor((Date.now() - start) / 1000);
			const m = Math.floor(s / 60);
			el.textContent = `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
		};
		tick();
		return setInterval(tick, 1000);
	}

	let activeRingtone = null;

	function stopRingtone() {
		if (!activeRingtone) return;
		try {
			activeRingtone.oscillator.stop();
			activeRingtone.context.close();
		} catch (_) {}
		activeRingtone = null;
	}

	function startRingtone() {
		stopRingtone();
		try {
			const Ctx = window.AudioContext || window.webkitAudioContext;
			if (!Ctx) return;
			const context = new Ctx();
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
			activeRingtone = { context, oscillator, beat };
			setTimeout(stopRingtone, 12000);
		} catch (_) {}
	}

	function closeDrawer(drawer, timerId) {
		stopRingtone();
		if (!drawer || !drawer.parentNode) return;
		clearInterval(timerId);
		drawer.classList.add("closing");
		setTimeout(() => drawer.remove(), 200);
	}

	let activeDrawer = null;
	let activeTimer = null;
	let activeCallId = null;
	let autoCloseId = null;

	const TERMINAL_STATES = new Set(["ended", "completed", "dropped", "no_answer", "busy", "failed", "answered"]);

	function updateDrawerState(state) {
		if (!activeDrawer) return;
		const stateEl = activeDrawer.querySelector(".m360-state");
		if (stateEl) {
			const wrapper = document.createElement("span");
			wrapper.innerHTML = stateBadge(state);
			const fresh = wrapper.firstElementChild;
			if (fresh) stateEl.replaceWith(fresh);
		}
		const key = String(state || "").toLowerCase().replace(/[\s-]/g, "_");
		if (key !== "ringing") stopRingtone();
		if (TERMINAL_STATES.has(key)) {
			clearTimeout(autoCloseId);
			autoCloseId = setTimeout(() => {
				if (activeDrawer) closeDrawer(activeDrawer, activeTimer);
				activeCallId = null;
			}, 5000);
		}
	}

	function showDrawer(profile, ctx = {}) {
		injectStyles();
		if (activeDrawer && activeCallId && activeCallId === ctx.callLog) {
			updateDrawerState(ctx.state || "ringing");
			return activeDrawer;
		}
		if (activeDrawer) closeDrawer(activeDrawer, activeTimer);
		clearTimeout(autoCloseId);

		const drawer = document.createElement("div");
		drawer.className = "m360-drawer";
		drawer.innerHTML = `<div class="m360-drawer-body">${renderDrawerContent(profile, ctx)}</div>`;
		document.body.appendChild(drawer);

		const timerEl = drawer.querySelector("[data-timer]");
		const timerId = timerEl ? startTimer(timerEl) : null;

		drawer.querySelector("[data-close]")?.addEventListener("click", () => closeDrawer(drawer, timerId));

		drawer.querySelectorAll("[data-tag]").forEach((btn) => {
			btn.addEventListener("click", async () => {
				if (!ctx.callLog) return;
				const label = btn.dataset.tag;
				btn.disabled = true;
				try {
					await frappe.call({
						method: "gain_maqsam_integration.api.maqsam_tag_call",
						args: { call_log: ctx.callLog, label },
					});
					frappe.show_alert({ message: __("Marked as {0}", [label]), indicator: "orange" });
					closeDrawer(drawer, timerId);
				} catch (e) {
					btn.disabled = false;
				}
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
				closeDrawer(drawer, timerId);

				frappe.route_options = { ...values };
				frappe.model.with_doctype(doctype, () => {
					const newDoc = frappe.model.get_new_doc(doctype, null, null, true);
					Object.assign(newDoc, values);

					const afterInsert = (doc) => {
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

		activeDrawer = drawer;
		activeTimer = timerId;
		activeCallId = ctx.callLog || null;

		// Only ring when this is an active inbound call event — manual opens
		// (clicking "Caller Profile" on a saved call log) must stay silent.
		if (ctx.state === "ringing") startRingtone();

		const escHandler = (event) => {
			if (event.key !== "Escape" || !activeDrawer) return;
			closeDrawer(drawer, timerId);
			document.removeEventListener("keydown", escHandler);
		};
		document.addEventListener("keydown", escHandler);

		return drawer;
	}

	function showDialog(profile, opts = {}) {
		showDrawer(profile, { title: opts.title, callLog: opts.callLog, state: opts.state });
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

	function registerRealtime() {
		if (gain_maqsam.caller360._registered) return true;
		if (!frappe.realtime || !frappe.realtime.socket) return false;
		gain_maqsam.caller360._registered = true;
		frappe.realtime.on("maqsam_incoming_call", (event) => {
			const id = event?.call_log || event?.maqsam_call_id || "";
			const state = event?.state || "ringing";
			const key = `${id}::${state}`;
			if (!consumeEventKey(key)) return;
			showDrawer(event.profile || {}, {
				callLog: event.call_log,
				state,
			});
		});
		return true;
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
})();
