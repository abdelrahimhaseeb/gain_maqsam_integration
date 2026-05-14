frappe.ui.form.on("Maqsam WhatsApp Conversation", {
	refresh: function (frm) {
		// 1. Refresh Button
		if (frm.doc.conversation_id) {
			frm.add_custom_button(
				__("Refresh Conversation"),
				() => {
					frappe.call({
						method: "gain_maqsam_integration.maqsam_whatsapp.api.maqsam_whatsapp_get_conversation",
						args: {
							conversation_id: frm.doc.conversation_id,
						},
						freeze: true,
						freeze_message: __("Refreshing Conversation..."),
						callback: (r) => {
							if (!r.exc) {
								frm.reload_doc();
							}
						},
					});
				},
				__("Maqsam")
			);
		}

		// 2. Chat Bubble Rendering
		render_chat_ui(frm);
	},
});

function render_chat_ui(frm) {
	if (!frm.doc.raw_payload) return;

	let payload = {};
	try {
		payload = JSON.parse(frm.doc.raw_payload);
	} catch (e) {
		console.warn("Failed to parse raw_payload for Maqsam WhatsApp Conversation");
		return;
	}

	// Locate messages array
	let messages = [];
	if (Array.isArray(payload)) {
		messages = payload;
	} else if (payload.messages && Array.isArray(payload.messages)) {
		messages = payload.messages;
	} else if (payload.data && Array.isArray(payload.data)) {
		messages = payload.data;
	} else if (payload.items && Array.isArray(payload.items)) {
		messages = payload.items;
	}

	// Ensure we have a wrapper to render into
	let $wrapper;
	if (frm.fields_dict.chat_view && frm.fields_dict.chat_view.$wrapper) {
		$wrapper = frm.fields_dict.chat_view.$wrapper;
	} else {
		// Inject dynamically above raw_payload if chat_view doesn't exist
		if (!frm.fields_dict.raw_payload) return;
		$wrapper = frm.fields_dict.raw_payload.$wrapper.prev(".m360-chat-wrapper");
		if ($wrapper.length === 0) {
			$wrapper = $('<div class="m360-chat-wrapper mb-4"></div>').insertBefore(frm.fields_dict.raw_payload.$wrapper);
		}
		// Hide the raw payload field visually to replace it with our UI
		frm.set_df_property("raw_payload", "hidden", 1);
	}

	$wrapper.empty();

	if (!messages || messages.length === 0) {
		$wrapper.html(`<div class="text-muted text-center p-4 bg-light rounded border">${__("No messages found in conversation payload.")}</div>`);
		return;
	}

	// Sort messages chronologically if possible (assuming they have created_at, sent_at, timestamp, etc)
	messages.sort((a, b) => {
		let tA = new Date(a.created_at || a.timestamp || a.time || 0).getTime();
		let tB = new Date(b.created_at || b.timestamp || b.time || 0).getTime();
		return tA - tB;
	});

	let chat_html = `<div class="d-flex flex-column gap-2 p-3 bg-light rounded border shadow-sm" style="max-height: 500px; overflow-y: auto;">`;

	messages.forEach((msg) => {
		// Determine direction
		let is_outbound = false;
		let direction_str = String(msg.direction || msg.type || msg.status || "").toLowerCase();
		if (direction_str.includes("out") || direction_str === "sent" || direction_str === "delivered" || direction_str === "read") {
			is_outbound = true;
		}

		// Fallback content extraction
		let text = msg.content || msg.text || msg.body || msg.message || "";
		if (typeof text === "object") {
			text = text.body || JSON.stringify(text);
		}

		// Fallback timestamp extraction
        let timestamp_raw = msg.created_at || msg.timestamp || msg.time || "";
        let timestamp = timestamp_raw ? frappe.datetime.global_date_format(timestamp_raw) + " " + frappe.datetime.get_time(timestamp_raw) : "";
        let escaped_timestamp = frappe.utils.escape_html(timestamp);

		if (is_outbound) {
			chat_html += `
				<div class="d-flex justify-content-end mb-2">
					<div class="p-2 rounded shadow-sm" style="background-color: #dcfce7; color: #166534; max-width: 75%; border-bottom-right-radius: 2px;">
						<div style="white-space: pre-wrap; word-wrap: break-word; font-size: 14px;">${frappe.utils.escape_html(text)}</div>
						<div class="text-right text-muted" style="font-size: 10px; margin-top: 4px;">
                            ${escaped_timestamp}
							${msg.status ? `<span class="ml-1 opacity-75">${frappe.utils.escape_html(msg.status)}</span>` : ""}
						</div>
					</div>
				</div>
			`;
		} else {
			chat_html += `
				<div class="d-flex justify-content-start mb-2">
					<div class="p-2 bg-white rounded shadow-sm border" style="color: #1e293b; max-width: 75%; border-bottom-left-radius: 2px;">
						<div style="white-space: pre-wrap; word-wrap: break-word; font-size: 14px;">${frappe.utils.escape_html(text)}</div>
						<div class="text-left text-muted" style="font-size: 10px; margin-top: 4px;">
                            ${escaped_timestamp}
						</div>
					</div>
				</div>
			`;
		}
	});

	chat_html += `</div>`;
	$wrapper.html(chat_html);
}
