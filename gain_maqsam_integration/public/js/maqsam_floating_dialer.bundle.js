// Floating Maqsam mini-dialer button.
// Shows a small phone icon in the bottom-right corner of the desk that
// expands into a draggable mini-window with the Maqsam portal embedded.
// Skips itself for users who don't have the Maqsam Agent role.

(() => {
	const REQUIRED_ROLES = ["Maqsam Agent", "System Manager"];
	const STORAGE_KEY = "gain_maqsam_floating_position";
	let cachedUrl = "";
	let urlFetchedAt = 0;
	const URL_TTL_MS = 25 * 60 * 1000; // tokens are short-lived; refresh every ~25 min

	function userIsAgent() {
		const roles = frappe.user_roles || [];
		return REQUIRED_ROLES.some((role) => roles.includes(role));
	}

	function injectStyles() {
		if (document.getElementById("mfd-styles")) return;
		const style = document.createElement("style");
		style.id = "mfd-styles";
		style.textContent = `
			.mfd-fab { position: fixed; bottom: 24px; inset-inline-end: 24px; z-index: 1040; width: 52px; height: 52px; border-radius: 50%; border: none; background: #0f766e; color: #fff; box-shadow: 0 8px 22px rgba(15, 118, 110, .35); cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 22px; transition: transform .2s, box-shadow .2s; }
			.mfd-fab:hover { transform: scale(1.06); box-shadow: 0 12px 28px rgba(15, 118, 110, .45); }
			.mfd-fab.active { background: #115e59; }
			.mfd-window { position: fixed; bottom: 90px; inset-inline-end: 24px; width: 380px; height: 560px; max-width: calc(100vw - 32px); max-height: calc(100vh - 130px); background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; box-shadow: 0 24px 48px rgba(15,23,42,.18), 0 4px 12px rgba(15,23,42,.08); z-index: 1041; display: flex; flex-direction: column; overflow: hidden; }
			.mfd-window.hidden { display: none; }
			.mfd-header { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border-bottom: 1px solid #f1f5f9; background: #fafbfc; cursor: move; user-select: none; }
			.mfd-title { font-weight: 700; font-size: 13px; color: #0f172a; display: flex; align-items: center; gap: 6px; }
			.mfd-status-dot { width: 8px; height: 8px; border-radius: 50%; background: #94a3b8; }
			.mfd-status-dot.ready { background: #16a34a; }
			.mfd-status-dot.error { background: #ef4444; }
			.mfd-actions { display: flex; gap: 4px; }
			.mfd-btn { border: 0; background: transparent; padding: 4px 8px; border-radius: 6px; cursor: pointer; color: #64748b; font-size: 14px; }
			.mfd-btn:hover { background: #f1f5f9; color: #0f172a; }
			.mfd-frame { flex: 1; width: 100%; border: 0; background: #f8fafc; }
			.mfd-blocker { display: none; flex-direction: column; align-items: center; justify-content: center; padding: 24px; text-align: center; color: #475569; gap: 10px; flex: 1; }
			.mfd-blocker.show { display: flex; }
			.mfd-blocker h4 { margin: 0; color: #0f172a; font-size: 14px; }
			.mfd-blocker p { font-size: 12px; margin: 0; }
		`;
		document.head.appendChild(style);
	}

	async function fetchAutologinUrl(force = false) {
		const now = Date.now();
		if (!force && cachedUrl && now - urlFetchedAt < URL_TTL_MS) {
			return cachedUrl;
		}
		const response = await frappe.xcall("gain_maqsam_integration.api.maqsam_get_autologin_url");
		cachedUrl = response?.url || "";
		urlFetchedAt = now;
		return cachedUrl;
	}

	function persistPosition(window) {
		try {
			const rect = window.getBoundingClientRect();
			localStorage.setItem(
				STORAGE_KEY,
				JSON.stringify({ left: rect.left, top: rect.top }),
			);
		} catch (_) {}
	}

	function restorePosition(window) {
		try {
			const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
			if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
				window.style.left = `${Math.max(0, Math.min(window.parentNode.clientWidth - 100, saved.left))}px`;
				window.style.top = `${Math.max(0, Math.min(window.parentNode.clientHeight - 100, saved.top))}px`;
				window.style.right = "auto";
				window.style.bottom = "auto";
			}
		} catch (_) {}
	}

	function makeDraggable(window, handle) {
		let dragging = false;
		let startX = 0, startY = 0, startLeft = 0, startTop = 0;
		handle.addEventListener("mousedown", (event) => {
			if (event.target.closest(".mfd-actions")) return;
			dragging = true;
			const rect = window.getBoundingClientRect();
			startX = event.clientX;
			startY = event.clientY;
			startLeft = rect.left;
			startTop = rect.top;
			window.style.left = `${startLeft}px`;
			window.style.top = `${startTop}px`;
			window.style.right = "auto";
			window.style.bottom = "auto";
			document.body.style.userSelect = "none";
		});
		document.addEventListener("mousemove", (event) => {
			if (!dragging) return;
			window.style.left = `${startLeft + event.clientX - startX}px`;
			window.style.top = `${startTop + event.clientY - startY}px`;
		});
		document.addEventListener("mouseup", () => {
			if (!dragging) return;
			dragging = false;
			document.body.style.userSelect = "";
			persistPosition(window);
		});
	}

	function buildUI() {
		injectStyles();

		const fab = document.createElement("button");
		fab.className = "mfd-fab";
		fab.title = __("Maqsam Dialer");
		fab.innerHTML = "📞";
		document.body.appendChild(fab);

		const win = document.createElement("div");
		win.className = "mfd-window hidden";
		win.innerHTML = `
			<div class="mfd-header" data-drag>
				<div class="mfd-title">
					<span class="mfd-status-dot" data-dot></span>
					<span>${__("Maqsam Dialer")}</span>
				</div>
				<div class="mfd-actions">
					<button class="mfd-btn" data-reload title="${__("Reload")}">↻</button>
					<button class="mfd-btn" data-popout title="${__("Open in new tab")}">⤴</button>
					<button class="mfd-btn" data-close title="${__("Close")}">✕</button>
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

		const frame = win.querySelector("[data-frame]");
		const blocker = win.querySelector("[data-blocker]");
		const dot = win.querySelector("[data-dot]");

		function setStatus(state) {
			dot.classList.remove("ready", "error");
			if (state) dot.classList.add(state);
		}

		async function loadFrame(force = false) {
			setStatus("");
			blocker.classList.remove("show");
			frame.style.display = "";
			try {
				const url = await fetchAutologinUrl(force);
				if (!url) throw new Error("missing url");
				const blockTimer = setTimeout(() => {
					blocker.classList.add("show");
					frame.style.display = "none";
					setStatus("error");
				}, 6000);
				frame.onload = () => {
					clearTimeout(blockTimer);
					setStatus("ready");
				};
				frame.src = url;
			} catch (_) {
				blocker.classList.add("show");
				frame.style.display = "none";
				setStatus("error");
			}
		}

		fab.addEventListener("click", async () => {
			const isHidden = win.classList.contains("hidden");
			if (isHidden) {
				win.classList.remove("hidden");
				fab.classList.add("active");
				if (!frame.src) await loadFrame();
				restorePosition(win);
			} else {
				win.classList.add("hidden");
				fab.classList.remove("active");
			}
		});

		win.querySelector("[data-close]").addEventListener("click", () => {
			win.classList.add("hidden");
			fab.classList.remove("active");
		});
		win.querySelector("[data-reload]").addEventListener("click", () => loadFrame(true));
		win.querySelectorAll("[data-popout], [data-popout-fallback]").forEach((btn) => {
			btn.addEventListener("click", async () => {
				const url = await fetchAutologinUrl();
				if (url) window.open(url, "_blank", "noopener,noreferrer");
			});
		});

		makeDraggable(win, win.querySelector("[data-drag]"));
	}

	function init() {
		if (!frappe?.user_roles) return;
		if (!userIsAgent()) return;
		if (document.querySelector(".mfd-fab")) return;
		buildUI();
	}

	$(document).on("app_ready", init);
	$(window).on("load", init);
	if (frappe?.user_roles) init();
})();
