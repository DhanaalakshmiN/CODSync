const PAYOUT_COLORS = {
	Paid: "green",
	"Short-paid": "orange",
	Missing: "red",
	Unknown: "purple",
	"Awaiting payout": "blue",
	"Not due": "gray",
};

frappe.query_reports["Payout Reconciliation"] = {
	filters: [
		{ fieldname: "courier", label: __("Courier"), fieldtype: "Link", options: "Courier" },
		{
			fieldname: "payout_status",
			label: __("Payout Status"),
			fieldtype: "Select",
			options: "\nNot due\nAwaiting payout\nPaid\nShort-paid\nMissing\nUnknown",
		},
		{ fieldname: "from_date", label: __("Delivered From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Delivered To"), fieldtype: "Date" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "payout_status" && data && data.payout_status) {
			const color = PAYOUT_COLORS[data.payout_status] || "gray";
			value = `<span class="indicator-pill ${color}">${frappe.utils.escape_html(
				data.payout_status
			)}</span>`;
		}
		return value;
	},
};
