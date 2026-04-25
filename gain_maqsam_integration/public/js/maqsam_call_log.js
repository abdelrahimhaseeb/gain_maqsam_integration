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
		const linkedTitle = doc.linked_title || doc.linked_docname || __("Unlinked record");
		const agent = doc.agent_name || doc.agent_email || __("Unassigned agent");
		const agentEmail = doc.agent_email && doc.agent_name ? ` · ${doc.agent_email}` : "";
		const notes = String(doc.notes || "").trim();
		const payload = parsePayload(doc.raw_payload) || {};
		const summary = getPayloadSummary(payload, doc);
		const readableSummary = getReadablePayloadSummary(payload, doc, summary, outcome, direction);
		const followUpHtml =
			doc.follow_up_required || doc.follow_up_date
				? `
					<div class="maqsam-call-message system">
						<div class="message-title">${__("Follow-up")}</div>
						<div>${doc.follow_up_required ? __("Required") : __("Optional")}${
							doc.follow_up_date ? ` · ${escapeHtml(frappe.datetime.str_to_user(doc.follow_up_date))}` : ""
						}</div>
					</div>
				`
				: "";

		const linkedHtml =
			doc.linked_doctype && doc.linked_docname
				? `
					<button class="btn btn-xs btn-default maqsam-linked-record" type="button">
						${escapeHtml(doc.linked_doctype)}: ${escapeHtml(linkedTitle)}
					</button>
				`
				: `<span class="text-muted">${escapeHtml(linkedTitle)}</span>`;

		const html = `
			<style>
				.maqsam-call-view {
					background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
					border: 1px solid #e2e8f0;
					border-radius: 18px;
					padding: 18px;
					max-width: 820px;
				}
				.maqsam-call-header {
					display: flex;
					align-items: center;
					justify-content: space-between;
					gap: 12px;
					margin-bottom: 16px;
				}
				.maqsam-call-title {
					display: flex;
					align-items: center;
					gap: 10px;
					font-size: 18px;
					font-weight: 700;
					color: #0f172a;
				}
				.maqsam-call-dot {
					width: 12px;
					height: 12px;
					border-radius: 50%;
					background: ${direction.indicator};
					box-shadow: 0 0 0 5px ${direction.indicator}22;
				}
				.maqsam-call-chip {
					border-radius: 999px;
					background: ${outcome.bg};
					color: ${outcome.color};
					font-size: 12px;
					font-weight: 700;
					padding: 5px 10px;
					white-space: nowrap;
				}
				.maqsam-call-thread {
					display: flex;
					flex-direction: column;
					gap: 10px;
				}
				.maqsam-call-message {
					border-radius: 16px;
					padding: 12px 14px;
					max-width: 72%;
					box-shadow: 0 1px 2px rgba(15, 23, 42, .08);
					line-height: 1.55;
				}
				.maqsam-call-message.incoming {
					align-self: flex-start;
					background: #ffffff;
					border-top-left-radius: 4px;
				}
				.maqsam-call-message.outgoing {
					align-self: flex-end;
					background: #dbeafe;
					border-top-right-radius: 4px;
				}
				.maqsam-call-message.system {
					align-self: center;
					background: #f1f5f9;
					color: #475569;
					max-width: 92%;
					text-align: center;
					font-size: 13px;
				}
				.message-title {
					font-size: 12px;
					font-weight: 700;
					color: #64748b;
					text-transform: uppercase;
					letter-spacing: .04em;
					margin-bottom: 4px;
				}
				.message-main {
					font-size: 15px;
					font-weight: 650;
					color: #0f172a;
				}
				.message-muted {
					color: #64748b;
					font-size: 13px;
					margin-top: 4px;
				}
				.maqsam-call-meta-grid {
					display: grid;
					grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
					gap: 10px;
					margin-top: 16px;
				}
				.maqsam-call-meta {
					background: rgba(255, 255, 255, .72);
					border: 1px solid #e2e8f0;
					border-radius: 14px;
					padding: 10px 12px;
				}
				.maqsam-call-meta-label {
					color: #64748b;
					font-size: 12px;
					margin-bottom: 3px;
				}
					.maqsam-call-meta-value {
						color: #0f172a;
						font-weight: 650;
						word-break: break-word;
					}
					.maqsam-call-summary {
						background: #fff8dc;
						border: 1px solid #f3df9f;
						border-radius: 14px;
						color: #3f3a22;
						padding: 12px 14px;
						margin-bottom: 14px;
						box-shadow: 0 1px 2px rgba(15, 23, 42, .06);
					}
					.maqsam-call-summary-title {
						color: #5f4b00;
						font-size: 12px;
						font-weight: 850;
						letter-spacing: .04em;
						text-transform: uppercase;
						margin-bottom: 4px;
					}
					.maqsam-call-summary-text {
						color: #1f2937;
						font-size: 13px;
						line-height: 1.55;
					}
					.maqsam-call-summary .localized-summary-lines {
						display: grid;
						gap: 8px;
					}
					.maqsam-call-summary .localized-summary-line {
						display: grid;
						grid-template-columns: 82px 1fr;
						gap: 10px;
						align-items: start;
					}
					.maqsam-call-summary .localized-summary-label {
						color: #8a6b00;
						font-size: 11px;
						font-weight: 850;
						text-transform: uppercase;
						letter-spacing: .04em;
					}
					.maqsam-call-summary .localized-summary-text {
						color: #1f2937;
						font-size: 13px;
						line-height: 1.55;
					}
					.maqsam-call-summary .localized-summary-line.arabic .localized-summary-text {
						text-align: right;
					}
					.maqsam-call-summary .localized-summary-empty {
						color: #8a6b00;
						font-size: 13px;
					}
				</style>
				<div class="maqsam-call-view">
					<div class="maqsam-call-header">
						<div class="maqsam-call-title">
						<span class="maqsam-call-dot"></span>
						<span>${escapeHtml(direction.label)}</span>
						</div>
						<span class="maqsam-call-chip">${escapeHtml(outcome.label)}</span>
					</div>
					<div class="maqsam-call-summary">
						<div class="maqsam-call-summary-title">${__("Summary")}</div>
						<div class="maqsam-call-summary-text">${renderSummaryLines(readableSummary)}</div>
					</div>
					<div class="maqsam-call-thread">
						<div class="maqsam-call-message ${direction.className}">
						<div class="message-title">${escapeHtml(direction.chip)}</div>
						<div class="message-main">
							${
								direction.className === "incoming"
									? __("Customer called Gain number")
									: __("Agent called customer")
							}
						</div>
						<div class="message-muted">
							${__("Customer")}: ${escapeHtml(customerNumber || __("Not available"))}
						</div>
						<div class="message-muted">
							${__("Gain Number")}: ${escapeHtml(gainNumber || __("Not available"))}
						</div>
					</div>
					<div class="maqsam-call-message system">
						<div class="message-title">${__("Call Result")}</div>
						<div>${escapeHtml(outcome.label)} · ${escapeHtml(formatDuration(doc.duration))}</div>
						<div class="message-muted">${escapeHtml(formatDateTime(doc.timestamp))}</div>
					</div>
					${
						notes
							? `<div class="maqsam-call-message system"><div class="message-title">${__("Notes")}</div><div>${escapeHtml(notes)}</div></div>`
							: ""
					}
					${followUpHtml}
				</div>
				<div class="maqsam-call-meta-grid">
					<div class="maqsam-call-meta">
						<div class="maqsam-call-meta-label">${__("Linked Record")}</div>
						<div class="maqsam-call-meta-value">${linkedHtml}</div>
					</div>
					<div class="maqsam-call-meta">
						<div class="maqsam-call-meta-label">${__("Agent")}</div>
						<div class="maqsam-call-meta-value">${escapeHtml(agent)}${escapeHtml(agentEmail)}</div>
					</div>
					<div class="maqsam-call-meta">
						<div class="maqsam-call-meta-label">${__("Maqsam Call ID")}</div>
						<div class="maqsam-call-meta-value">${escapeHtml(doc.maqsam_call_id || __("Not available"))}</div>
					</div>
					<div class="maqsam-call-meta">
						<div class="maqsam-call-meta-label">${__("Source")}</div>
						<div class="maqsam-call-meta-value">${escapeHtml(doc.source || __("Not available"))}</div>
					</div>
				</div>
			</div>
		`;

		frm.fields_dict.call_view_html?.$wrapper.html(html);
		frm.fields_dict.call_view_html?.$wrapper
			.find(".maqsam-linked-record")
			.on("click", () => frappe.set_route("Form", doc.linked_doctype, doc.linked_docname));
	}

	frappe.ui.form.on("Maqsam Call Log", {
		refresh(frm) {
			renderCallView(frm);
			renderPayloadView(frm);
			if (!frm.is_new()) {
    frm.add_custom_button(__("Caller Profile"), async () => {
					const profile = await gain_maqsam.caller360.fetchProfile({ call_log: frm.doc.name });
      gain_maqsam.caller360.showDialog(profile, { title: __("Caller Profile") });
				});
			}
		},
	});
})();
