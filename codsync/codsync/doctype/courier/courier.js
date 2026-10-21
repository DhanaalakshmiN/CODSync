frappe.ui.form.on("Courier", {
	refresh(frm) {
		frm.add_custom_button(__("Sync Tracking"), () => {
			frappe.call({
				method: "codsync.codsync.tracking.sync_tracking",
				args: { courier: frm.doc.name },
				freeze: true,
				freeze_message: __("Refreshing tracking..."),
				callback(r) {
					const { checked, updated, failed } = r.message;
					frappe.msgprint({
						message: __("Tracking sync for {0}: {1} checked, {2} updated, {3} failed.",
							[frm.doc.name, checked, updated, failed]),
						indicator: failed ? "red" : "green",
					});
					frm.reload_doc();
				},
			});
		});
	},
});
