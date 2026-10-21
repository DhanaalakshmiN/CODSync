frappe.listview_settings["Courier Remittance"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Import Remittance"), () => codsync.import_dialog("Remittance", listview));
	},
};
