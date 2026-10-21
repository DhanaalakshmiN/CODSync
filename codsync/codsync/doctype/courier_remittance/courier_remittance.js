frappe.ui.form.on("Courier Remittance", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.docstatus < 2) {
			frm.add_custom_button(__("Run Matching"), () => {
				frappe.call({
					method: "codsync.codsync.matching.run_matching",
					args: { remittance: frm.doc.name },
					freeze: true,
					freeze_message: __("Matching lines to parcels..."),
					callback(r) {
						const c = r.message;
						frappe.msgprint({
							message: __("Matching complete: {0} matched, {1} short-paid, {2} unknown, {3} exceptions.",
								[c.matched, c["short-paid"], c.unknown, c.exceptions]),
							indicator: c.exceptions ? "orange" : "green",
							title: __("Run Matching"),
						});
						frm.reload_doc();
					},
				});
			}, __("Actions"));
		}
	},
});
