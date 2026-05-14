frappe.provide("gain_maqsam_integration.whatsapp");

gain_maqsam_integration.whatsapp = {
    allowed_roles: ["Maqsam Agent", "Maqsam Supervisor", "System Manager"],
    supported_doctypes: ["Lead", "Contact", "Customer", "Patient", "Patient Appointment"],

    can_use: function () {
        const roles = frappe.user_roles || [];
        return this.allowed_roles.some((role) => roles.includes(role));
    },

    escape_html: function (value) {
        return frappe.utils.escape_html(String(value ?? ""));
    },

    get_variable_default: function (dialog, variable) {
        const defaults = dialog.variable_defaults || {};
        const direct = defaults[variable] ?? defaults[String(variable)];
        if (direct !== undefined && direct !== null) return String(direct);

        const orderedKeys = Object.keys(defaults);
        const index = Number(variable) - 1;
        if (index >= 0 && index < orderedKeys.length) {
            const value = defaults[orderedKeys[index]];
            if (value !== undefined && value !== null) return String(value);
        }
        return "";
    },

    init: function (frm) {
        if (frm.is_new()) return;
        if (!this.can_use()) return;
        if (!this.supported_doctypes.includes(frm.doc.doctype)) return;
        if (frm._maqsam_whatsapp_button_added) return;
        frm._maqsam_whatsapp_button_added = true;

        frm.add_custom_button(
            __("Send WhatsApp"),
            () => this.show_dialog(frm),
            __("Maqsam")
        );
    },

    show_dialog: function (frm) {
        frappe.call({
            method: "gain_maqsam_integration.maqsam_whatsapp.api.maqsam_whatsapp_get_defaults",
            args: {
                doctype: frm.doc.doctype,
                docname: frm.doc.name,
            },
            freeze: true,
            freeze_message: __("Loading WhatsApp context..."),
            callback: (r) => {
                if (r.message) {
                    this._render_dialog(frm, r.message);
                }
            },
        });
    },

    _render_dialog: function (frm, defaults) {
        const candidates = defaults.phone_candidates || [];
        const default_phone = candidates.length > 0 ? candidates[0] : "";

        const templates = defaults.suggested_templates || [];
        const default_template = templates.length > 0 ? templates[0] : "";

        const dialog = new frappe.ui.Dialog({
            title: __("Send WhatsApp via Maqsam"),
            fields: [
                {
                    fieldname: "template",
                    fieldtype: "Link",
                    label: __("Template"),
                    options: "Maqsam WhatsApp Template",
                    default: default_template,
                    reqd: 1,
                    description: __("Select the pre-approved WhatsApp template to send."),
                    get_query: () => ({
                        filters: {
                            active: 1,
                            status: ["in", ["approved", "Approved", "APPROVED"]],
                        },
                    }),
                },
                {
                    fieldname: "phone",
                    fieldtype: "Data",
                    label: __("Recipient Phone"),
                    default: default_phone,
                    reqd: 1,
                    description: __("Phone number of the recipient (+E.164 format recommended)."),
                },
                {
                    fieldtype: "Section Break",
                    fieldname: "variables_section",
                    label: __("Template Variables"),
                    hidden: 1,
                },
                {
                    fieldname: "variables_html",
                    fieldtype: "HTML",
                },
                {
                    fieldtype: "Section Break",
                },
                {
                    fieldname: "preview_html",
                    fieldtype: "HTML",
                    label: __("Preview"),
                }
            ],
            primary_action_label: __("Send"),
            primary_action: (values) => {
                this.submit(frm, dialog, values);
            },
        });

        // Store defaults for variables explicitly
        dialog.variable_defaults = defaults.variable_defaults || {};
        dialog._sending = false;

        // Listen to template changes to render variables
        dialog.fields_dict.template.df.onchange = () => {
            const template_id = dialog.get_value("template");
            if (template_id) {
                frappe.db.get_doc("Maqsam WhatsApp Template", template_id).then((doc) => {
                    this.render_variables(dialog, doc);
                });
            } else {
                dialog.set_df_property("variables_section", "hidden", 1);
                dialog.fields_dict.variables_html.$wrapper.empty();
                dialog.fields_dict.preview_html.$wrapper.empty();
            }
        };

        dialog.show();

        // Trigger initial load if default template exists
        if (default_template) {
            setTimeout(() => {
                dialog.fields_dict.template.df.onchange();
            }, 100);
        }
    },

    render_variables: function (dialog, template_doc) {
        const content = template_doc.content || "";
        // Extract {{1}}, {{2}} kind of variables using regex
        const matches = content.match(/\{\{(\d+)\}\}/g) || [];
        const variablesSet = new Set(matches.map((m) => m.replace(/[{}]/g, "")));
        const variables = Array.from(variablesSet).sort((a, b) => Number(a) - Number(b));

        dialog.template_content = content;
        dialog.template_variables = variables;

        if (variables.length > 0) {
            dialog.set_df_property("variables_section", "hidden", 0);
            let html = `<div class="mb-3">`;
            variables.forEach((v) => {
                const defaultValue = this.get_variable_default(dialog, v);
                const escapedDefault = this.escape_html(defaultValue);
                const escapedPlaceholder = this.escape_html(`${__("Value for")} {{${v}}}`);
                html += `
					<div class="form-group">
						<label class="control-label text-muted small">${__("Variable")} {{${v}}}</label>
						<input type="text" class="form-control form-control-sm m360-var-input" data-var="${v}" value="${escapedDefault}" placeholder="${escapedPlaceholder}">
					</div>
				`;
            });
            html += `</div>`;
            dialog.fields_dict.variables_html.$wrapper.html(html);

            // Bind live preview
            dialog.fields_dict.variables_html.$wrapper.find("input").on("input", () => {
                this.render_preview(dialog);
            });
        } else {
            dialog.set_df_property("variables_section", "hidden", 1);
            dialog.fields_dict.variables_html.$wrapper.empty();
        }

        this.render_preview(dialog);
    },

    render_preview: function (dialog) {
        let content = this.escape_html(dialog.template_content || "");
        const inputs = dialog.fields_dict.variables_html.$wrapper.find("input");

        let vars_dict = {};
        inputs.each((_, el) => {
            const v = $(el).data("var");
            vars_dict[v] = $(el).val() || `{{${v}}}`;
        });

        // Replace placeholders with preview values
        content = content.replace(/\{\{(\d+)\}\}/g, (match, p1) => {
            return `<strong>${this.escape_html(vars_dict[p1] || match)}</strong>`;
        });

        dialog.fields_dict.preview_html.$wrapper.html(`
			<div class="p-3 bg-light rounded text-dark mt-2 border">
				${content.replace(/\n/g, "<br>")}
			</div>
		`);
    },

    submit: function (frm, dialog, values) {
        if (!values.template || !values.phone) {
            frappe.msgprint(__("Template and Phone are required."));
            return;
        }

        if (dialog._sending) return;
        dialog._sending = true;
        dialog.get_primary_btn().prop("disabled", true);

        // Extract variables
        const inputs = dialog.fields_dict.variables_html.$wrapper.find("input");
        let variablesObj = {};
        inputs.each((_, el) => {
            const v = $(el).data("var");
            variablesObj[v] = $(el).val();
        });

        frappe.call({
            method: "gain_maqsam_integration.maqsam_whatsapp.api.maqsam_whatsapp_send_template",
            args: {
                template: values.template,
                phone: values.phone,
                reference_doctype: frm.doc.doctype,
                reference_name: frm.doc.name,
                variables: JSON.stringify(variablesObj),
            },
            freeze: true,
            freeze_message: __("Sending WhatsApp Message..."),
            callback: (r) => {
                if (!r.exc && r.message && r.message.ok) {
                    dialog._sending = false;
                    dialog.get_primary_btn().prop("disabled", false);
                    dialog.hide();
                    frappe.show_alert({
                        message: __("WhatsApp Message Sent Successfully."),
                        indicator: "green",
                    });
                    // Route to the conversation list natively
                    if (r.message.conversation) {
                        frappe.set_route("Form", "Maqsam WhatsApp Conversation", r.message.conversation);
                    }
                } else {
                    dialog._sending = false;
                    dialog.get_primary_btn().prop("disabled", false);
                }
            },
            error: (err) => {
                dialog._sending = false;
                dialog.get_primary_btn().prop("disabled", false);
                // Frappe will automatically show the exception via its global error UI.
            },
        });
    },
};

gain_maqsam_integration.whatsapp.supported_doctypes.forEach((doctype) => {
    frappe.ui.form.on(doctype, {
        refresh: function (frm) {
            gain_maqsam_integration.whatsapp.init(frm);
        },
    });
});
