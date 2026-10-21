import frappe
from frappe import _


def execute(filters=None):
	return get_columns(), get_data(filters or {})


def get_columns():
	return [
		{"label": _("Order ID"), "fieldname": "order_id", "fieldtype": "Data", "width": 120},
		{"label": _("AWB"), "fieldname": "awb", "fieldtype": "Link", "options": "COD Parcel", "width": 140},
		{
			"label": _("Courier"),
			"fieldname": "courier",
			"fieldtype": "Link",
			"options": "Courier",
			"width": 120,
		},
		{"label": _("COD Amount"), "fieldname": "cod_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Expected Net"), "fieldname": "expected_net", "fieldtype": "Currency", "width": 110},
		{
			"label": _("Amount Received"),
			"fieldname": "actual_settlement",
			"fieldtype": "Currency",
			"width": 120,
		},
		{"label": _("Short Amount"), "fieldname": "short", "fieldtype": "Currency", "width": 110},
		{"label": _("Payout Status"), "fieldname": "payout_status", "fieldtype": "Data", "width": 120},
	]


def get_data(filters):
	conditions = ""
	if filters.get("courier"):
		conditions += " and p.courier = %(courier)s"
	if filters.get("payout_status"):
		conditions += " and p.payout_status = %(payout_status)s"
	if filters.get("from_date"):
		conditions += " and p.delivered_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " and p.delivered_date <= %(to_date)s"

	# expected_net lives on the matched remittance line of a submitted remittance
	# conditions holds only fixed fragments with %(name)s placeholders; values are bound
	return frappe.db.sql(  # nosemgrep
		f"""
		select p.order_id, p.awb, p.courier, p.cod_amount, rl.expected_net,
			p.actual_settlement, greatest(-ifnull(p.difference, 0), 0) as short, p.payout_status
		from `tabCOD Parcel` p
		left join (
			select l.cod_parcel, l.expected_net
			from `tabRemittance Line` l
			join `tabCourier Remittance` r on r.name = l.parent and r.docstatus = 1
		) rl on rl.cod_parcel = p.name
		where 1 = 1 {conditions}
		order by p.delivered_date desc, p.awb
		""",
		filters,
		as_dict=True,
	)
