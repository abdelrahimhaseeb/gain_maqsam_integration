// Maqsam Dialer — embeds the Maqsam portal inside the desk via the
// /v2/token autologin URL so the agent doesn't have to open a separate tab.
//
// Note: Maqsam may set X-Frame-Options: DENY on the portal. When that
// happens, the iframe stays blank and we surface a "Open in new tab" fallback.

frappe.pages["maqsam-dialer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Maqsam Dialer"),
		single_column: true,
	});

	const $body = $(page.body);
	$body.addClass("maqsam-dialer-page");

	$body.html(`
		<style>
			.maqsam-dialer-page { padding: 0 !important; }
			.maqsam-dialer-shell { display: flex; flex-direction: column; height: calc(100vh - 160px); border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden; background: #fff; box-shadow: 0 4px 12px rgba(15,23,42,.04); }
			.maqsam-dialer-toolbar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid #f1f5f9; background: #fafbfc; font-size: 12px; color: #475569; }
			.maqsam-dialer-toolbar .status { display: inline-flex; align-items: center; gap: 6px; }
			.maqsam-dialer-toolbar .status .dot { width: 8px; height: 8px; border-radius: 50%; background: #94a3b8; }
			.maqsam-dialer-toolbar .status.ready .dot { background: #16a34a; }
			.maqsam-dialer-toolbar .status.error .dot { background: #ef4444; }
			.maqsam-dialer-toolbar .spacer { flex: 1; }
			.maqsam-dialer-frame { flex: 1; width: 100%; border: 0; background: #f8fafc; }
			.maqsam-dialer-blocker { display: none; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 32px; text-align: center; color: #475569; }
			.maqsam-dialer-blocker h3 { margin: 0; color: #0f172a; }
			.maqsam-dialer-shell.blocked .maqsam-dialer-frame { display: none; }
			.maqsam-dialer-shell.blocked .maqsam-dialer-blocker { display: flex; }
		</style>
		<div class="maqsam-dialer-shell" data-shell>
			<div class="maqsam-dialer-toolbar">
				<span class="status loading" data-status>
					<span class="dot"></span>
					<span class="label">${__("Connecting…")}</span>
				</span>
				<span class="spacer"></span>
				<button class="btn btn-xs btn-default" data-reload>${__("Reload")}</button>
				<button class="btn btn-xs btn-default" data-popout>${__("Open in new tab")}</button>
			</div>
			<iframe class="maqsam-dialer-frame" data-frame allow="microphone; camera; autoplay" referrerpolicy="strict-origin-when-cross-origin"></iframe>
			<div class="maqsam-dialer-blocker" data-blocker>
				<h3>${__("Maqsam blocked the embedded view")}</h3>
				<p>${__("Maqsam's portal does not allow embedding in another page. Click below to open the dialer in a new tab — your session is signed in automatically.")}</p>
				<button class="btn btn-primary" data-popout-fallback>${__("Open Maqsam Dialer")}</button>
			</div>
		</div>
	`);

	const $shell = $body.find("[data-shell]");
	const $frame = $body.find("[data-frame]");
	const $status = $body.find("[data-status]");
	const $statusLabel = $status.find(".label");
	let currentUrl = "";

	function setStatus(state, label) {
		$status.removeClass("loading ready error").addClass(state);
		$statusLabel.text(label);
	}

	async function load() {
		setStatus("loading", __("Connecting…"));
		$shell.removeClass("blocked");
		try {
			const response = await frappe.xcall("gain_maqsam_integration.api.maqsam_get_autologin_url");
			currentUrl = response?.url || "";
			if (!currentUrl) throw new Error(__("Maqsam did not return an autologin URL."));
			$frame.attr("src", currentUrl);
			// Watch for X-Frame-Options blocking: if the iframe never reaches
			// a 'load' state in 6s, treat as blocked.
			const blockTimer = setTimeout(() => {
				$shell.addClass("blocked");
				setStatus("error", __("Embedded view blocked"));
			}, 6000);
			$frame.one("load", () => {
				clearTimeout(blockTimer);
				setStatus("ready", __("Connected"));
			});
		} catch (error) {
			setStatus("error", error.message || __("Could not load dialer"));
			$shell.addClass("blocked");
		}
	}

	function popout() {
		if (currentUrl) {
			window.open(currentUrl, "_blank", "noopener,noreferrer");
		} else {
			load().then(() => currentUrl && window.open(currentUrl, "_blank", "noopener,noreferrer"));
		}
	}

	$body.on("click", "[data-reload]", load);
	$body.on("click", "[data-popout], [data-popout-fallback]", popout);

	load();
};
