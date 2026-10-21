import frappe
from frappe import _

BUCKETS = [("b0_7", "0-7 days"), ("b8_15", "8-15 days"), ("b16_30", "16-30 days"), ("b30_plus", "30+ days")]


def execute(filters=None):
	filters = filters or {}
	columns = [
		{
			"label": _("Courier"),
			"fieldname": "courier",
			"fieldtype": "Link",
			"options": "Courier",
			"width": 140,
		}
	]
	columns += [
		{"label": _(label), "fieldname": f, "fieldtype": "Currency", "width": 120} for f, label in BUCKETS
	]
	columns.append({"label": _("Total"), "fieldname": "total", "fieldtype": "Currency", "width": 130})

	conditions = ""
	if filters.get("courier"):
		conditions = " and courier = %(courier)s"

	# conditions holds only fixed fragments with %(name)s placeholders; values are bound
	data = frappe.db.sql(  # nosemgrep
		f"""
		select courier,
			sum(case when age <= 7 then cod_amount else 0 end) as b0_7,
			sum(case when age between 8 and 15 then cod_amount else 0 end) as b8_15,
			sum(case when age between 16 and 30 then cod_amount else 0 end) as b16_30,
			sum(case when age > 30 then cod_amount else 0 end) as b30_plus,
			sum(cod_amount) as total
		from (
			select courier, cod_amount, datediff(curdate(), delivered_date) as age
			from `tabCOD Parcel`
			where status = 'Delivered' and payout_status != 'Paid'
				and delivered_date is not null {conditions}
		) t
		group by courier
		order by courier
		""",
		filters,
		as_dict=True,
	)
	return columns, data
