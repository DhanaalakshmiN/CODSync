frappe.listview_settings["COD Parcel"] = {
	add_fields: ["payout_status"],
	onload(listview) {
		listview.page.add_inner_button(__("Import Parcels"), () =>
			codsync.import_dialog("Parcels", listview)
		);
	},
	get_indicator(doc) {
		const colors = {
			Paid: "green",
			"Short-paid": "orange",
			Missing: "red",
			Unknown: "purple",
			"Awaiting payout": "blue",
			"Not due": "gray",
		};
		return [
			__(doc.payout_status),
			colors[doc.payout_status] || "gray",
			"payout_status,=," + doc.payout_status,
		];
	},
};
