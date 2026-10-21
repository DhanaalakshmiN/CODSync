import frappe
from frappe import _


def execute(filters=None):
	columns = [
		{
			"label": _("Courier"),
			"fieldname": "courier",
			"fieldtype": "Link",
			"options": "Courier",
			"width": 140,
		},
		{"label": _("COD Collected"), "fieldname": "collected", "fieldtype": "Currency", "width": 130},
		{"label": _("Payout Received"), "fieldname": "received", "fieldtype": "Currency", "width": 130},
		{"label": _("Short Amount"), "fieldname": "short", "fieldtype": "Currency", "width": 120},
		{"label": _("Missing Amount"), "fieldname": "missing", "fieldtype": "Currency", "width": 130},
		{"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Currency", "width": 130},
	]

	conditions = ""
	if (filters or {}).get("courier"):
		conditions = " where courier = %(courier)s"

	# Outstanding = COD still unpaid (Awaiting payout + Missing) + shortfall on short-paid parcels
	# conditions holds only fixed fragments with %(name)s placeholders; values are bound
	data = frappe.db.sql(  # nosemgrep
		f"""
		select courier,
			sum(case when status = 'Delivered' then cod_amount else 0 end) as collected,
			sum(actual_settlement) as received,
			sum(greatest(-ifnull(difference, 0), 0)) as short,
			sum(case when payout_status = 'Missing' then cod_amount else 0 end) as missing,
			sum(case when payout_status in ('Awaiting payout', 'Missing') then cod_amount else 0 end)
				+ sum(greatest(-ifnull(difference, 0), 0)) as outstanding
		from `tabCOD Parcel`
		{conditions}
		group by courier
		order by courier
		""",
		filters or {},
		as_dict=True,
	)

	chart = {
		"data": {
			"labels": [d.courier for d in data],
			"datasets": [{"name": _("Outstanding"), "values": [d.outstanding or 0 for d in data]}],
		},
		"type": "bar",
	}
	return columns, data, None, chart
