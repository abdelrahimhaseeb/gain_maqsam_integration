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
	const URL_TTL_MS = 25 * 60 * 1000;
	const STATUS_POLL_MS = 30 * 1000;
	const MOBILE_BREAKPOINT = 600;
	// /app/maqsam-dialer renders the same iframe full-screen — don't double up.
	const HIDDEN_ROUTES = new Set(["maqsam-dialer"]);

	let cachedUrl = "";
	let urlFetchedAt = 0;
	let agentStatusTimer = null;
	let drawerObserver = null;
	let busyCallId = null;
	let elements = null;

	frappe.provide("gain_maqsam.dialer");

	function userIsAgent() {
		const roles = frappe.user_roles || [];
		return REQUIRED_ROLES.some((role) => roles.includes(role));
	}

	function injectStyles() {
		if (document.getElementById("mfd-styles")) return;
		const style = document.createElement("style");
		style.id = "mfd-styles";
		style.textContent = `
			.mfd-fab { position: fixed; bottom: 24px; inset-inline-end: 24px; z-index: 1040; width: 52px; height: 52px; border-radius: 50%; border: none; background: #0f766e; color: #fff; box-shadow: 0 8px 22px rgba(15, 118, 110, .35); cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 22px; transition: transform .2s, box-shadow .2s, background .2s; }
			.mfd-fab:hover { transform: scale(1.06); box-shadow: 0 12px 28px rgba(15, 118, 110, .45); }
			.mfd-fab.active { background: #115e59; }
			.mfd-fab.busy { background: #dc2626; animation: mfd-pulse 1.2s infinite; box-shadow: 0 8px 22px rgba(220, 38, 38, .45); }
			.mfd-fab.hidden { display: none !important; }
			@keyframes mfd-pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.08); } }
			.mfd-window { position: fixed; bottom: 90px; inset-inline-end: 24px; width: 380px; height: 560px; max-width: calc(100vw - 32px); max-height: calc(100vh - 130px); background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; box-shadow: 0 24px 48px rgba(15,23,42,.18), 0 4px 12px rgba(15,23,42,.08); z-index: 1041; display: flex; flex-direction: column; overflow: hidden; }
			.mfd-window.hidden { display: none; }
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
		// Land directly on Maqsam's phone dialer view, not the default
		// account dashboard / call history.
		const response = await frappe.xcall("gain_maqsam_integration.api.maqsam_get_autologin_url", {
			continue_path: "/phone/dialer",
		});
		cachedUrl = response?.url || "";
		urlFetchedAt = now;
		return cachedUrl;
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

	function watchCallerDrawer() {
		if (drawerObserver) return;
		drawerObserver = new MutationObserver(() => {
			if (!elements) return;
			const drawerOpen = !!document.querySelector(".m360-drawer:not(.closing)");
			if (drawerOpen && !elements.win.classList.contains("hidden")) {
				// Drawer just opened — collapse mini-window so they don't overlap.
				api.close();
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

	async function loadFrame(force = false) {
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
				setStatus("ready");
			};
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

		async open() {
			if (!elements) return;
			if (hiddenForRoute()) {
				// Already on the dedicated dialer page — nothing to do.
				return;
			}
			if (!api.isOpen()) {
				elements.win.classList.remove("hidden");
				elements.fab.classList.add("active");
				if (!elements.frame.src) await loadFrame();
				restorePosition(elements.win);
				startStatusPoll();
			}
		},

		close() {
			if (!elements) return;
			elements.win.classList.add("hidden");
			elements.fab.classList.remove("active");
			stopStatusPoll();
		},

		toggle() {
			if (api.isOpen()) api.close(); else api.open();
		},

		setBusy(callId) {
			if (!elements) return;
			busyCallId = callId || null;
			elements.fab.classList.toggle("busy", !!busyCallId);
		},

		clearBusy(callId) {
			if (!elements) return;
			if (callId && busyCallId && callId !== busyCallId) return;
			busyCallId = null;
			elements.fab.classList.remove("busy");
		},

		async getAutologinUrl(force = false) {
			return fetchAutologinUrl(force);
		},
	};

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
					<button class="mfd-btn" data-reload title="${__("Reload")}">↻</button>
					<button class="mfd-btn" data-popout title="${__("Open in new tab")}">⤴</button>
					<button class="mfd-btn" data-close title="${__("Close (Alt+D)")}">✕</button>
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
		};

		fab.addEventListener("click", api.toggle);
		win.querySelector("[data-close]").addEventListener("click", api.close);
		win.querySelector("[data-reload]").addEventListener("click", () => loadFrame(true));
		win.querySelectorAll("[data-popout], [data-popout-fallback]").forEach((btn) => {
			btn.addEventListener("click", async () => {
				const url = await fetchAutologinUrl();
				if (url) window.open(url, "_blank", "noopener,noreferrer");
			});
		});

		makeDraggable(win, win.querySelector("[data-drag]"));

		document.addEventListener("keydown", (event) => {
			if (event.altKey && (event.key === "d" || event.key === "D")) {
				event.preventDefault();
				api.toggle();
			}
		});

		applyRouteVisibility();
		frappe.router?.on?.("change", applyRouteVisibility);
		watchCallerDrawer();
	}

	function init() {
		if (!frappe?.user_roles) return;
		if (!userIsAgent()) return;
		if (document.querySelector(".mfd-fab")) return;
		buildUI();
		Object.assign(gain_maqsam.dialer, api);
	}

	$(document).on("app_ready", init);
	$(window).on("load", init);
	if (frappe?.user_roles) init();
})();
