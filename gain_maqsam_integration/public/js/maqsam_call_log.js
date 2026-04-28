(() => {
	function escapeHtml(value) {
		return String(value || "")
			.replaceAll("&", "&amp;")
			.replaceAll("<", "&lt;")
			.replaceAll(">", "&gt;")
			.replaceAll('"', "&quot;")
			.replaceAll("'", "&#39;");
	}

	function formatDuration(seconds) {
		const totalSeconds = Number(seconds || 0);
		if (!totalSeconds) {
			return __("0 sec");
		}

		const minutes = Math.floor(totalSeconds / 60);
		const remainingSeconds = totalSeconds % 60;
		if (!minutes) {
			return __("{0} sec", [remainingSeconds]);
		}

		return __("{0} min {1} sec", [minutes, remainingSeconds]);
	}

	function formatDateTime(value) {
		if (!value) {
			return __("Not available");
		}

		return frappe.datetime.str_to_user(value);
	}

	function getDirectionMeta(direction) {
		const normalized = String(direction || "").toLowerCase();
		if (normalized === "inbound") {
			return {
				label: __("Incoming Call"),
				chip: __("Inbound"),
				className: "incoming",
				indicator: "#16a34a",
				icon: "phone-incoming",
			};
		}
		if (normalized === "outbound") {
			return {
				label: __("Outgoing Call"),
				chip: __("Outbound"),
				className: "outgoing",
				indicator: "#2563eb",
				icon: "phone-outgoing",
			};
		}

		return {
			label: __("Call"),
			chip: __("Unknown"),
			className: "neutral",
			indicator: "#64748b",
			icon: "phone",
		};
	}

	function getOutcomeMeta(outcome, state) {
		const value = outcome || state || __("Unknown");
		const normalized = String(value || "").toLowerCase();

		if (normalized.includes("answer") || normalized.includes("complete") || normalized.includes("serviced")) {
			return { label: outcome || __("Answered"), className: "success", color: "#15803d", bg: "#dcfce7" };
		}
		if (normalized.includes("busy")) {
			return { label: outcome || __("Busy"), className: "warning", color: "#b45309", bg: "#fef3c7" };
		}
		if (normalized.includes("no answer") || normalized.includes("no_answer") || normalized.includes("abandon")) {
			return { label: outcome || __("No Answer"), className: "danger", color: "#b91c1c", bg: "#fee2e2" };
		}

		return { label: value, className: "muted", color: "#475569", bg: "#e2e8f0" };
	}

	function getCustomerNumber(doc) {
		if (String(doc.direction || "").toLowerCase() === "inbound") {
			return doc.caller_number || doc.normalized_phone || "";
		}
		return doc.callee_number || doc.normalized_phone || "";
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

	function getLinkedIcon(doctype) {
		const map = {
			Patient: "🩺",
			Customer: "👤",
			Lead: "🎯",
			Contact: "📇",
			"Patient Appointment": "📅",
		};
		return map[doctype] || "📂";
	}

	function getGainNumber(doc) {
		if (String(doc.direction || "").toLowerCase() === "inbound") {
			return doc.callee_number || "";
		}
		return doc.caller_number || "";
	}

	function parsePayload(rawPayload) {
		if (!rawPayload) {
			return null;
		}

		try {
			return JSON.parse(rawPayload);
		} catch (error) {
			return null;
		}
	}

	function isPlainObject(value) {
		return Boolean(value) && typeof value === "object" && !Array.isArray(value);
	}

	function isEmptyValue(value) {
		if (value === null || value === undefined || value === "") {
			return true;
		}
		if (Array.isArray(value)) {
			return value.length === 0;
		}
		if (isPlainObject(value)) {
			return Object.keys(value).length === 0;
		}
		return false;
	}

	function humanizeKey(key) {
		return String(key || "")
			.replace(/([a-z])([A-Z])/g, "$1 $2")
			.replace(/_/g, " ")
			.replace(/\b\w/g, (letter) => letter.toUpperCase());
	}

	function formatPayloadTimestamp(value) {
		if (!value) {
			return "";
		}

		if (typeof value === "number") {
			const milliseconds = value > 10000000000 ? value : value * 1000;
			return new Date(milliseconds).toLocaleString();
		}

		return String(value);
	}

	function formatPayloadValue(value) {
		if (isEmptyValue(value)) {
			return `<span class="payload-empty">${__("Empty")}</span>`;
		}

		if (Array.isArray(value)) {
			return value
				.map((item) => {
					if (isPlainObject(item)) {
						return `<div class="payload-nested">${formatPayloadRows(item)}</div>`;
					}
					return `<div>${escapeHtml(item)}</div>`;
				})
				.join("");
		}

		if (isPlainObject(value)) {
			return `<div class="payload-nested">${formatPayloadRows(value)}</div>`;
		}

		return escapeHtml(value);
	}

	function formatPayloadRows(payload, keys = null) {
		const entries = (keys || Object.keys(payload || {}))
			.filter((key) => Object.prototype.hasOwnProperty.call(payload || {}, key))
			.filter((key) => !isEmptyValue(payload[key]));

		if (!entries.length) {
			return `<div class="payload-row"><span>${__("No data")}</span></div>`;
		}

		return entries
			.map(
				(key) => `
					<div class="payload-row">
						<span class="payload-key">${escapeHtml(humanizeKey(key))}</span>
						<span class="payload-value">${formatPayloadValue(payload[key])}</span>
					</div>
				`,
			)
			.join("");
	}

	function payloadBubble({ title, subtitle, body, align = "left", tone = "neutral" }) {
		return `
			<div class="payload-bubble ${align} ${tone}">
				<div class="payload-bubble-title">${escapeHtml(title)}</div>
				${subtitle ? `<div class="payload-bubble-subtitle">${escapeHtml(subtitle)}</div>` : ""}
				<div class="payload-bubble-body">${body}</div>
			</div>
		`;
	}

	function getPayloadSummary(payload, doc) {
		return {
			id: payload?.id || doc.maqsam_call_id,
			direction: payload?.direction || doc.direction,
			type: payload?.type || doc.call_type,
			state: payload?.state || doc.state,
			duration: payload?.duration ?? doc.duration,
			timestamp: formatPayloadTimestamp(payload?.timestamp) || formatDateTime(doc.timestamp),
		};
	}

	function firstValue(object, keys) {
		for (const key of keys) {
			if (object?.[key] !== undefined && object?.[key] !== null && object?.[key] !== "") {
				return object[key];
			}
		}
		return "";
	}

	function hasTranscriptContent(message) {
		return Boolean(firstValue(message, ["content", "text", "message", "transcript", "utterance"]));
	}

	function findTranscriptArray(node, depth = 0, seen = new Set()) {
		if (!node || depth > 6 || seen.has(node)) {
			return [];
		}
		if (typeof node === "object") {
			seen.add(node);
		}

		if (Array.isArray(node)) {
			const looksLikeTranscript = node.some((item) => isPlainObject(item) && hasTranscriptContent(item));
			if (looksLikeTranscript) {
				return node;
			}

			for (const item of node) {
				const found = findTranscriptArray(item, depth + 1, seen);
				if (found.length) {
					return found;
				}
			}
			return [];
		}

		if (isPlainObject(node)) {
			const preferredKeys = [
				"messages",
				"conversation",
				"transcript",
				"transcription",
				"utterances",
				"segments",
				"dialog",
				"dialogue",
			];
			for (const key of preferredKeys) {
				const found = findTranscriptArray(node[key], depth + 1, seen);
				if (found.length) {
					return found;
				}
			}

			for (const value of Object.values(node)) {
				const found = findTranscriptArray(value, depth + 1, seen);
				if (found.length) {
					return found;
				}
			}
		}

		return [];
	}

	function normalizeTranscriptMessage(message) {
		return {
			party: firstValue(message, ["party", "speaker", "role", "participant", "channel"]) || __("Unknown"),
			content: firstValue(message, ["content", "text", "message", "transcript", "utterance"]),
			startTime: firstValue(message, ["startTime", "start_time", "start", "startSeconds", "from"]),
			endTime: firstValue(message, ["endTime", "end_time", "end", "endSeconds", "to"]),
		};
	}

	function getTranscriptMessages(payload) {
		return findTranscriptArray(payload)
			.map(normalizeTranscriptMessage)
			.filter((message) => message.content)
			.sort((left, right) => Number(left.startTime || 0) - Number(right.startTime || 0));
	}

	function formatTranscriptTime(startTime, endTime) {
		const start = startTime !== "" ? `${startTime}s` : "";
		const end = endTime !== "" ? `${endTime}s` : "";
		return [start, end].filter(Boolean).join(" - ");
	}

	function getMessageSide(party) {
		const normalized = String(party || "").toLowerCase();
		if (["agent", "user", "employee", "staff", "operator"].some((part) => normalized.includes(part))) {
			return { align: "right", tone: "sent" };
		}
		if (["customer", "client", "caller", "lead", "patient"].some((part) => normalized.includes(part))) {
			return { align: "left", tone: "received" };
		}
		return { align: "left", tone: "received" };
	}

	function getReadablePayloadSummary(payload, doc, summary, outcomeMeta, directionMeta) {
		const rawSummary = firstValue(payload, [
			"summary",
			"callSummary",
			"aiSummary",
			"conversationSummary",
			"transcriptSummary",
		]);

		const localizedSummary = getLocalizedSummary(rawSummary);
		if (localizedSummary.en || localizedSummary.ar) {
			return localizedSummary;
		}

		return {
			en: [
				directionMeta.label,
				outcomeMeta.label,
				formatDuration(summary.duration),
				doc.linked_title || doc.linked_docname,
			]
				.filter(Boolean)
				.join(" · "),
			ar: "",
		};
	}

	function cleanSummaryText(value) {
		return String(value || "")
			.replaceAll("\\n", "\n")
			.replace(/\s*\n+\s*/g, " ")
			.replace(/\s+/g, " ")
			.trim();
	}

	function parseSummaryValue(value) {
		if (typeof value !== "string") {
			return value;
		}

		const trimmed = value.trim();
		if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) {
			return trimmed;
		}

		try {
			return JSON.parse(trimmed);
		} catch (error) {
			return trimmed;
		}
	}

	function getLocalizedSummary(value) {
		const parsed = parseSummaryValue(value);
		if (typeof parsed === "string") {
			return { en: cleanSummaryText(parsed), ar: "" };
		}

		if (!isPlainObject(parsed)) {
			return { en: "", ar: "" };
		}

		const nestedSummary = firstValue(parsed, ["content", "text", "summary", "message"]);
		const en = firstValue(parsed, ["en", "english", "en_US", "summary_en", "english_summary"]);
		const ar = firstValue(parsed, ["ar", "arabic", "ar_SA", "summary_ar", "arabic_summary"]);

		if (!en && !ar && nestedSummary) {
			return getLocalizedSummary(nestedSummary);
		}

		return {
			en: cleanSummaryText(en),
			ar: cleanSummaryText(ar),
		};
	}

	function renderSummaryLines(summary) {
		const en = cleanSummaryText(summary?.en);
		const ar = cleanSummaryText(summary?.ar);

		if (!en && !ar) {
			return `<div class="localized-summary-empty">${__("No summary available.")}</div>`;
		}

		return `
			<div class="localized-summary-lines">
				${
					en
						? `<div class="localized-summary-line english">
							<span class="localized-summary-label">English</span>
							<span class="localized-summary-text" dir="ltr">${escapeHtml(en)}</span>
						</div>`
						: ""
				}
				${
					ar
						? `<div class="localized-summary-line arabic">
							<span class="localized-summary-label">العربية</span>
							<span class="localized-summary-text" dir="rtl">${escapeHtml(ar)}</span>
						</div>`
						: ""
				}
			</div>
		`;
	}

	function renderPayloadView(frm) {
		const doc = frm.doc || {};
		const payload = parsePayload(doc.raw_payload);
		if (!frm.fields_dict.payload_view_html) {
			return;
		}

		if (!payload) {
			frm.fields_dict.payload_view_html.$wrapper.html(`
				<div class="text-muted" style="padding: 12px 0;">
					${__("No readable raw payload is available for this call yet.")}
				</div>
			`);
			return;
		}

		const summary = getPayloadSummary(payload, doc);
		const directionMeta = getDirectionMeta(summary.direction);
		const outcomeMeta = getOutcomeMeta(doc.outcome, summary.state);
		const transcriptMessages = getTranscriptMessages(payload);
		const readableSummary = getReadablePayloadSummary(payload, doc, summary, outcomeMeta, directionMeta);
		const recordingUrl =
			doc.name && summary.id
				? `/api/method/gain_maqsam_integration.api.maqsam_get_call_recording?call_log=${encodeURIComponent(doc.name)}`
				: "";
		let recordingSaved = Boolean(doc.recording_file);

		function transcriptBubble(message) {
			const side = getMessageSide(message.party);
			const timeText = formatTranscriptTime(message.startTime, message.endTime);
			return `
				<div class="wa-row ${side.align}">
					<div class="wa-bubble ${side.tone}">
						<div class="wa-party">${escapeHtml(message.party)}</div>
						<div class="wa-content" dir="auto">${escapeHtml(message.content)}</div>
						${timeText ? `<div class="wa-footer">${escapeHtml(timeText)}</div>` : ""}
					</div>
				</div>
			`;
		}

		function systemMessage(text) {
			return `<div class="wa-system">${escapeHtml(text)}</div>`;
		}

		const html = `
			<style>
				.maqsam-payload-view {
					width: min(100%, 480px);
					border: 1px solid #d9e2dc;
					border-radius: 16px;
					overflow: hidden;
					background: #efe7dc;
					box-shadow: 0 8px 22px rgba(15, 23, 42, .08);
				}
				.wa-header {
					display: flex;
					align-items: center;
					gap: 10px;
					padding: 10px 12px;
					background: #075e54;
					color: #fff;
				}
				.wa-avatar {
					width: 34px;
					height: 34px;
					border-radius: 50%;
					display: grid;
					place-items: center;
					background: rgba(255, 255, 255, .18);
					font-weight: 800;
				}
				.wa-header-main {
					flex: 1;
					min-width: 0;
				}
				.wa-header-title {
					font-size: 14px;
					font-weight: 750;
					line-height: 1.2;
				}
				.wa-header-subtitle {
					font-size: 11px;
					opacity: .82;
					white-space: nowrap;
					overflow: hidden;
					text-overflow: ellipsis;
				}
				.wa-status {
					background: ${outcomeMeta.bg};
					color: ${outcomeMeta.color};
					border-radius: 999px;
					font-size: 11px;
					font-weight: 800;
					padding: 4px 8px;
					white-space: nowrap;
				}
				.wa-chat {
					background:
						radial-gradient(circle at 10px 10px, rgba(15, 23, 42, .06) 1px, transparent 1px),
						#f7f1e8;
					background-size: 20px 20px;
					padding: 10px;
					display: flex;
					flex-direction: column;
					gap: 7px;
					min-height: 220px;
				}
				.wa-row {
					display: flex;
				}
				.wa-row.left {
					justify-content: flex-start;
				}
				.wa-row.right {
					justify-content: flex-end;
				}
				.wa-bubble {
					max-width: 82%;
					border-radius: 12px;
					padding: 7px 9px 5px;
					box-shadow: 0 1px 1px rgba(15, 23, 42, .12);
					font-size: 12px;
					line-height: 1.35;
				}
				.wa-bubble.received {
					background: #fff;
					border-top-left-radius: 3px;
				}
				.wa-bubble.sent {
					background: #dcf8c6;
					border-top-right-radius: 3px;
				}
				.wa-party {
					color: #075e54;
					font-size: 10px;
					font-weight: 800;
					letter-spacing: .02em;
					text-transform: uppercase;
					margin-bottom: 3px;
				}
				.wa-content {
					color: #111827;
					font-size: 13px;
					white-space: pre-wrap;
					word-break: break-word;
				}
				.wa-footer {
					color: #667781;
					font-size: 10px;
					text-align: right;
					margin-top: 4px;
				}
				.wa-system {
					align-self: center;
					background: rgba(255, 255, 255, .76);
					color: #64748b;
					border-radius: 999px;
					font-size: 11px;
					padding: 4px 9px;
					box-shadow: 0 1px 1px rgba(15, 23, 42, .06);
				}
				.wa-summary {
					background: #fff8dc;
					border: 1px solid #f3df9f;
					border-radius: 12px;
					padding: 8px 10px;
					color: #3f3a22;
					font-size: 12px;
					line-height: 1.45;
					box-shadow: 0 1px 1px rgba(15, 23, 42, .06);
				}
				.wa-summary-title {
					font-weight: 850;
					color: #5f4b00;
					margin-bottom: 3px;
				}
				.wa-recording {
					background: #ffffff;
					border: 1px solid rgba(7, 94, 84, .16);
					border-radius: 12px;
					padding: 8px 10px;
					box-shadow: 0 1px 1px rgba(15, 23, 42, .06);
				}
				.wa-recording-title {
					color: #075e54;
					font-size: 11px;
					font-weight: 850;
					margin-bottom: 6px;
					text-transform: uppercase;
					letter-spacing: .04em;
				}
				.wa-recording-actions {
					display: flex;
					align-items: center;
					flex-wrap: wrap;
					gap: 8px;
					margin-bottom: 6px;
				}
				.wa-recording-status {
					color: #64748b;
					font-size: 11px;
				}
				.wa-recording-error {
					color: #b91c1c;
				}
				.wa-recording audio {
					width: 100%;
					height: 34px;
					display: none;
					margin-top: 4px;
				}
				.wa-recording.loaded audio {
					display: block;
				}
				.localized-summary-lines {
					display: grid;
					gap: 6px;
				}
				.localized-summary-line {
					display: grid;
					grid-template-columns: 72px 1fr;
					gap: 8px;
					align-items: start;
				}
				.localized-summary-line.arabic {
					grid-template-columns: 72px 1fr;
				}
				.localized-summary-label {
					color: #8a6b00;
					font-size: 10px;
					font-weight: 850;
					text-transform: uppercase;
					letter-spacing: .04em;
				}
				.localized-summary-text {
					color: #1f2937;
					font-size: 12px;
					line-height: 1.45;
				}
				.localized-summary-line.arabic .localized-summary-text {
					text-align: right;
					font-family: inherit;
				}
				.localized-summary-empty {
					color: #8a6b00;
					font-size: 12px;
				}
			</style>
			<div class="maqsam-payload-view">
				<div class="wa-header">
					<div class="wa-avatar">M</div>
					<div class="wa-header-main">
						<div class="wa-header-title">${__("Call Transcript")}</div>
						<div class="wa-header-subtitle">${escapeHtml(summary.id || "")}</div>
					</div>
					<div class="wa-status">${escapeHtml(outcomeMeta.label)}</div>
				</div>
				<div class="wa-chat">
					<div class="wa-summary">
						<div class="wa-summary-title">${__("Summary")}</div>
						${renderSummaryLines(readableSummary)}
					</div>
					${
						recordingUrl
							? `<div class="wa-recording">
								<div class="wa-recording-title">${__("Call Recording")}</div>
								<div class="wa-recording-actions">
									<button type="button" class="btn btn-xs btn-default wa-save-recording" ${recordingSaved ? "disabled" : ""}>
										${recordingSaved ? __("Saved in Gain") : __("Save Recording")}
									</button>
									<button type="button" class="btn btn-xs btn-primary wa-load-recording" data-recording-url="${escapeHtml(recordingUrl)}">
										${__("Listen")}
									</button>
									<button type="button" class="btn btn-xs btn-default wa-download-recording" data-recording-url="${escapeHtml(recordingUrl)}">
										${__("Download")}
									</button>
									<span class="wa-recording-status">${recordingSaved ? __("Stored in Gain") : __("Not saved yet")}</span>
								</div>
								<audio controls preload="metadata"></audio>
							</div>`
							: ""
					}
					${systemMessage(`${escapeHtml(directionMeta.label)} · ${escapeHtml(summary.timestamp)}`)}
					${
						transcriptMessages.length
							? transcriptMessages.map(transcriptBubble).join("")
							: systemMessage(
									__(
										"No transcript messages were included in this Maqsam payload. Raw Payload still has the technical call data."
									),
								)
					}
				</div>
			</div>
		`;

		const wrapper = frm.fields_dict.payload_view_html.$wrapper;
		wrapper.html(html);

		async function fetchRecordingBlob(url) {
			const response = await fetch(url, {
				credentials: "same-origin",
				cache: "no-store",
			});
			if (!response.ok) {
				let message = `${response.status} ${response.statusText}`;
				try {
					const payload = await response.json();
					message = payload.message || payload.exception || message;
				} catch (error) {
					// Keep the HTTP status if the response is not JSON.
				}
				throw new Error(message);
			}

			const blob = await response.blob();
			if (!blob.size) {
				throw new Error(__("Maqsam returned an empty recording file."));
			}

			return blob;
		}

		async function saveRecordingIfNeeded(recording, status) {
			if (recordingSaved) {
				return;
			}

			const saveButton = recording.find(".wa-save-recording");
			status.removeClass("wa-recording-error").text(__("Saving recording in Gain..."));
			saveButton.prop("disabled", true).text(__("Saving..."));

			try {
				const result = await frappe.xcall("gain_maqsam_integration.api.maqsam_save_call_recording", {
					call_log: doc.name,
				});
				recordingSaved = true;
				doc.recording_file = result.file_url || doc.recording_file || "__saved__";
				doc.recording_file_size = result.file_size || doc.recording_file_size;
				doc.recording_content_type = result.content_type || doc.recording_content_type;
				if (frm.doc && frm.doc.name === doc.name) {
					frm.doc.recording_file = doc.recording_file;
					frm.doc.recording_file_size = doc.recording_file_size;
					frm.doc.recording_content_type = doc.recording_content_type;
				}
				saveButton.text(__("Saved in Gain"));
				status.text(__("Stored in Gain"));
			} catch (error) {
				saveButton.prop("disabled", false).text(__("Save Recording"));
				throw error;
			}
		}

		wrapper.find(".wa-save-recording").on("click", async function () {
			const button = $(this);
			const recording = button.closest(".wa-recording");
			const status = recording.find(".wa-recording-status");

			button.prop("disabled", true);
			try {
				await saveRecordingIfNeeded(recording, status);
			} catch (error) {
				status.addClass("wa-recording-error").text(error.message || __("Could not save recording."));
			}
		});

		wrapper.find(".wa-load-recording").on("click", async function () {
			const button = $(this);
			const recording = button.closest(".wa-recording");
			const status = recording.find(".wa-recording-status");
			const audio = recording.find("audio").get(0);
			const url = button.attr("data-recording-url");

			button.prop("disabled", true);

			try {
				await saveRecordingIfNeeded(recording, status);
				status.removeClass("wa-recording-error").text(__("Loading recording..."));
				const blob = await fetchRecordingBlob(url);

				if (audio.dataset.objectUrl) {
					URL.revokeObjectURL(audio.dataset.objectUrl);
				}

				const objectUrl = URL.createObjectURL(blob);
				audio.dataset.objectUrl = objectUrl;
				audio.src = objectUrl;
				audio.load();
				recording.addClass("loaded");
				status.text(__("Recording loaded"));
				button.text(__("Reload"));
			} catch (error) {
				status.addClass("wa-recording-error").text(error.message || __("Could not load recording."));
			} finally {
				button.prop("disabled", false);
			}
		});

		wrapper.find(".wa-download-recording").on("click", async function () {
			const button = $(this);
			const recording = button.closest(".wa-recording");
			const status = recording.find(".wa-recording-status");
			const url = button.attr("data-recording-url");
			const downloadUrl = `${url}${url.includes("?") ? "&" : "?"}download=1`;

			button.prop("disabled", true);
			try {
				await saveRecordingIfNeeded(recording, status);
				status.removeClass("wa-recording-error").text(__("Preparing download..."));
				const blob = await fetchRecordingBlob(downloadUrl);
				const objectUrl = URL.createObjectURL(blob);
				const link = document.createElement("a");
				link.href = objectUrl;
				link.download = `maqsam-call-${summary.id || doc.name}.mp3`;
				document.body.appendChild(link);
				link.click();
				link.remove();
				setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
				status.text(__("Download ready"));
			} catch (error) {
				status.addClass("wa-recording-error").text(error.message || __("Could not download recording."));
			} finally {
				button.prop("disabled", false);
			}
		});
	}

	function renderCallView(frm) {
		const doc = frm.doc || {};
		const direction = getDirectionMeta(doc.direction);
		const outcome = getOutcomeMeta(doc.outcome, doc.state);
		const customerNumber = getCustomerNumber(doc);
		const gainNumber = getGainNumber(doc);
		const customerFormatted = formatPhone(customerNumber) || customerNumber || __("Not available");
		const gainFormatted = formatPhone(gainNumber) || gainNumber || __("Not available");
		const linkedTitle = doc.linked_title || doc.linked_docname || "";
		const linkedIcon = getLinkedIcon(doc.linked_doctype);
		const agent = doc.agent_name || doc.agent_email || __("Unassigned");
		const notes = String(doc.notes || "").trim();
		const payload = parsePayload(doc.raw_payload) || {};
		const summary = getPayloadSummary(payload, doc);
		const readableSummary = getReadablePayloadSummary(payload, doc, summary, outcome, direction);
		const recordingUrl = doc.name && doc.maqsam_call_id
			? `/api/method/gain_maqsam_integration.api.maqsam_get_call_recording?call_log=${encodeURIComponent(doc.name)}`
			: "";
		const recordingSavedInitial = Boolean(doc.recording_file);

		const directionEmoji = direction.className === "incoming" ? "📥" : direction.className === "outgoing" ? "📤" : "📞";

		const linkedButton = doc.linked_doctype && doc.linked_docname
			? `<button class="mcl-action mcl-linked" type="button" data-doctype="${escapeHtml(doc.linked_doctype)}" data-name="${escapeHtml(doc.linked_docname)}">
				${linkedIcon} ${escapeHtml(linkedTitle || doc.linked_docname)} <span class="mcl-action-sub">${escapeHtml(doc.linked_doctype)}</span>
			</button>`
			: "";

		const followUpBadge = doc.follow_up_required
			? `<span class="mcl-pill warn">📅 ${__("Follow-up")}${doc.follow_up_date ? " · " + escapeHtml(frappe.datetime.str_to_user(doc.follow_up_date)) : ""}</span>`
			: "";

		const html = `
			<style>
				.mcl { color: #0f172a; max-width: 880px; }
				.mcl * { box-sizing: border-box; }
				.mcl-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; box-shadow: 0 1px 2px rgba(15, 23, 42, .04); }
				.mcl-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; border-bottom: 1px solid #f1f5f9; flex-wrap: wrap; }
				.mcl-header-main { display: flex; align-items: center; gap: 10px; min-width: 0; flex-wrap: wrap; }
				.mcl-direction { display: inline-flex; align-items: center; gap: 6px; font-size: 16px; font-weight: 700; }
				.mcl-direction-dot { width: 10px; height: 10px; border-radius: 50%; background: ${direction.indicator}; box-shadow: 0 0 0 4px ${direction.indicator}1f; }
				.mcl-pill { display: inline-flex; align-items: center; gap: 4px; border-radius: 999px; padding: 3px 10px; font-size: 12px; font-weight: 700; white-space: nowrap; }
				.mcl-pill.outcome { background: ${outcome.bg}; color: ${outcome.color}; }
				.mcl-pill.muted { background: #f1f5f9; color: #475569; }
				.mcl-pill.warn { background: #fef3c7; color: #92400e; }
				.mcl-meta-line { color: #64748b; font-size: 13px; }

				.mcl-recording { display: flex; align-items: center; gap: 12px; padding: 14px 16px; border-bottom: 1px solid #f1f5f9; flex-wrap: wrap; }
				.mcl-recording audio { flex: 1; min-width: 240px; height: 36px; }
				.mcl-recording-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
				.mcl-recording-status { color: #64748b; font-size: 12px; }
				.mcl-recording-error { color: #b91c1c; }

				.mcl-actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 16px; border-bottom: 1px solid #f1f5f9; }
				.mcl-action { display: inline-flex; align-items: center; gap: 6px; padding: 8px 12px; border-radius: 10px; border: 1px solid #e2e8f0; background: #fff; color: #0f172a; font-weight: 600; font-size: 13px; cursor: pointer; transition: all .15s; }
				.mcl-action:hover { background: #f8fafc; border-color: #cbd5e1; }
				.mcl-action.primary { background: #0f766e; color: #fff; border-color: #0f766e; }
				.mcl-action.primary:hover { background: #115e59; }
				.mcl-action.danger { color: #991b1b; border-color: #fecaca; }
				.mcl-action.danger:hover { background: #fee2e2; }
				.mcl-action-sub { font-size: 11px; color: #64748b; font-weight: 500; margin-inline-start: 4px; }
				.mcl-action.mcl-linked .mcl-action-sub { color: rgba(15, 23, 42, .55); }

				.mcl-numbers { display: flex; align-items: center; gap: 10px; padding: 14px 16px; font-size: 14px; flex-wrap: wrap; }
				.mcl-num { font-variant-numeric: tabular-nums; font-weight: 700; }
				.mcl-num-label { color: #64748b; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 2px; }
				.mcl-arrow { color: #94a3b8; font-size: 18px; }
				.mcl-num-block { min-width: 140px; }

				.mcl-summary { background: #fff8dc; border-top: 1px solid #f3df9f; padding: 12px 16px; }
				.mcl-summary-title { color: #5f4b00; font-size: 11px; font-weight: 850; letter-spacing: .04em; text-transform: uppercase; margin-bottom: 6px; }
				.mcl-summary .localized-summary-lines { display: grid; gap: 6px; }
				.mcl-summary .localized-summary-line { display: grid; grid-template-columns: 70px 1fr; gap: 10px; align-items: start; }
				.mcl-summary .localized-summary-label { color: #8a6b00; font-size: 10px; font-weight: 850; text-transform: uppercase; }
				.mcl-summary .localized-summary-text { color: #1f2937; font-size: 13px; line-height: 1.55; }
				.mcl-summary .localized-summary-line.arabic .localized-summary-text { text-align: right; }

				.mcl-notes { padding: 14px 16px; border-top: 1px solid #f1f5f9; }
				.mcl-notes-title { color: #475569; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center; }
				.mcl-notes-text { color: #0f172a; font-size: 13px; line-height: 1.55; white-space: pre-wrap; min-height: 22px; }
				.mcl-notes-text:empty::before { content: "${__("Click here to add a note...")}"; color: #94a3b8; font-style: italic; }
				.mcl-notes-text:hover { background: #f8fafc; cursor: text; border-radius: 6px; }
				.mcl-notes-text[contenteditable="true"] { background: #fefce8; padding: 6px 8px; outline: 2px solid #facc15; border-radius: 6px; cursor: text; }

				.mcl-footer { padding: 10px 16px; border-top: 1px solid #f1f5f9; display: flex; flex-wrap: wrap; gap: 12px; color: #64748b; font-size: 11px; }
				.mcl-footer code { font-family: ui-monospace, SFMono-Regular, monospace; color: #475569; background: #f8fafc; padding: 1px 5px; border-radius: 4px; font-size: 11px; }
			</style>
			<div class="mcl">
				<div class="mcl-card">
					<div class="mcl-header">
						<div class="mcl-header-main">
							<span class="mcl-direction"><span class="mcl-direction-dot"></span>${directionEmoji} ${escapeHtml(direction.label)}</span>
							<span class="mcl-pill outcome">${escapeHtml(outcome.label)}</span>
							<span class="mcl-meta-line">·  ${escapeHtml(formatDuration(doc.duration))}</span>
							<span class="mcl-meta-line">·  ${escapeHtml(formatDateTime(doc.timestamp))}</span>
							${followUpBadge}
						</div>
					</div>

					${recordingUrl ? `
						<div class="mcl-recording mcl-recording-block">
							<audio controls preload="metadata"></audio>
							<div class="mcl-recording-actions">
								<button type="button" class="mcl-action wa-load-recording" data-recording-url="${escapeHtml(recordingUrl)}">${__("Load")}</button>
								<button type="button" class="mcl-action wa-save-recording" ${recordingSavedInitial ? "disabled" : ""}>${recordingSavedInitial ? __("Saved") : __("Save")}</button>
								<button type="button" class="mcl-action wa-download-recording" data-recording-url="${escapeHtml(recordingUrl)}">${__("Download")}</button>
								<span class="wa-recording-status mcl-recording-status">${recordingSavedInitial ? __("Stored in Gain") : __("Click Load to play")}</span>
							</div>
						</div>
					` : ""}

					<div class="mcl-actions">
						${customerNumber ? `<button type="button" class="mcl-action primary" data-action="call-back" data-phone="${escapeHtml(customerNumber)}">📞 ${__("Call Back")}</button>` : ""}
						${linkedButton}
						<button type="button" class="mcl-action" data-action="add-note">📝 ${__("Add Note")}</button>
						<button type="button" class="mcl-action danger" data-action="tag" data-label="Wrong Number">🚫 ${__("Wrong Number")}</button>
						<button type="button" class="mcl-action danger" data-action="tag" data-label="Spam">⛔ ${__("Spam")}</button>
					</div>

					<div class="mcl-numbers">
						<div class="mcl-num-block">
							<div class="mcl-num-label">${__("Customer")}</div>
							<div class="mcl-num">${escapeHtml(customerFormatted)}</div>
						</div>
						<div class="mcl-arrow">${direction.className === "incoming" ? "→" : "←"}</div>
						<div class="mcl-num-block">
							<div class="mcl-num-label">${__("Gain Number")}</div>
							<div class="mcl-num">${escapeHtml(gainFormatted)}</div>
						</div>
						<div class="mcl-num-block" style="margin-inline-start: auto;">
							<div class="mcl-num-label">${__("Agent")}</div>
							<div class="mcl-num" style="font-weight: 600; font-size: 13px;">${escapeHtml(agent)}</div>
						</div>
					</div>

					<div class="mcl-summary">
						<div class="mcl-summary-title">${__("AI Summary")}</div>
						${renderSummaryLines(readableSummary)}
					</div>

					<div class="mcl-notes">
						<div class="mcl-notes-title">
							<span>${__("Notes")}</span>
							<span class="text-muted" style="font-weight: 500; font-size: 10px;">${__("Click text to edit")}</span>
						</div>
						<div class="mcl-notes-text" data-notes-editable>${escapeHtml(notes)}</div>
					</div>

					<div class="mcl-footer">
						<span>${__("Call ID")}: <code>${escapeHtml(doc.maqsam_call_id || "—")}</code></span>
						<span>${__("Source")}: ${escapeHtml(doc.source || "—")}</span>
						<span>${escapeHtml(doc.name || "")}</span>
					</div>
				</div>
			</div>
		`;

		const wrapper = frm.fields_dict.call_view_html?.$wrapper;
		if (!wrapper) return;
		wrapper.html(html);
		bindCallViewActions(frm, wrapper, doc, recordingUrl);
	}

	function bindCallViewActions(frm, wrapper, doc, recordingUrl) {
		// Linked record open
		wrapper.find(".mcl-linked").on("click", function () {
			const dt = $(this).data("doctype");
			const name = $(this).data("name");
			if (dt && name) frappe.set_route("Form", dt, name);
		});

		// Call Back via maqsam_create_click_to_call
		wrapper.find('[data-action="call-back"]').on("click", async function () {
			const button = $(this);
			const phone = button.data("phone");
			if (!phone) return;
			button.prop("disabled", true).text(__("Calling..."));
			try {
				await frappe.xcall("gain_maqsam_integration.api.maqsam_create_click_to_call", {
					phone: String(phone),
					doctype: doc.linked_doctype || null,
					docname: doc.linked_docname || null,
				});
				frappe.show_alert({ message: __("Call placed via Maqsam"), indicator: "green" });
			} catch (error) {
				frappe.show_alert({ message: error.message || __("Could not place call"), indicator: "red" });
			} finally {
				button.prop("disabled", false).html(`📞 ${__("Call Back")}`);
			}
		});

		// Add Note: focuses the inline editable area
		wrapper.find('[data-action="add-note"]').on("click", () => {
			const target = wrapper.find("[data-notes-editable]");
			target.attr("contenteditable", "true").focus();
		});

		// Wrong Number / Spam tagging
		wrapper.find('[data-action="tag"]').on("click", async function () {
			const button = $(this);
			const label = button.data("label");
			button.prop("disabled", true);
			try {
				await frappe.xcall("gain_maqsam_integration.api.maqsam_tag_call", {
					call_log: doc.name,
					label,
				});
				frappe.show_alert({ message: __("Marked as {0}", [label]), indicator: "orange" });
				frm.reload_doc();
			} catch (error) {
				frappe.show_alert({ message: error.message || __("Could not tag call"), indicator: "red" });
				button.prop("disabled", false);
			}
		});

		// Inline notes editor
		const notesEl = wrapper.find("[data-notes-editable]");
		notesEl.on("click", function () {
			$(this).attr("contenteditable", "true").focus();
		});
		notesEl.on("blur", async function () {
			const newValue = $(this).text().trim();
			$(this).removeAttr("contenteditable");
			if (newValue === String(doc.notes || "").trim()) return;
			try {
				await frappe.xcall("gain_maqsam_integration.api.maqsam_update_call_outcome", {
					call_log: doc.name,
					notes: newValue,
				});
				doc.notes = newValue;
				if (frm.doc) frm.doc.notes = newValue;
				frappe.show_alert({ message: __("Note saved"), indicator: "green" });
			} catch (error) {
				frappe.show_alert({ message: error.message || __("Could not save note"), indicator: "red" });
			}
		});
		notesEl.on("keydown", function (e) {
			if (e.key === "Escape") $(this).blur();
			if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $(this).blur();
		});

		// Recording controls — wire onto the same handlers used by Payload View by
		// re-using the existing logic in the wrapper (it scans for these classes).
		bindRecordingControls(frm, wrapper, doc, recordingUrl);
	}

	function bindRecordingControls(frm, wrapper, doc, recordingUrl) {
		if (!recordingUrl) return;
		let recordingSaved = Boolean(doc.recording_file);

		async function fetchRecordingBlob(url) {
			const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
			if (!response.ok) {
				let message = `${response.status} ${response.statusText}`;
				try {
					const payload = await response.json();
					message = payload.message || payload.exception || message;
				} catch (_) {}
				throw new Error(message);
			}
			const blob = await response.blob();
			if (!blob.size) throw new Error(__("Maqsam returned an empty recording file."));
			return blob;
		}

		async function saveRecordingIfNeeded(block, status) {
			if (recordingSaved) return;
			const saveBtn = block.find(".wa-save-recording");
			status.removeClass("mcl-recording-error").text(__("Saving..."));
			saveBtn.prop("disabled", true).text(__("Saving..."));
			const result = await frappe.xcall("gain_maqsam_integration.api.maqsam_save_call_recording", {
				call_log: doc.name,
			});
			recordingSaved = true;
			doc.recording_file = result.file_url || doc.recording_file || "__saved__";
			if (frm.doc && frm.doc.name === doc.name) frm.doc.recording_file = doc.recording_file;
			saveBtn.text(__("Saved"));
			status.text(__("Stored in Gain"));
		}

		wrapper.find(".mcl-recording-block .wa-save-recording").on("click", async function () {
			const btn = $(this);
			const block = btn.closest(".mcl-recording-block");
			const status = block.find(".wa-recording-status");
			btn.prop("disabled", true);
			try {
				await saveRecordingIfNeeded(block, status);
			} catch (error) {
				status.addClass("mcl-recording-error").text(error.message || __("Could not save recording."));
				btn.prop("disabled", false);
			}
		});

		wrapper.find(".mcl-recording-block .wa-load-recording").on("click", async function () {
			const btn = $(this);
			const block = btn.closest(".mcl-recording-block");
			const status = block.find(".wa-recording-status");
			const audio = block.find("audio").get(0);
			const url = btn.attr("data-recording-url");
			btn.prop("disabled", true);
			try {
				await saveRecordingIfNeeded(block, status);
				status.removeClass("mcl-recording-error").text(__("Loading..."));
				const blob = await fetchRecordingBlob(url);
				if (audio.dataset.objectUrl) URL.revokeObjectURL(audio.dataset.objectUrl);
				const objectUrl = URL.createObjectURL(blob);
				audio.dataset.objectUrl = objectUrl;
				audio.src = objectUrl;
				audio.load();
				audio.play().catch(() => {});
				status.text(__("Loaded"));
				btn.text(__("Reload"));
			} catch (error) {
				status.addClass("mcl-recording-error").text(error.message || __("Could not load recording."));
			} finally {
				btn.prop("disabled", false);
			}
		});

		wrapper.find(".mcl-recording-block .wa-download-recording").on("click", async function () {
			const btn = $(this);
			const block = btn.closest(".mcl-recording-block");
			const status = block.find(".wa-recording-status");
			const url = btn.attr("data-recording-url");
			const downloadUrl = `${url}${url.includes("?") ? "&" : "?"}download=1`;
			btn.prop("disabled", true);
			try {
				await saveRecordingIfNeeded(block, status);
				window.location.href = downloadUrl;
			} catch (error) {
				status.addClass("mcl-recording-error").text(error.message || __("Could not download recording."));
			} finally {
				btn.prop("disabled", false);
			}
		});
	}

	frappe.ui.form.on("Maqsam Call Log", {
		refresh(frm) {
			renderCallView(frm);
			renderPayloadView(frm);

			// Raw JSON tab is for engineers — hide for everyone except System Manager.
			const isSystemManager = (frappe.user_roles || []).includes("System Manager");
			frm.fields_dict.raw_payload_tab?.df && frm.toggle_display("raw_payload_tab", isSystemManager);
			frm.fields_dict.raw_payload_section?.df && frm.toggle_display("raw_payload_section", isSystemManager);
			frm.fields_dict.raw_payload?.df && frm.toggle_display("raw_payload", isSystemManager);

			if (!frm.is_new()) {
				frm.add_custom_button(__("Caller Profile"), async () => {
					const profile = await gain_maqsam.caller360.fetchProfile({ call_log: frm.doc.name });
					gain_maqsam.caller360.showDialog(profile, { title: __("Caller Profile") });
				});
			}
		},
	});
})();
