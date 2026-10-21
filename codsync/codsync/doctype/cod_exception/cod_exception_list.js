frappe.listview_settings["COD Exception"] = {
	add_fields: ["status", "dispute_status"],
	get_indicator(doc) {
		const disputes = {
			"Raised with Courier": "blue",
			Resolved: "green",
			Rejected: "red",
		};
		if (doc.dispute_status && disputes[doc.dispute_status]) {
			return [
				__(doc.dispute_status),
				disputes[doc.dispute_status],
				"dispute_status,=," + doc.dispute_status,
			];
		}
		return [
			__(doc.status),
			doc.status === "Resolved" ? "green" : "orange",
			"status,=," + doc.status,
		];
	},
};
