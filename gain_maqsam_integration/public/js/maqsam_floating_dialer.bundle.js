// Floating Maqsam mini-dialer.
//
// Shows a phone FAB in the bottom-right corner that expands into a draggable
// 380x560 window with the Maqsam portal embedded via the autologin URL. The
// same instance is exposed as `window.gain_maqsam.dialer` so click-to-call
// flows can ensure the dialer is open before placing a call instead of
// spawning a separate browser tab.

(() => {
	const REQUIRED_ROLES = ["Maqsam Agent", "System Manager"];
	const STORAGE_KEY = "gain_maqsam_floating_position";
	const AGENT_ENABLED_KEY = "gain_maqsam_agent_enabled";
	const PANEL_VISIBLE_KEY = "gain_maqsam_dialer_visible";
	const URL_TTL_MS = 10 * 1000;
	const STATUS_POLL_MS = 30 * 1000;
	const MOBILE_BREAKPOINT = 600;
	// /app/maqsam-dialer renders the same iframe full-screen — don't double up.
	const HIDDEN_ROUTES = new Set(["maqsam-dialer"]);

	let cachedUrl = "";
	let urlFetchedAt = 0;
	let frameLoadedAt = 0;
	let agentStatusTimer = null;
	let drawerObserver = null;
	let busyCallId = null;
	let activeCallContext = null;
	let busyMessageShownAt = 0;
	let drawerSavedPosition = null;
	let elements = null;

	frappe.provide("gain_maqsam.dialer");

	function userIsAgent() {
		const roles = frappe.user_roles || [];
		return REQUIRED_ROLES.some((role) => roles.includes(role));
	}

	function agentEnabled() {
		// Default to enabled for actual Maqsam Agents who never made an
		// explicit choice — otherwise a fresh login would silently swallow
		// incoming-call popups until the user happens to click the FAB.
		// Users who deliberately deactivate themselves (FAB → gray) keep
		// that choice persisted as "0".
		const stored = localStorage.getItem(AGENT_ENABLED_KEY);
		if (stored === null) return userIsAgent();
		return stored === "1";
	}

	function panelShouldBeVisible() {
		return localStorage.getItem(PANEL_VISIBLE_KEY) === "1";
	}

	function setPanelVisible(visible) {
		localStorage.setItem(PANEL_VISIBLE_KEY, visible ? "1" : "0");
		if (elements) {
			elements.win.classList.toggle("hidden", !visible);
			elements.fab.classList.toggle("active", visible);
		}
		updateAvailabilityUi();
	}

	function setAgentEnabled(enabled) {
		localStorage.setItem(AGENT_ENABLED_KEY, enabled ? "1" : "0");
		window.gain_maqsam.agentEnabled = enabled;
		updateAvailabilityUi();
		window.dispatchEvent(new CustomEvent("maqsam_agent_availability_changed", { detail: { enabled } }));
	}

	window.gain_maqsam.isAgentEnabled = agentEnabled;
	window.gain_maqsam.agentEnabled = agentEnabled();

	function updateAvailabilityUi() {
		if (!elements) return;
		const enabled = agentEnabled();
		const open = !elements.win.classList.contains("hidden");
		elements.fab.classList.toggle("enabled", enabled);
		elements.fab.classList.toggle("inactive", !enabled);
		if (!enabled) {
			elements.fab.title = __("Activate Maqsam Agent");
		} else if (open) {
			elements.fab.title = __("Hide Maqsam Dialer");
		} else {
			elements.fab.title = __("Show Maqsam Dialer");
		}
	}

	function injectStyles() {
		if (document.getElementById("mfd-styles")) return;
		const style = document.createElement("style");
		style.id = "mfd-styles";
		style.textContent = `
			.mfd-fab { position: fixed; bottom: 24px; inset-inline-end: 24px; z-index: 1052; width: 52px; height: 52px; border-radius: 50%; border: none; background: #0f766e; color: #fff; box-shadow: 0 8px 22px rgba(15, 118, 110, .35); cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 22px; transition: transform .2s, box-shadow .2s, background .2s, inset-inline-end .25s ease, inset-inline-start .25s ease; }
			.mfd-fab.beside-drawer { inset-inline-end: auto; inset-inline-start: 24px; }
			.mfd-fab:hover { transform: scale(1.06); box-shadow: 0 12px 28px rgba(15, 118, 110, .45); }
			.mfd-fab.inactive { background: #64748b; box-shadow: 0 8px 22px rgba(100, 116, 139, .28); }
			.mfd-fab.enabled { background: #0f766e; }
			.mfd-fab.active { background: #115e59; }
			.mfd-fab.busy { background: #dc2626; animation: mfd-pulse 1.2s infinite; box-shadow: 0 8px 22px rgba(220, 38, 38, .45); }
			.mfd-fab.hidden { display: none !important; }
			@keyframes mfd-pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.08); } }
			.mfd-window { position: fixed; bottom: 90px; inset-inline-end: 24px; width: 380px; height: 560px; max-width: calc(100vw - 32px); max-height: calc(100vh - 130px); background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; box-shadow: 0 24px 48px rgba(15,23,42,.18), 0 4px 12px rgba(15,23,42,.08); z-index: 1051; display: flex; flex-direction: column; overflow: hidden; transition: inset-inline-end .25s ease, inset-inline-start .25s ease, opacity .16s ease, transform .16s ease; }
			.mfd-window.hidden { opacity: 0; pointer-events: none; transform: translateY(8px) scale(.98); }
			.mfd-window.beside-drawer { inset-inline-end: auto; inset-inline-start: 24px; }
			.mfd-header { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border-bottom: 1px solid #f1f5f9; background: #fafbfc; cursor: move; user-select: none; }
			.mfd-title { font-weight: 700; font-size: 13px; color: #0f172a; display: flex; align-items: center; gap: 8px; min-width: 0; }
			.mfd-status-dot { width: 8px; height: 8px; border-radius: 50%; background: #94a3b8; flex-shrink: 0; }
			.mfd-status-dot.ready { background: #16a34a; }
			.mfd-status-dot.error { background: #ef4444; }
			.mfd-status-dot.busy { background: #f59e0b; }
			.mfd-agent-status { font-size: 11px; color: #64748b; font-weight: 500; }
			.mfd-actions { display: flex; gap: 4px; flex-shrink: 0; }
			.mfd-btn { border: 0; background: transparent; padding: 4px 8px; border-radius: 6px; cursor: pointer; color: #64748b; font-size: 14px; }
			.mfd-btn:hover { background: #f1f5f9; color: #0f172a; }
			.mfd-btn:disabled { opacity: .35; cursor: not-allowed; background: transparent; }
			.mfd-profile-btn { display: inline-flex; align-items: center; justify-content: center; min-width: 34px; font-weight: 700; }
			.mfd-window.call-active [data-close] { color: #dc2626; background: #fee2e2; }
			.mfd-frame { flex: 1; width: 100%; border: 0; background: #f8fafc; }
			.mfd-blocker { display: none; flex-direction: column; align-items: center; justify-content: center; padding: 24px; text-align: center; color: #475569; gap: 10px; flex: 1; }
			.mfd-blocker.show { display: flex; }
			.mfd-blocker h4 { margin: 0; color: #0f172a; font-size: 14px; }
			.mfd-blocker p { font-size: 12px; margin: 0; }
			@media (max-width: ${MOBILE_BREAKPOINT}px) {
				.mfd-window:not(.hidden) { inset: 60px 8px 8px 8px !important; width: auto !important; height: auto !important; max-width: none; max-height: none; }
			}
		`;
		document.head.appendChild(style);
	}

	async function fetchAutologinUrl(force = false) {
		const now = Date.now();
		if (!force && cachedUrl && now - urlFetchedAt < URL_TTL_MS) {
			return cachedUrl;
		}
		// Maqsam autologin tokens are short-lived. Keep only a tiny in-memory cache
		// to collapse duplicate clicks, never to survive a real reload/reopen flow.
		const response = await frappe.xcall("gain_maqsam_integration.api.maqsam_get_autologin_url", {
			continue_path: "/phone/dialer",
		});
		cachedUrl = response?.url || "";
		urlFetchedAt = Date.now();
		return cachedUrl;
	}

	function frameNeedsFreshLogin() {
		return !elements?.frame?.src;
	}

	async function fetchAgentStatus() {
		try {
			const response = await frappe.xcall("gain_maqsam_integration.api.maqsam_get_agent_status");
			return response || {};
		} catch (_) {
			return { found: false };
		}
	}

	function persistPosition(node) {
		try {
			const rect = node.getBoundingClientRect();
			localStorage.setItem(STORAGE_KEY, JSON.stringify({ left: rect.left, top: rect.top }));
		} catch (_) {}
	}

	function restorePosition(node) {
		try {
			const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
			if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
				node.style.left = `${Math.max(0, Math.min(window.innerWidth - 100, saved.left))}px`;
				node.style.top = `${Math.max(0, Math.min(window.innerHeight - 100, saved.top))}px`;
				node.style.right = "auto";
				node.style.bottom = "auto";
			}
		} catch (_) {}
	}

	function makeDraggable(node, handle) {
		let dragging = false;
		let startX = 0, startY = 0, startLeft = 0, startTop = 0;
		handle.addEventListener("mousedown", (event) => {
			if (event.target.closest(".mfd-actions")) return;
			if (window.innerWidth <= MOBILE_BREAKPOINT) return; // disable drag on mobile
			dragging = true;
			const rect = node.getBoundingClientRect();
			startX = event.clientX;
			startY = event.clientY;
			startLeft = rect.left;
			startTop = rect.top;
			node.style.left = `${startLeft}px`;
			node.style.top = `${startTop}px`;
			node.style.right = "auto";
			node.style.bottom = "auto";
			document.body.style.userSelect = "none";
		});
		document.addEventListener("mousemove", (event) => {
			if (!dragging) return;
			node.style.left = `${startLeft + event.clientX - startX}px`;
			node.style.top = `${startTop + event.clientY - startY}px`;
		});
		document.addEventListener("mouseup", () => {
			if (!dragging) return;
			dragging = false;
			document.body.style.userSelect = "";
			persistPosition(node);
		});
	}

	function hiddenForRoute() {
		const route = (frappe.get_route?.() || [])[0] || "";
		return HIDDEN_ROUTES.has(route);
	}

	function applyRouteVisibility() {
		if (!elements) return;
		const hide = hiddenForRoute();
		elements.fab.classList.toggle("hidden", hide);
		if (hide) {
			elements.win.classList.add("hidden");
			elements.fab.classList.remove("active");
		}
	}

	function moveDialerBesideDrawer() {
		if (!elements) return;
		if (!drawerSavedPosition) {
			drawerSavedPosition = {
				left: elements.win.style.left,
				top: elements.win.style.top,
				right: elements.win.style.right,
				bottom: elements.win.style.bottom,
			};
		}

		elements.win.style.left = "";
		elements.win.style.top = "";
		elements.win.style.right = "";
		elements.win.style.bottom = "";
		elements.win.classList.add("beside-drawer");
		elements.fab.classList.add("beside-drawer");
	}

	function restoreDialerAfterDrawer() {
		if (!elements) return;
		elements.win.classList.remove("beside-drawer");
		elements.fab.classList.remove("beside-drawer");
		if (drawerSavedPosition) {
			elements.win.style.left = drawerSavedPosition.left;
			elements.win.style.top = drawerSavedPosition.top;
			elements.win.style.right = drawerSavedPosition.right;
			elements.win.style.bottom = drawerSavedPosition.bottom;
			drawerSavedPosition = null;
		}
	}

	function watchCallerDrawer() {
		if (drawerObserver) return;
		drawerObserver = new MutationObserver(() => {
			if (!elements) return;
			const drawerOpen = !!document.querySelector(".m360-drawer:not(.closing)");
			if (drawerOpen) {
				// Keep both the FAB and dialer window on the opposite side while
				// the incoming-call drawer is open so nothing sits underneath it.
				moveDialerBesideDrawer();
				if (elements.win.classList.contains("hidden") && !hiddenForRoute()) {
					api.open().then(moveDialerBesideDrawer);
				}
			} else {
				restoreDialerAfterDrawer();
			}
		});
		drawerObserver.observe(document.body, { childList: true, subtree: false });
	}

	function setStatus(state) {
		if (!elements) return;
		elements.dot.classList.remove("ready", "error", "busy");
		if (state) elements.dot.classList.add(state);
	}

	function setAgentStatusLabel(status) {
		if (!elements) return;
		const label = elements.agentLabel;
		if (!status || !status.found) {
			label.textContent = __("Status unknown");
			return;
		}
		if (status.can_make_outbound_calls) {
			label.textContent = __("Online");
		} else if (status.message) {
			label.textContent = status.message;
		} else {
			label.textContent = __("Offline");
		}
	}


	function updateProfileButton() {
		if (!elements?.profileBtn) return;
		const hasCurrentCall = Boolean(activeCallContext?.callLog || activeCallContext?.phone || busyCallId);
		elements.profileBtn.disabled = false;
		elements.profileBtn.title = hasCurrentCall
			? __("Show current caller profile")
			: __("Find current caller profile");
	}

	async function fetchCurrentCallContext() {
		try {
			return await frappe.xcall("gain_maqsam_integration.api.maqsam_get_current_call_profile");
		} catch (_) {
			return null;
		}
	}

	function rememberCallContext(event) {
		if (!event?.call_log && !event?.phone && !event?.profile) return;
		activeCallContext = {
			callLog: event.call_log || activeCallContext?.callLog || busyCallId || "",
			maqsamCallId: event.maqsam_call_id || activeCallContext?.maqsamCallId || "",
			phone: event.phone || event.profile?.profile_summary?.input_phone || activeCallContext?.phone || "",
			state: event.state || activeCallContext?.state || "ringing",
			profile: event.profile || activeCallContext?.profile || null,
		};
		updateProfileButton();
	}

	function buildCurrentCallLiteProfile(ctx) {
		return {
			profile_summary: {
				input_phone: ctx?.phone || "",
				display_name: __("Looking up caller..."),
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

	async function showCurrentCallerProfile() {
		const caller360 = window.gain_maqsam?.caller360;
		if (!caller360?.showDrawer) {
			frappe.show_alert({ message: __("Caller profile is still loading."), indicator: "orange" });
			return;
		}

		let ctx = activeCallContext || { callLog: busyCallId, state: "ringing" };
		if (!ctx.callLog && !ctx.phone && !ctx.profile) {
			if (elements?.profileBtn) elements.profileBtn.disabled = true;
			const current = await fetchCurrentCallContext();
			if (elements?.profileBtn) elements.profileBtn.disabled = false;
			if (current?.call_log || current?.phone || current?.profile) {
				rememberCallContext(current);
				ctx = activeCallContext || {
					callLog: current.call_log || busyCallId || "",
					maqsamCallId: current.maqsam_call_id || "",
					phone: current.phone || "",
					state: current.state || "ringing",
					profile: current.profile || null,
				};
			}
		}

		if (!ctx.callLog && !ctx.phone && !ctx.profile) {
			frappe.show_alert({ message: __("No current Maqsam call was found yet."), indicator: "orange" });
			return;
		}

		let profile = ctx.profile;
		if (!profile && ctx.callLog && !ctx.phone) {
			try {
				profile = await caller360.fetchProfile?.({ call_log: ctx.callLog });
			} catch (_) {
				profile = null;
			}
		}

		caller360.showDrawer(profile || buildCurrentCallLiteProfile(ctx), {
			callLog: ctx.callLog || busyCallId,
			maqsamCallId: ctx.maqsamCallId,
			state: ctx.state || "ringing",
			lite: !profile,
			phone: ctx.phone || profile?.profile_summary?.input_phone || "",
		});
	}

	async function loadFrame(force = true) {
		if (!elements) return;
		setStatus("");
		elements.blocker.classList.remove("show");
		elements.frame.style.display = "";
		try {
			const url = await fetchAutologinUrl(force);
			if (!url) throw new Error("missing url");
			const blockTimer = setTimeout(() => {
				elements.blocker.classList.add("show");
				elements.frame.style.display = "none";
				setStatus("error");
			}, 6000);
			elements.frame.onload = () => {
				clearTimeout(blockTimer);
				frameLoadedAt = Date.now();
				setStatus("ready");
			};
			frameLoadedAt = Date.now();
			elements.frame.src = url;
		} catch (_) {
			elements.blocker.classList.add("show");
			elements.frame.style.display = "none";
			setStatus("error");
		}
	}

	function startStatusPoll() {
		if (agentStatusTimer) return;
		const tick = async () => {
			const status = await fetchAgentStatus();
			setAgentStatusLabel(status);
		};
		tick();
		agentStatusTimer = setInterval(tick, STATUS_POLL_MS);
	}

	function stopStatusPoll() {
		if (!agentStatusTimer) return;
		clearInterval(agentStatusTimer);
		agentStatusTimer = null;
	}

	const api = {
		isOpen() {
			return !!(elements && !elements.win.classList.contains("hidden"));
		},

		async open({ allowHiddenRoute = false, markEnabled = true } = {}) {
			if (!elements) return;
			if (markEnabled) setAgentEnabled(true);
			if (hiddenForRoute() && !allowHiddenRoute) {
				return;
			}
			if (!api.isOpen()) {
				setPanelVisible(true);
				if (frameNeedsFreshLogin()) await loadFrame(true);
				if (!elements.win.classList.contains("beside-drawer")) {
					restorePosition(elements.win);
				}
				startStatusPoll();
				updateAvailabilityUi();
			}
		},

		async close({ deactivate = false, force = false } = {}) {
			if (!elements) return;
			if (busyCallId && !force) {
				// The busy flag may be stale (call ended but webhook missed,
				// or drawer was closed before terminal state). Confirm with
				// the backend before nagging the user.
				const stillActive = await _isCallStillActive(busyCallId);
				if (stillActive) {
					setPanelVisible(true);
					const now = Date.now();
					if (now - busyMessageShownAt > 3000) {
						busyMessageShownAt = now;
						_showBusyConfirmDialog(deactivate);
					}
					return;
				}
				// Call already ended — clear stale busy and continue closing.
				api.clearBusy(busyCallId);
			}
			setPanelVisible(false);
			if (deactivate || !agentEnabled()) {
				stopStatusPoll();
			}
			if (deactivate) {
				setAgentEnabled(false);
				busyCallId = null;
				activeCallContext = null;
				elements.fab.classList.remove("busy");
				cachedUrl = "";
				urlFetchedAt = 0;
				frameLoadedAt = 0;
				elements.frame.removeAttribute("src");
			} else {
				updateAvailabilityUi();
			}
		},

		async ensureSession({ force = false } = {}) {
			if (!elements) return;
			setAgentEnabled(true);
			if (force || frameNeedsFreshLogin()) await loadFrame(true);
			startStatusPoll();
			updateAvailabilityUi();
		},

		async activate({ silent = false } = {}) {
			await api.open({ markEnabled: true });
			if (!silent) {
				frappe.show_alert({ message: __("Maqsam agent mode is active. Keep your Maqsam status Online/Available inside the dialer."), indicator: "green" });
			}
		},

		deactivate({ silent = false } = {}) {
			api.close({ deactivate: true });
			if (!silent) {
				frappe.show_alert({ message: __("Maqsam agent mode is inactive."), indicator: "orange" });
			}
		},

		toggleAvailability() {
			return agentEnabled() ? api.deactivate() : api.activate();
		},

		togglePanel() {
			if (!agentEnabled()) {
				return api.activate();
			}
			return api.isOpen() ? api.close() : api.open({ markEnabled: false });
		},

		toggle() {
			api.togglePanel();
		},

		isEnabled() {
			return agentEnabled();
		},

		setBusy(callId) {
			if (!elements) return;
			busyCallId = callId || null;
			if (busyCallId) {
				activeCallContext = { ...(activeCallContext || {}), callLog: busyCallId };
			}
			elements.fab.classList.toggle("busy", !!busyCallId);
			elements.win.classList.toggle("call-active", !!busyCallId);
			const closeBtn = elements.win.querySelector("[data-close]");
			if (closeBtn) {
				closeBtn.title = busyCallId ? __("End the call in Maqsam first") : __("Hide Dialer");
			}
			if (busyCallId) {
				setStatus("busy");
				elements.agentLabel.textContent = __("Active call - use Maqsam hangup");
			}
			updateProfileButton();
		},

		clearBusy(callId) {
			if (!elements) return;
			if (callId && busyCallId && callId !== busyCallId) return;
			busyCallId = null;
			activeCallContext = null;
			elements.fab.classList.remove("busy");
			elements.win.classList.remove("call-active");
			const closeBtn = elements.win.querySelector("[data-close]");
			if (closeBtn) closeBtn.title = __("Hide Dialer");
			setStatus("ready");
			updateProfileButton();
		},

		async getAutologinUrl(force = true) {
			return fetchAutologinUrl(force);
		},
	};

	const TERMINAL_CALL_STATES = new Set([
		"ended",
		"completed",
		"answered",
		"serviced",
		"abandoned",
		"dropped",
		"no_answer",
		"busy",
		"failed",
	]);

	// Maqsam agent states that mean the agent is currently in a call.
	// Anything outside this set (available, away, offline, idle, …) means
	// no call is in progress, regardless of what the call log says.
	const IN_CALL_AGENT_STATES = new Set([
		"in_call",
		"on_call",
		"oncall",
		"busy",
		"ringing",
		"talking",
	]);

	async function _isCallStillActive(callLog) {
		// Two sources of truth:
		//  1. Agent status in Maqsam (most reliable — reflects WebRTC reality)
		//  2. Call log state (may lag if `ended` webhook is missed/late)
		// The agent status wins: if Maqsam itself says the agent is available,
		// they cannot be in a call regardless of what the call log persists.
		if (!callLog) return false;

		// 1) Agent status check — fast and authoritative.
		try {
			const status = await fetchAgentStatus();
			const agentState = String(status?.state || "").toLowerCase().replace(/[\s-]/g, "_");
			if (agentState && !IN_CALL_AGENT_STATES.has(agentState)) {
				return false;
			}
		} catch (_) {
			// Fall through to call-log check
		}

		// 2) Call log state check (and force-refresh from Maqsam's recent
		// calls list to catch a missed `ended` webhook). Use callback-style
		// so server errors stay silent — surfacing "Not found" while the
		// agent is just trying to close a panel would be terrible UX.
		const response = await new Promise((resolve) => {
			frappe.call({
				method: "gain_maqsam_integration.api.maqsam_refresh_call_state",
				args: { call_log: callLog },
				freeze: false,
				callback: (r) => resolve(r),
				error: () => resolve(null),
			});
		});
		try {
			const state = String(response?.message?.state || "").toLowerCase().replace(/[\s-]/g, "_");
			if (!state) return false;
			return !TERMINAL_CALL_STATES.has(state);
		} catch (_) {
			// On error, prefer "not active" so we don't trap the user behind
			// a stale busy flag. They can always re-open via the FAB.
			return false;
		}
	}

	function _showBusyConfirmDialog(deactivate) {
		// Soft confirmation instead of a hard "no": if the agent insists the
		// call has ended, let them release the busy lock and close.
		const dialog = new frappe.ui.Dialog({
			title: __("Hide Dialer?"),
			fields: [
				{
					fieldtype: "HTML",
					options: `
						<div style="line-height:1.7; font-size:13px;">
							<p>${__("Maqsam still reports an active call for this session.")}</p>
							<p style="color:#64748b;">${__("If you have already ended the call inside Maqsam, you can hide the dialer anyway.")}</p>
						</div>
					`,
				},
			],
			primary_action_label: __("Hide Anyway"),
			primary_action: () => {
				dialog.hide();
				api.clearBusy(busyCallId);
				api.close({ deactivate, force: true });
			},
			secondary_action_label: __("Keep Open"),
			secondary_action: () => dialog.hide(),
		});
		dialog.show();
	}

	function _registerCallStateRealtime() {
		// Backstop for the busy flag: when ANY incoming-call event for the
		// current busy call hits a terminal state, release the lock — even
		// if the Caller 360 drawer is already closed and `setAfterCallMode`
		// is no longer wired up to handle it.
		if (!frappe.realtime?.on || _registerCallStateRealtime._wired) return;
		_registerCallStateRealtime._wired = true;
		frappe.realtime.on("maqsam_incoming_call", (event) => {
			const callLog = event?.call_log;
			const state = String(event?.state || "").toLowerCase().replace(/[\s-]/g, "_");
			if (callLog && !TERMINAL_CALL_STATES.has(state)) {
				rememberCallContext(event);
				api.setBusy(callLog);
			}
			if (!callLog || !busyCallId || callLog !== busyCallId) return;
			if (TERMINAL_CALL_STATES.has(state)) {
				api.clearBusy(callLog);
			}
		});
	}

	function buildUI() {
		injectStyles();

		const fab = document.createElement("button");
		fab.className = "mfd-fab";
		fab.title = __("Maqsam Dialer (Alt+D)");
		fab.innerHTML = "📞";
		document.body.appendChild(fab);

		const win = document.createElement("div");
		win.className = "mfd-window hidden";
		win.innerHTML = `
			<div class="mfd-header" data-drag>
				<div class="mfd-title">
					<span class="mfd-status-dot" data-dot></span>
					<span>${__("Maqsam")}</span>
					<span class="mfd-agent-status" data-agent-status>${__("Connecting…")}</span>
				</div>
				<div class="mfd-actions">
					<button class="mfd-btn mfd-profile-btn" data-profile title="${__("Show current caller profile")}">360</button>
					<button class="mfd-btn" data-reload title="${__("Reload")}">↻</button>
					<button class="mfd-btn" data-popout title="${__("Open in new tab")}">⤴</button>
					<button class="mfd-btn" data-close title="${__("Hide Dialer")}">✕</button>
				</div>
			</div>
			<iframe class="mfd-frame" data-frame allow="microphone; camera; autoplay" referrerpolicy="strict-origin-when-cross-origin"></iframe>
			<div class="mfd-blocker" data-blocker>
				<h4>${__("Maqsam blocked the embedded view")}</h4>
				<p>${__("Click below to open the dialer in a new tab — your session signs in automatically.")}</p>
				<button class="btn btn-primary btn-sm" data-popout-fallback>${__("Open Dialer")}</button>
			</div>
		`;
		document.body.appendChild(win);

		elements = {
			fab,
			win,
			frame: win.querySelector("[data-frame]"),
			blocker: win.querySelector("[data-blocker]"),
			dot: win.querySelector("[data-dot]"),
			agentLabel: win.querySelector("[data-agent-status]"),
			profileBtn: win.querySelector("[data-profile]"),
		};

		fab.addEventListener("click", api.togglePanel);
		win.querySelector("[data-close]").addEventListener("click", () => api.close());
		win.querySelector("[data-profile]").addEventListener("click", showCurrentCallerProfile);
		win.querySelector("[data-reload]").addEventListener("click", () => loadFrame(true));
		win.querySelectorAll("[data-popout], [data-popout-fallback]").forEach((btn) => {
			btn.addEventListener("click", async () => {
				const url = await fetchAutologinUrl(true);
				if (url) window.open(url, "_blank", "noopener,noreferrer");
			});
		});

		makeDraggable(win, win.querySelector("[data-drag]"));

		document.addEventListener("keydown", (event) => {
			if (event.altKey && (event.key === "d" || event.key === "D")) {
				event.preventDefault();
				api.togglePanel();
			}
		});

		applyRouteVisibility();
		frappe.router?.on?.("change", applyRouteVisibility);
		updateAvailabilityUi();
		updateProfileButton();
		watchCallerDrawer();
	}

	function init() {
		if (!frappe?.user_roles) return;
		if (!userIsAgent()) return;
		if (document.querySelector(".mfd-fab")) return;
		buildUI();
		Object.assign(gain_maqsam.dialer, api);
		_registerCallStateRealtime();
		// Re-attach if the realtime socket connects after init (slow networks).
		if (!frappe.realtime?.socket) {
			const interval = setInterval(() => {
				if (frappe.realtime?.on) {
					_registerCallStateRealtime();
					clearInterval(interval);
				}
			}, 500);
			setTimeout(() => clearInterval(interval), 30000);
		}
		window.dispatchEvent(new CustomEvent("maqsam_agent_availability_changed", { detail: { enabled: agentEnabled() } }));
		if (agentEnabled() && !hiddenForRoute()) {
			const resume = () => {
				if (panelShouldBeVisible()) {
					api.activate({ silent: true });
				} else {
					api.ensureSession({ force: true });
				}
			};
			setTimeout(resume, 150);
		}
	}

	$(document).on("app_ready", init);
	$(window).on("load", init);
	if (frappe?.user_roles) init();
})();
