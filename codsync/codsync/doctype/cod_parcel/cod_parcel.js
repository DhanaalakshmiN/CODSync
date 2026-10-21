frappe.ui.form.on("COD Parcel", {
	refresh(frm) {
		// Raise Dispute button – visible only when payout is Short-paid or Missing
		if (["Short-paid", "Missing"].includes(frm.doc.payout_status)) {
			frm.add_custom_button(__("Raise Dispute"), () => {
				frappe.call({
					method: "codsync.codsync.engine.raise_dispute",
					args: { parcel: frm.doc.name },
					freeze: true,
					callback(r) {
						if (r.message) frappe.set_route("Form", "COD Exception", r.message);
					},
				});
			}, __("Actions"));
		}

		// Sync Tracking button
		frm.add_custom_button(__("Sync Tracking"), () => {
			frappe.call({
				method: "codsync.codsync.tracking.sync_tracking",
				args: { parcel: frm.doc.name },
				freeze: true,
				freeze_message: __("Refreshing tracking..."),
				callback(r) {
					const { checked, updated, failed } = r.message;
					frm.reload_doc();
					frappe.show_alert({
						message: __("Tracking sync: {0} checked, {1} updated, {2} failed.",
							[checked, updated, failed]),
						indicator: failed ? "red" : "green",
					});
				},
			});
		}, __("Actions"));
	},
});
