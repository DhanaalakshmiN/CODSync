"""Unexplained deduction pattern mining: rules and statistics over settled lines, no ML.

Remittance Lines joined with COD Parcels are bucketed by one parcel feature at a time
(status, weight band, COD amount band, pincode zone). A bucket becomes a "pattern" when
the same kind of deduction repeats: enough parcels, a consistent difference and a
meaningful total. Read-only; contract: docs/API_CONTRACT.md (`deduction_patterns`).
"""

import statistics

import frappe
from frappe.utils import flt, getdate

READ_ROLES = ("CODSync Manager", "CODSync Operator", "CODSync Viewer", "System Manager")

# a group is reported as a pattern only when all of these hold
MIN_GROUP_SIZE = 3  # parcels in the group
MIN_CONSISTENCY = 0.7  # share of differences within CONSISTENCY_BAND of the group median
MIN_TOTAL_DIFFERENCE = 100.0  # absolute net difference of the group
MAX_PATTERNS = 10  # cap after ranking
CONSISTENCY_BAND = 0.1  # "within 10% of the group's median"

# (upper limit, label); a value above every limit falls into the last label
WEIGHT_BANDS = ((0.5, "up to 0.5 kg"), (1.0, "0.5-1 kg"), (2.0, "1-2 kg"))
WEIGHT_OVER = "over 2 kg"
AMOUNT_BANDS = ((500.0, "under ₹500"), (1000.0, "₹500-1000"), (2000.0, "₹1000-2000"))
AMOUNT_OVER = "over ₹2000"

FEATURES = ("status", "weight_band", "amount_band", "zone")


def _band(value, bands, over_label):
	for limit, label in bands:
		if value <= limit:
			return label
	return over_label


def _features(row):
	"""One feature value per dimension for a settled line; None when it cannot be derived."""
	status = "Delivered" if row.status == "Delivered" else ("RTO" if row.status == "RTO" else "Other")
	weight = flt(row.charged_weight) or flt(row.line_weight) or flt(row.declared_weight)
	amount = flt(row.cod_amount) or flt(row.line_cod)
	pin = str(row.pincode or "").strip()
	return {
		"status": status,
		"weight_band": _band(flt(weight), WEIGHT_BANDS, WEIGHT_OVER),
		"amount_band": _band(flt(amount), AMOUNT_BANDS, AMOUNT_OVER),
		"zone": pin[:3] if len(pin) >= 3 else None,
	}


def _where(feature, value):
	if feature == "status":
		return f"{value} parcels"
	if feature == "weight_band":
		return f"parcels {value}"
	if feature == "amount_band":
		return f"parcels with COD {value}"
	return f"parcels in the {value}xxx pincode zone"


def _summary(courier, feature, value, count, total, avg):
	verb = "short-paid" if total < 0 else "over-paid"
	return f"{courier} {verb} ₹{abs(avg):,.0f} on {count} {_where(feature, value)}, total ₹{abs(total):,.0f}"


@frappe.whitelist()
def get_deduction_patterns(courier=None, from_date=None, to_date=None):
	"""Repeating unexplained deductions (courier + one feature at a time), ranked by total
	absolute difference, capped at MAX_PATTERNS. Read role."""
	frappe.only_for(READ_ROLES)
	conditions = [
		"r.docstatus = 1",
		"l.cod_parcel is not null",
		"l.match_status != 'Unknown'",
		"coalesce(l.difference, 0) != 0",
	]
	values = {}
	if courier:
		conditions.append("r.courier = %(courier)s")
		values["courier"] = courier
	if from_date:
		conditions.append("r.remittance_date >= %(from_date)s")
		values["from_date"] = getdate(from_date)
	if to_date:
		conditions.append("r.remittance_date <= %(to_date)s")
		values["to_date"] = getdate(to_date)
	rows = frappe.db.sql(
		f"""select l.cod_parcel, l.difference, l.charged_weight as line_weight,
			l.cod_amount as line_cod, r.courier,
			p.status, p.pincode, p.cod_amount, p.declared_weight, p.charged_weight
		from `tabRemittance Line` l
		join `tabCourier Remittance` r on r.name = l.parent
		join `tabCOD Parcel` p on p.name = l.cod_parcel
		where {" and ".join(conditions)}""",
		values,
		as_dict=True,
	)

	groups = {}
	for row in rows:
		for feature, value in _features(row).items():
			if value is None:
				continue
			groups.setdefault((row.courier, feature, value), []).append(row)

	patterns = []
	for (courier_name, feature, value), lines in groups.items():
		count = len(lines)
		if count < MIN_GROUP_SIZE:
			continue
		magnitudes = [abs(flt(l.difference)) for l in lines]
		median = statistics.median(magnitudes)
		consistency = flt(
			sum(1 for m in magnitudes if abs(m - median) <= CONSISTENCY_BAND * median) / count, 2
		)
		if consistency < MIN_CONSISTENCY:
			continue
		total = flt(sum(flt(l.difference) for l in lines), 2)
		if abs(total) < MIN_TOTAL_DIFFERENCE:
			continue
		avg = flt(total / count, 2)
		patterns.append(
			{
				"courier": courier_name,
				"feature": feature,
				"value": value,
				"count": count,
				"total": total,
				"avg": avg,
				"consistency": consistency,
				"summary": _summary(courier_name, feature, value, count, total, avg),
				"parcels": sorted({l.cod_parcel for l in lines}),
			}
		)
	patterns.sort(key=lambda p: abs(p["total"]), reverse=True)
	return patterns[:MAX_PATTERNS]
