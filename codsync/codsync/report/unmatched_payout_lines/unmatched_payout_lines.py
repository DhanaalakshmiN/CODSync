import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	columns = [
		{
			"label": _("Remittance"),
			"fieldname": "remittance",
			"fieldtype": "Link",
			"options": "Courier Remittance",
			"width": 160,
		},
		{
			"label": _("Courier"),
			"fieldname": "courier",
			"fieldtype": "Link",
			"options": "Courier",
			"width": 120,
		},
		{"label": _("AWB"), "fieldname": "awb", "fieldtype": "Data", "width": 140},
		{"label": _("Net Paid"), "fieldname": "net_paid", "fieldtype": "Currency", "width": 110},
	]

	conditions = ""
	if filters.get("courier"):
		conditions = " and r.courier = %(courier)s"
	if filters.get("from_date"):
		conditions += " and r.remittance_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " and r.remittance_date <= %(to_date)s"

	# conditions holds only fixed fragments with %(name)s placeholders; values are bound
	data = frappe.db.sql(  # nosemgrep
		f"""
		select r.name as remittance, r.courier, l.awb, l.net_paid
		from `tabRemittance Line` l
		join `tabCourier Remittance` r on r.name = l.parent
		where r.docstatus = 1 and l.match_status = 'Unknown' {conditions}
		order by r.remittance_date desc, l.idx
		""",
		filters,
		as_dict=True,
	)
	return columns, data
