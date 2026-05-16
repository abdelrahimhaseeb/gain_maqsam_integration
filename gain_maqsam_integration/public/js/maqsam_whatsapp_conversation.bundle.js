frappe.ui.form.on("Maqsam WhatsApp Conversation", {
	refresh: function (frm) {
		get_chat_wrapper(frm);

		if (!frm.doc.conversation_id) {
			render_chat_ui(frm, []);
			return;
		}

		frm.add_custom_button(
			__("Refresh Conversation"),
			() => load_conversation(frm, { freeze: true }),
			__("Maqsam")
		);

		load_conversation(frm);
	},
});

function load_conversation(frm, opts = {}) {
	if (!frm.doc.conversation_id || frm._maqsam_whatsapp_loading) return;

	frm._maqsam_whatsapp_loading = true;
	if (!frm._maqsam_whatsapp_conversation) {
		render_chat_loading(frm);
	}

	frappe.call({
		method: "gain_maqsam_integration.maqsam_whatsapp.api.maqsam_whatsapp_get_conversation",
		args: {
			conversation_id: frm.doc.conversation_id,
		},
		freeze: Boolean(opts.freeze),
		freeze_message: __("Refreshing Conversation..."),
		callback: (r) => {
			frm._maqsam_whatsapp_loading = false;
			if (r.exc) return;

			frm._maqsam_whatsapp_conversation = r.message || {};
			render_chat_ui(frm, frm._maqsam_whatsapp_conversation.messages || []);
		},
		error: () => {
			frm._maqsam_whatsapp_loading = false;
			render_chat_error(frm);
		},
	});
}

function get_chat_wrapper(frm) {
	if (frm.fields_dict.chat_view && frm.fields_dict.chat_view.$wrapper) {
		return frm.fields_dict.chat_view.$wrapper;
	}

	if (
		frm._maqsam_whatsapp_chat_wrapper &&
		frm._maqsam_whatsapp_chat_wrapper.length &&
		document.body.contains(frm._maqsam_whatsapp_chat_wrapper.get(0))
	) {
		return frm._maqsam_whatsapp_chat_wrapper;
	}

	const $wrapper = $('<div class="m360-chat-wrapper mb-4"></div>');
	const anchor_fields = ["last_message_preview", "last_message_at", "status", "conversation_id"];
	let $anchor = null;

	for (const fieldname of anchor_fields) {
		if (frm.fields_dict[fieldname] && frm.fields_dict[fieldname].$wrapper) {
			$anchor = frm.fields_dict[fieldname].$wrapper;
			break;
		}
	}

	if ($anchor && $anchor.length) {
		$wrapper.insertAfter($anchor);
	} else {
		const $layout = frm.$wrapper.find(".form-layout").first();
		if ($layout.length) {
			$layout.prepend($wrapper);
		} else {
			frm.$wrapper.prepend($wrapper);
		}
	}

	frm._maqsam_whatsapp_chat_wrapper = $wrapper;
	return $wrapper;
}

function render_chat_loading(frm) {
	const $wrapper = get_chat_wrapper(frm);
	$wrapper.html(`
		<div class="text-muted text-center p-4 bg-light rounded border">
			${escape_html(__("Loading conversation transcript..."))}
		</div>
	`);
}

function render_chat_error(frm) {
	const $wrapper = get_chat_wrapper(frm);
	$wrapper.html(`
		<div class="text-muted text-center p-4 bg-light rounded border">
			${escape_html(__("Unable to load conversation transcript."))}
		</div>
	`);
}

function render_chat_ui(frm, messages) {
	const $wrapper = get_chat_wrapper(frm);
	const safe_messages = Array.isArray(messages) ? messages.slice() : [];

	$wrapper.empty();

	if (safe_messages.length === 0) {
		$wrapper.html(`
			<div class="text-muted text-center p-4 bg-light rounded border">
				${escape_html(__("No messages found in conversation payload."))}
			</div>
		`);
		return;
	}

	safe_messages.sort((a, b) => {
		const tA = timestamp_value(a);
		const tB = timestamp_value(b);
		return tA - tB;
	});

	let chat_html = `<div class="d-flex flex-column gap-2 p-3 bg-light rounded border shadow-sm" style="max-height: 500px; overflow-y: auto;">`;

	safe_messages.forEach((msg) => {
		const is_outbound = is_outbound_message(msg);
		const text = message_text(msg);
		const sender = message_sender(msg);
		const timestamp = format_timestamp(message_timestamp(msg));
		const status = message_status(msg);

		const sender_html = sender
			? `<div class="small text-muted mb-1">${escape_html(sender)}</div>`
			: "";
		const timestamp_html = timestamp ? escape_html(timestamp) : "";
		const status_html = status
			? `<span class="ml-1 opacity-75">${escape_html(status)}</span>`
			: "";

		if (is_outbound) {
			chat_html += `
				<div class="d-flex justify-content-end mb-2">
					<div class="p-2 rounded shadow-sm" style="background-color: #dcfce7; color: #166534; max-width: 75%; border-bottom-right-radius: 2px;">
						${sender_html}
						<div style="white-space: pre-wrap; word-wrap: break-word; font-size: 14px;">${escape_html(text)}</div>
						<div class="text-right text-muted" style="font-size: 10px; margin-top: 4px;">
							${timestamp_html}
							${status_html}
						</div>
					</div>
				</div>
			`;
		} else {
			chat_html += `
				<div class="d-flex justify-content-start mb-2">
					<div class="p-2 bg-white rounded shadow-sm border" style="color: #1e293b; max-width: 75%; border-bottom-left-radius: 2px;">
						${sender_html}
						<div style="white-space: pre-wrap; word-wrap: break-word; font-size: 14px;">${escape_html(text)}</div>
						<div class="text-left text-muted" style="font-size: 10px; margin-top: 4px;">
							${timestamp_html}
							${status_html}
						</div>
					</div>
				</div>
			`;
		}
	});

	chat_html += `</div>`;
	$wrapper.html(chat_html);
}

function escape_html(value) {
	return frappe.utils.escape_html(as_text(value));
}

function as_text(value) {
	if (value === null || value === undefined) return "";
	if (typeof value === "object") return JSON.stringify(value);
	return String(value);
}

function message_timestamp(msg) {
	return msg.timestamp || msg.created_at || msg.createdAt || msg.sent_at || msg.sentAt || msg.time || "";
}

function message_text(msg) {
	return as_text(msg.content || msg.text || msg.body || msg.message || "");
}

function message_sender(msg) {
	return as_text(msg.sender || msg.sender_name || msg.senderName || msg.from || msg.to || msg.user || "");
}

function message_status(msg) {
	return as_text(msg.status || msg.state || "");
}

function is_outbound_message(msg) {
	const direction = as_text(msg.direction || msg.type || "").toLowerCase();
	const status = message_status(msg).toLowerCase();
	return (
		direction.includes("out") ||
		direction === "sent" ||
		direction === "delivered" ||
		direction === "read" ||
		status === "sent" ||
		status === "delivered" ||
		status === "read"
	);
}

function timestamp_value(msg) {
	const raw = message_timestamp(msg);
	if (!raw) return 0;
	const parsed = new Date(raw).getTime();
	return Number.isNaN(parsed) ? 0 : parsed;
}

function format_timestamp(value) {
	const raw = as_text(value);
	if (!raw) return "";

	try {
		const date = frappe.datetime.global_date_format(raw);
		const time = frappe.datetime.get_time(raw);
		return `${date} ${time}`.trim();
	} catch (e) {
		return raw;
	}
}
