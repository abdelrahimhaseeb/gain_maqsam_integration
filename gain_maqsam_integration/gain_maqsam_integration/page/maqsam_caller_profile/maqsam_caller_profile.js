frappe.pages["maqsam-caller-profile"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Maqsam Caller Profile"),
		single_column: true,
	});

	new MaqsamCallerProfilePage(wrapper);
};

class MaqsamCallerProfilePage {
	constructor(wrapper) {
		this.wrapper = $(wrapper);
		this.page = wrapper.page;
		this.main = this.wrapper.find(".layout-main-section");
		this.make();
	}

	make() {
		this.main.empty().append(`
			<div class="maqsam-caller-profile-page" style="display:grid; gap:16px; padding: 4px 0 24px;">
				<div class="frappe-card" style="padding:16px;">
					<div class="row">
						<div class="col-md-8 caller360-phone-control"></div>
						<div class="col-md-4" style="padding-top: 24px;">
							<button class="btn btn-primary btn-search-caller">${__("Search Caller")}</button>
						</div>
					</div>
					<div class="text-muted small" style="margin-top:8px;">
						${__("Search by local or international phone number. Example: 0564348436 or 966564348436.")}
					</div>
				</div>
				<div class="caller360-result"></div>
			</div>
		`);

		this.phone = frappe.ui.form.make_control({
			parent: this.main.find(".caller360-phone-control"),
			df: {
				fieldtype: "Data",
				fieldname: "phone",
				label: __("Phone Number"),
				placeholder: __("Enter caller phone number"),
				change: () => this.search(),
			},
			render_input: true,
		});
		this.phone.refresh();

		this.main.find(".btn-search-caller").on("click", () => this.search());

		const route = frappe.get_route();
		const routePhone = route?.[1];
		if (routePhone) {
			this.phone.set_value(decodeURIComponent(routePhone));
			this.search();
		} else if (frappe.route_options?.phone) {
			this.phone.set_value(frappe.route_options.phone);
			this.search();
		}
	}

	async search() {
		const phone = this.phone.get_value();
		if (!phone) {
			this.main.find(".caller360-result").html(`
        <div class="text-muted" style="padding: 14px;">${__("Enter a phone number to view Caller Profile.")}</div>
			`);
			return;
		}

		this.main.find(".caller360-result").html(`
			<div class="frappe-card" style="padding:16px;">${__("Loading caller profile...")}</div>
		`);

		try {
			const profile = await gain_maqsam.caller360.fetchProfile({ phone });
			this.main.find(".caller360-result").html(gain_maqsam.caller360.renderProfile(profile));
		} catch (error) {
			this.main.find(".caller360-result").html(`
				<div class="frappe-card" style="padding:16px; color:#b91c1c;">
					${frappe.utils.escape_html(error.message || __("Could not load caller profile."))}
				</div>
			`);
		}
	}
}
