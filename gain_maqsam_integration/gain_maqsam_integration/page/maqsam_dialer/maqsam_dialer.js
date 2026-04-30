// /app/maqsam-dialer is no longer a real standalone page. It exists purely so
// shortcuts and workspace links can target it: when Frappe routes here we
// open the embedded floating dialer and bounce the user back to where they
// came from (or the call-center workspace if there is no history).

frappe.pages["maqsam-dialer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Maqsam Dialer"),
		single_column: true,
	});

	$(page.body).html(`
		<div style="display:flex; flex-direction:column; align-items:center; justify-content:center; padding:48px 16px; gap:8px; color:#475569;">
			<div style="font-size:32px;">📞</div>
			<div style="font-weight:600; color:#0f172a;">${__("Opening Maqsam Dialer…")}</div>
			<div style="font-size:12px;">${__("The dialer floats in the corner — no separate page to manage.")}</div>
		</div>
	`);
};

frappe.pages["maqsam-dialer"].on_page_show = function () {
	const previous = frappe.get_prev_route?.() || [];
	const tryOpenAndLeave = () => {
		const dialer = window.gain_maqsam?.dialer;
		if (!dialer?.open) return false;
		dialer.open();
		// Land back where the user was; fall back to the workspace.
		const target = previous.length ? previous : ["workspace", "Maqsam Call Center"];
		setTimeout(() => frappe.set_route(...target), 50);
		return true;
	};

	if (tryOpenAndLeave()) return;
	let attempts = 0;
	const interval = setInterval(() => {
		attempts += 1;
		if (tryOpenAndLeave() || attempts > 30) clearInterval(interval);
	}, 100);
};
