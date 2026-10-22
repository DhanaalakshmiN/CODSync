"""Courier performance intelligence: plain aggregation over COD Parcels and Remittance Lines, no ML.

Parcels are filtered by order date and grouped by courier (or courier + the first 3 pincode
digits). Payout metrics come from submitted Remittance Lines of those parcels. Each period is
also computed for the previous period of equal length so the UI can show trend arrows.
Read-only; contract: docs/API_CONTRACT.md (`courier_performance`).
"""

import frappe
from frappe.utils import add_days, date_diff, flt, getdate, nowdate

READ_ROLES = ("CODSync Manager", "CODSync Operator", "CODSync Viewer", "System Manager")

DEFAULT_DAYS = 30
ZONE_DIGITS = 3
UNKNOWN_ZONE = "Unknown"
GROUP_BYS = ("courier", "courier_zone")

# composite score weights (sum to 1); each metric is min-max normalised across ranked groups
W_DELIVERY_RATE = 0.40
W_LOW_RTO = 0.20
W_LOW_COST = 0.20
W_SPEED = 0.10
W_PAYOUT_LAG = 0.10
SCORE_MAX = 100
NEUTRAL = 0.5  # normalised value of a metric a group has no data for
MIN_PARCELS = 10  # groups with fewer dispatched parcels are returned but not ranked


def _div(a, b):
	return round(a / b, 4) if b else None


def _avg(total, n, digits=1):
	return round(total / n, digits) if n else None


def _parcels(start, end):
	return frappe.db.sql(
		"""select name, courier, pincode, status, order_date, delivered_date, cod_amount, payout_status
		from `tabCOD Parcel`
		where ifnull(awb, '') != '' and ifnull(courier, '') != ''
			and date(order_date) between %(start)s and %(end)s""",
		{"start": start, "end": end},
		as_dict=True,
	)


def _paid_lines(start, end):
	return frappe.db.sql(
		"""select l.cod_parcel, l.freight, l.cod_fee, l.gst, l.net_paid, l.expected_net, r.remittance_date
		from `tabRemittance Line` l
		join `tabCourier Remittance` r on r.name = l.parent
		join `tabCOD Parcel` p on p.name = l.cod_parcel
		where r.docstatus = 1 and l.cod_parcel is not null and l.match_status != 'Unknown'
			and date(p.order_date) between %(start)s and %(end)s""",
		{"start": start, "end": end},
		as_dict=True,
	)


def _key(parcel, group_by):
	pin = str(parcel.pincode or "").strip()
	zone = pin[:ZONE_DIGITS] if len(pin) >= ZONE_DIGITS else UNKNOWN_ZONE
	return (parcel.courier, zone) if group_by == "courier_zone" else (parcel.courier, None)


def _period(start, end, group_by):
	"""{(courier, zone): metrics} for parcels ordered in [start, end]."""
	groups, owner = {}, {}
	for p in _parcels(start, end):
		k = _key(p, group_by)
		owner[p.name] = (k, p)
		g = groups.setdefault(
			k,
			{
				"dispatched": 0, "delivered": 0, "rto": 0, "_days": 0.0, "_days_n": 0,
				"_lag": 0.0, "_lag_n": 0, "paid_lines": 0, "short_lines": 0, "short_pay_value": 0.0,
				"_charges": 0.0, "cash_locked": 0.0,
			},
		)  # fmt: skip
		g["dispatched"] += 1
		if p.status == "RTO":
			g["rto"] += 1
		if p.status == "Delivered":
			g["delivered"] += 1
			if p.delivered_date and p.order_date:
				g["_days"] += max(date_diff(p.delivered_date, getdate(p.order_date)), 0)
				g["_days_n"] += 1
			if p.payout_status not in ("Paid", "Short-paid"):
				g["cash_locked"] += flt(p.cod_amount)

	for line in _paid_lines(start, end):
		if line.cod_parcel not in owner:
			continue
		k, p = owner[line.cod_parcel]
		g = groups[k]
		g["paid_lines"] += 1
		g["_charges"] += flt(line.freight) + flt(line.cod_fee) + flt(line.gst)
		short = flt(line.expected_net) - flt(line.net_paid)
		if short > 0:
			g["short_lines"] += 1
			g["short_pay_value"] += short
		if p.delivered_date and line.remittance_date:
			g["_lag"] += date_diff(line.remittance_date, p.delivered_date)
			g["_lag_n"] += 1

	out = {}
	for k, g in groups.items():
		# RTO charges are not stored on the parcel and are not part of the paid-line cost here,
		# so cost_per_delivered excludes them.
		cost = g["_charges"] + g["short_pay_value"]
		out[k] = {
			"dispatched": g["dispatched"],
			"delivered": g["delivered"],
			"rto": g["rto"],
			"delivery_rate": _div(g["delivered"], g["dispatched"]),
			"rto_rate": _div(g["rto"], g["dispatched"]),
			"avg_delivery_days": _avg(g["_days"], g["_days_n"]),
			"avg_payout_lag_days": _avg(g["_lag"], g["_lag_n"]),
			"short_pay_rate": _div(g["short_lines"], g["paid_lines"]),
			"short_pay_value": round(g["short_pay_value"], 2),
			"cost_per_delivered": _avg(cost, g["delivered"], 2),
			"cash_locked": round(g["cash_locked"], 2),
			"low_sample": g["dispatched"] < MIN_PARCELS,
			"score": None,
		}
	_score(out)
	return out


def _normalise(values, higher_is_better):
	"""{key: 0..1} min-max across groups; groups without the metric get NEUTRAL."""
	known = {k: v for k, v in values.items() if v is not None}
	lo, hi = (min(known.values()), max(known.values())) if known else (0, 0)
	out = {}
	for k, v in values.items():
		if v is None:
			out[k] = NEUTRAL
		elif hi == lo:
			out[k] = 1.0
		else:
			n = (v - lo) / (hi - lo)
			out[k] = n if higher_is_better else 1 - n
	return out


def _score(metrics):
	ranked = {k: m for k, m in metrics.items() if not m["low_sample"]}
	if not ranked:
		return
	spec = (
		("delivery_rate", True, W_DELIVERY_RATE),
		("rto_rate", False, W_LOW_RTO),
		("cost_per_delivered", False, W_LOW_COST),
		("avg_delivery_days", False, W_SPEED),
		("avg_payout_lag_days", False, W_PAYOUT_LAG),
	)
	total = {k: 0.0 for k in ranked}
	for field, higher, weight in spec:
		for k, n in _normalise({k: m[field] for k, m in ranked.items()}, higher).items():
			total[k] += n * weight
	for k, s in total.items():
		ranked[k]["score"] = round(s * SCORE_MAX)


@frappe.whitelist()
def get_courier_performance(from_date=None, to_date=None, group_by="courier"):
	"""Per courier (or courier + pincode zone) delivery, RTO, payout and cost metrics with a 0-100 score,
	plus the same metrics for the previous period of equal length. Read role."""
	frappe.only_for(READ_ROLES)
	if group_by not in GROUP_BYS:
		frappe.throw(frappe._("group_by must be courier or courier_zone"))
	end = getdate(to_date) if to_date else getdate(nowdate())
	start = getdate(from_date) if from_date else add_days(end, -(DEFAULT_DAYS - 1))
	if start > end:
		frappe.throw(frappe._("From date is after to date"))
	days = date_diff(end, start) + 1
	prev_end = add_days(start, -1)
	prev_start = add_days(prev_end, -(days - 1))

	current = _period(start, end, group_by)
	previous = _period(prev_start, prev_end, group_by)

	rows = []
	for (courier, zone), m in current.items():
		row = {"courier": courier, "zone": zone, **m, "is_best": False}
		row["previous"] = previous.get((courier, zone))
		rows.append(row)
	rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), -r["dispatched"]))

	best_by_zone = {}
	if group_by == "courier_zone":
		for r in rows:  # sorted by score, so the first ranked row of a zone is its best
			if r["score"] is not None and r["zone"] not in best_by_zone:
				best_by_zone[r["zone"]] = r["courier"]
				r["is_best"] = True

	return {
		"group_by": group_by,
		"from_date": str(start),
		"to_date": str(end),
		"previous_from_date": str(prev_start),
		"previous_to_date": str(prev_end),
		"min_parcels": MIN_PARCELS,
		"rows": rows,
		"best_by_zone": best_by_zone,
	}
