frappe.ui.form.on("Store Connection", {
	refresh(frm) {
		frm.add_custom_button(__("Test Connection"), () => {
			frm.call("test_connection").then((r) => {
				const m = r.message || {};
				frappe.msgprint({
					title: __("Test Connection"),
					message: m.message,
					indicator: m.ok ? "green" : "red",
				});
				frm.reload_doc();
			});
		});
		frm.add_custom_button(__("Fetch Orders"), () => {
			frm.call("fetch_orders").then((r) => {
				const c = r.message || {};
				frappe.msgprint(
					__("Fetched {0}, COD {1}, created {2}, updated {3}, skipped {4}, failed {5}", [
						c.fetched,
						c.cod,
						c.created,
						c.updated,
						c.skipped,
						c.failed,
					])
				);
				frm.reload_doc();
			});
		});
	},
});
