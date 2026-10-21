"""CODSync UI API: whitelisted endpoints for the COD Ledger screens.

"Order" in the UI is a COD Parcel (its name is the order id). Statuses, expected values,
the timeline and exceptions come from codsync.codsync.engine. Money is returned as numbers;
datetimes as "YYYY-MM-DD HH:MM:SS" strings. Contract: docs/API_CONTRACT.md
"""

import json
from urllib.parse import quote

import frappe
import frappe.sessions
from frappe import _
from frappe.utils import (
	add_days,
	cint,
	date_diff,
	flt,
	get_datetime,
	getdate,
	now_datetime,
	nowdate,
	pretty_date,
)

from codsync.codsync import engine
from codsync.codsync.platforms import get_platform

READ_ROLES = ("CODSync Manager", "CODSync Operator", "CODSync Viewer", "System Manager")
WRITE_ROLES = ("CODSync Manager", "CODSync Operator", "System Manager")

STATUSES = ("Reconciled", "Pending", "Mismatch", "Exception")
EXC_TYPES = (
	"Unexpected deduction",
	"Amount mismatch",
	"Missing settlement",
	"Missing AWB",
	"Tracking mismatch",
	"Unknown AWB",
	"Duplicate AWB",
)
SETTLED = ("Paid", "Short-paid")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read():
	frappe.only_for(READ_ROLES)


def _write():
	frappe.only_for(WRITE_ROLES)


def _dt(value):
	return get_datetime(value).strftime("%Y-%m-%d %H:%M:%S") if value else None


def _d(value):
	return str(getdate(value)) if value else None


def _since(period):
	"""Start date for a period key (7d / 30d / 90d / month); default 30d."""
	today = getdate(nowdate())
	if period == "month":
		return today.replace(day=1)
	days = {"7d": 7, "30d": 30, "90d": 90}.get(period or "30d", 30)
	return add_days(today, -days)


def _json(value, default=None):
	if isinstance(value, str):
		try:
			return json.loads(value) if value.strip() else default
		except ValueError:
			return default
	return value if value is not None else default


def _sort_key(value):
	if value is None:
		return (2, 0)
	if isinstance(value, (int, float)):
		return (0, value)
	return (1, str(value).lower())


def _paginate(rows, page=1, page_size=20, sort=None, search=None, search_keys=()):
	if search:
		q = str(search).strip().lower()
		rows = [r for r in rows if any(q in str(r.get(k) or "").lower() for k in search_keys)]
	if sort:
		sort = str(sort).strip()
		desc = sort.startswith("-") or sort.lower().endswith(" desc")
		field = sort.lstrip("-").split(" ")[0]
		rows = sorted(rows, key=lambda r: _sort_key(r.get(field)), reverse=desc)
	total = len(rows)
	page, page_size = max(cint(page) or 1, 1), max(cint(page_size) or 20, 1)
	start = (page - 1) * page_size
	return {"rows": rows[start : start + page_size], "total": total}


def _mask_phone(phone):
	digits = "".join(c for c in (phone or "") if c.isdigit())[-10:]
	return f"+91 {digits[:2]}xxxxx{digits[-3:]}" if len(digits) == 10 else (phone or "")


PARCEL_FIELDS = [
	"name",
	"order_id",
	"awb",
	"courier",
	"customer_name",
	"phone",
	"city",
	"pincode",
	"address",
	"email",
	"cod_amount",
	"order_total",
	"payment_mode",
	"status",
	"order_status",
	"platform",
	"external_id",
	"delivered_date",
	"payout_status",
	"expected_settlement",
	"actual_settlement",
	"difference",
	"settlement_batch",
	"declared_weight",
	"charged_weight",
	"last_event",
	"last_event_at",
	"order_date",
	"creation",
]


def _open_exceptions(courier=None):
	filters = {"status": "Open"}
	if courier:
		filters["courier"] = courier
	return frappe.get_all(
		"COD Exception",
		filters=filters,
		order_by="creation desc",
		limit_page_length=0,
		fields=[
			"name",
			"exception_type",
			"cod_parcel",
			"awb",
			"courier",
			"detail",
			"impact",
			"opened_on",
			"creation",
			"assignee",
			"status",
			"line_ref",
			"settlement_batch",
		],
	)


def _orders(courier=None, since=None, until=None, names=None):
	"""All parcels with derived statuses (delivery / COD / reconciliation)."""
	filters = {"courier": courier} if courier else {}
	if names:
		filters["name"] = ["in", list(names)]
	parcels = frappe.get_all("COD Parcel", filters=filters, fields=PARCEL_FIELDS, limit_page_length=0)
	open_types = {}
	for e in _open_exceptions():
		if e.cod_parcel:
			open_types.setdefault(e.cod_parcel, set()).add(e.exception_type)
	out = []
	for p in parcels:
		p.date = get_datetime(p.order_date or p.creation)
		if since and p.date.date() < getdate(since):
			continue
		if until and p.date.date() > getdate(until):
			continue
		p.open_types = open_types.get(p.name, set())
		p.amount = flt(p.order_total or p.cod_amount)
		p.delivery_status = engine.delivery_status(p)
		p.cod_status = engine.cod_status(p)
		p.reconciliation_status = engine.reconciliation_status(p, p.open_types)
		out.append(p)
	return out


def _is_cod(p):
	return p.payment_mode != "Prepaid"


def _batch_info(batches):
	"""{name: {utr, date, source, status}} for settlement batch names."""
	names = [b for b in set(batches) if b]
	if not names:
		return {}
	rows = frappe.get_all(
		"Courier Remittance",
		filters={"name": ["in", names]},
		fields=["name", "utr_number", "remittance_date", "source", "batch_status"],
	)
	return {r.name: r for r in rows}


def _tolerance():
	return engine.get_tolerance()


# ---------------------------------------------------------------------------
# boot / search
# ---------------------------------------------------------------------------


@frappe.whitelist()
def csrf_token():
	"""CSRF token of the current logged-in session (Guests get 403). Used by the dev server."""
	return frappe.sessions.get_csrf_token()


@frappe.whitelist()
def couriers(active_only: int = 0):
	"""Courier cards (see API_CONTRACT). active_only=1 lists active couriers only. Read role."""
	_read()
	counts = dict(
		frappe.db.sql(
			"select courier, count(*) from `tabCOD Parcel` where courier is not null group by courier"
		)
	)
	saved_keys = set(
		frappe.db.sql_list(
			"select name from `__Auth` where doctype='Courier' and fieldname='api_key' and password != ''"
		)
	)
	out = []
	for c in frappe.get_all(
		"Courier",
		fields=["*"],
		filters={"is_active": 1} if cint(active_only) else {},
		order_by="courier_name asc",
		limit_page_length=0,
	):
		secs = int(frappe.utils.time_diff_in_seconds(str(c.settlement_sync_time or "09:00:00"), "00:00:00"))
		hhmm = f"{secs // 3600:02d}:{secs % 3600 // 60:02d}"
		words = (c.courier_name or "").split()
		out.append(
			{
				"name": c.name,
				"display_name": c.courier_name,
				"is_active": bool(c.is_active),
				"initials": "".join(w[0] for w in words[:2]).upper() or (c.courier_name or "?")[:2].upper(),
				"status": c.connection_status or "Not connected",
				"tracking_provider": c.tracking_provider,
				"settlement_via": c.settlement_via,
				"tracking_enabled": bool(c.tracking_sync_enabled),
				"tracking_every": f"{cint(c.tracking_interval_min) or 30} min",
				"tracking_interval_min": cint(c.tracking_interval_min) or 30,
				"last_tracking": _dt(c.last_tracking_sync),
				"settlement_enabled": bool(c.settlement_sync_enabled),
				"settlement_schedule": f"Daily {hhmm}",
				"settlement_time": hhmm,
				"last_settlement": _dt(c.last_settlement_sync),
				"orders_synced": counts.get(c.name, 0),
				"error": c.last_error or None,
				"payout_cycle_days": cint(c.payout_cycle_days),
				"cod_fee_percent": flt(c.cod_fee_percent),
				"gst_percent": flt(c.gst_percent),
				"base_weight_kg": flt(c.base_weight_kg),
				"base_freight": flt(c.base_freight),
				"additional_freight_per_kg": flt(c.additional_freight_per_kg),
				"api_key_saved": c.name in saved_keys,
				"parcels_mapping": _json(c.parcels_mapping, {}) or {},
				"remittance_mapping": _json(c.remittance_mapping, {}) or {},
			}
		)
	return out


COURIER_PROVIDERS = ("Mock", "Ship24")
COURIER_VIA = ("", "API", "Excel")


def _validate_courier_mapping(value, label):
	if isinstance(value, str) and value.strip():
		try:
			json.loads(value)
		except ValueError:
			frappe.throw(_("{0} is not valid JSON").format(label))
	m = _json(value, {}) or {}
	if isinstance(m, list):
		m = {r.get("file_column"): r.get("field") for r in m if r.get("file_column") and r.get("field")}
	if not isinstance(m, dict) or any(not isinstance(v, str) for v in m.values()):
		frappe.throw(_("{0} must be a JSON object of file column to field").format(label))
	return json.dumps(m)


@frappe.whitelist()
def save_courier(name: str | None = None, values: dict | str | None = None, api_key: str | None = None):
	"""Create (no name) or update a courier. `values` may hold courier_name (create only), is_active,
	payout_cycle_days, cod_fee_percent, gst_percent, base_weight_kg, base_freight, additional_freight_per_kg,
	tracking_provider, tracking_sync_enabled, tracking_interval_min, settlement_via, settlement_sync_enabled,
	settlement_sync_time, parcels_mapping, remittance_mapping. `api_key` is write-only; empty keeps the saved one.
	Returns the saved courier card. Manager role."""
	_manager()
	v = _json(values, {}) or {}
	if name:
		doc = frappe.get_doc("Courier", name)
	else:
		cname = (v.get("courier_name") or "").strip()
		if not cname:
			frappe.throw(_("Courier name is required"))
		if frappe.db.exists("Courier", cname):
			frappe.throw(_("Courier {0} already exists").format(cname))
		doc = frappe.new_doc("Courier")
		doc.courier_name = cname
	for f in ("payout_cycle_days", "tracking_interval_min"):
		if f in v:
			n = cint(v[f])
			if n < 1:
				frappe.throw(_("{0} must be at least 1").format(doc.meta.get_label(f)))
			doc.set(f, n)
	for f in (
		"cod_fee_percent",
		"gst_percent",
		"base_weight_kg",
		"base_freight",
		"additional_freight_per_kg",
	):
		if f in v:
			n = flt(v[f])
			if n < 0:
				frappe.throw(_("{0} cannot be negative").format(doc.meta.get_label(f)))
			doc.set(f, n)
	for f in ("is_active", "tracking_sync_enabled", "settlement_sync_enabled"):
		if f in v:
			doc.set(f, 1 if cint(v[f]) else 0)
	if "tracking_provider" in v:
		if v["tracking_provider"] not in COURIER_PROVIDERS:
			frappe.throw(_("Unknown tracking provider"))
		doc.tracking_provider = v["tracking_provider"]
	if "settlement_via" in v:
		if (v["settlement_via"] or "") not in COURIER_VIA:
			frappe.throw(_("Settlement via must be API or Excel"))
		doc.settlement_via = v["settlement_via"] or None
	if v.get("settlement_sync_time"):
		doc.settlement_sync_time = v["settlement_sync_time"]
	for f, label in (("parcels_mapping", "Parcels mapping"), ("remittance_mapping", "Remittance mapping")):
		if f in v:
			doc.set(f, _validate_courier_mapping(v[f], label))
	key = (api_key or "").strip()
	if key:
		doc.api_key = key
		doc.connection_status = "Not connected"  # a new key must be tested again
	elif not doc.connection_status:
		doc.connection_status = "Not connected"
	doc.save()
	return next(c for c in couriers() if c["name"] == doc.name)


@frappe.whitelist()
def test_courier(name: str):
	"""Check the courier's tracking provider with its saved key; sets Connected / Action needed and last_error.
	Mock always connects. Manager role."""
	_manager()
	doc = frappe.get_doc("Courier", name)
	ok, message = True, _("Connection OK")
	if doc.tracking_provider == "Ship24":
		key = doc.get_password("api_key", raise_exception=False)
		if not key:
			ok, message = False, _("No API key saved")
		else:
			import requests

			try:
				r = requests.get(
					"https://api.ship24.com/public/v1/couriers",
					headers={"Authorization": f"Bearer {key}"},
					timeout=15,
				)
				if r.status_code in (401, 403):
					ok, message = False, _("The provider rejected the API key")
				elif not r.ok:
					ok, message = False, _("The provider answered with HTTP {0}").format(r.status_code)
			except requests.RequestException:
				ok, message = False, _("Could not reach the provider")
	frappe.db.set_value(
		"Courier",
		doc.name,
		{"connection_status": "Connected" if ok else "Action needed", "last_error": None if ok else message},
		update_modified=False,
	)
	from codsync.codsync.synclog import log_sync

	log_sync(
		"Courier",
		"Test Connection",
		"Success" if ok else "Failed",
		reference_doctype="Courier",
		reference_name=doc.name,
		error_message=None if ok else message,
	)
	return {"ok": ok, "message": message, "status": "Connected" if ok else "Action needed"}


@frappe.whitelist()
def boot():
	_read()
	conn = frappe.get_cached_doc("Store Connection")
	stamps = [conn.last_synced_on]
	for c in frappe.get_all("Courier", fields=["last_tracking_sync", "last_settlement_sync"]):
		stamps += [c.last_tracking_sync, c.last_settlement_sync]
	stamps = [get_datetime(s) for s in stamps if s]
	return {
		"user": {
			"name": frappe.session.user,
			"full_name": frappe.utils.get_fullname(),
			"roles": [r for r in frappe.get_roles() if r.startswith("CODSync") or r == "System Manager"],
		},
		"store_name": conn.store_name or "Vanam Organics",
		"last_synced_at": _dt(max(stamps)) if stamps else None,
		"open_exception_count": frappe.db.count("COD Exception", {"status": "Open"}),
		"tolerance": _tolerance(),
	}


@frappe.whitelist()
def global_search(q: str):
	"""Find orders (id / customer / AWB) and settlements (batch / UTR)."""
	_read()
	q = (q or "").strip()
	if len(q) < 2:
		return []
	like = f"%{q}%"
	out = []
	for p in frappe.db.sql(
		"""select name, customer_name, awb from `tabCOD Parcel`
		where name like %(q)s or customer_name like %(q)s or awb like %(q)s
		order by modified desc limit 10""",
		{"q": like},
		as_dict=True,
	):
		kind = (
			"shipment" if q.lower() in (p.awb or "").lower() and q.lower() not in p.name.lower() else "order"
		)
		label = f"{p.name} · {p.customer_name or ''}".strip(" ·")
		if kind == "shipment":
			label = f"{p.awb} · {p.name}"
		out.append({"type": kind, "label": label, "route": f"/orders/{quote(p.name, safe='')}"})
	for r in frappe.db.sql(
		"""select name, utr_number from `tabCourier Remittance`
		where docstatus = 1 and (name like %(q)s or utr_number like %(q)s)
		order by remittance_date desc limit 10""",
		{"q": like},
		as_dict=True,
	):
		out.append(
			{
				"type": "settlement",
				"label": f"{r.name} · {r.utr_number or ''}".strip(" ·"),
				"route": f"/settlements/{quote(r.name, safe='')}",
			}
		)
	return out


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@frappe.whitelist()
def overview(period: str = "30d", courier: str | None = None):
	_read()
	rows = _orders(courier, since=_since(period))
	cod = [p for p in rows if _is_cod(p) and p.delivery_status != "Cancelled"]
	today = getdate(nowdate())

	delivered = [p for p in cod if p.status == "Delivered"]
	settled = [p for p in delivered if p.payout_status in SETTLED]
	pending = [p for p in delivered if p.payout_status not in SETTLED]
	reconciled = [p for p in cod if p.reconciliation_status == "Reconciled"]
	kpis = {
		"cod_orders": len(cod),
		"total_orders": len(rows),
		"expected_cod": flt(sum(flt(p.cod_amount) for p in cod), 2),
		"collected_amount": flt(sum(flt(p.cod_amount) for p in delivered), 2),
		"delivered_count": len([p for p in rows if p.status == "Delivered"]),
		"settled_amount": flt(sum(flt(p.actual_settlement) for p in settled), 2),
		"settled_orders": len(settled),
		"pending_amount": flt(sum(flt(p.cod_amount) for p in pending), 2),
		"pending_orders": len(pending),
		"oldest_pending_days": max(
			(date_diff(today, p.delivered_date) for p in pending if p.delivered_date), default=0
		),
		"reconciled_count": len(reconciled),
		"reconciled_pct": flt(len(reconciled) * 100 / len(cod), 1) if cod else 0,
		"unreconciled_count": len(cod) - len(reconciled),
		"mismatch_count": len([p for p in cod if p.reconciliation_status == "Mismatch"]),
		"exception_count": len([p for p in cod if p.reconciliation_status == "Exception"]),
	}
	summary = {
		"orders": len(rows),
		"awb_assigned": len([p for p in rows if p.awb]),
		"delivered": len([p for p in rows if p.status == "Delivered"]),
		"cod_collected": len([p for p in cod if p.cod_status in ("Collected", "Settled")]),
		"settled": len([p for p in cod if p.cod_status == "Settled"]),
		"reconciled": len(reconciled),
	}
	status_table = []
	for st in STATUSES:
		group = [p for p in cod if p.reconciliation_status == st]
		status_table.append(
			{
				"status": st,
				"orders": len(group),
				"cod_value": flt(sum(flt(p.cod_amount) for p in group), 2),
				"difference": flt(sum(flt(p.difference) for p in group), 2),
			}
		)

	exceptions = _open_exceptions(courier)
	top = sorted(exceptions, key=lambda e: abs(flt(e.impact)), reverse=True)[:5]
	open_exceptions = {
		"rows": [_exception_row(e) | {"order": e.cod_parcel} for e in top],
		"total_open": len(exceptions),
	}

	batches = frappe.get_all(
		"Courier Remittance",
		filters={"docstatus": 1, **({"courier": courier} if courier else {})},
		fields=[
			"name",
			"courier",
			"remittance_date",
			"orders_count",
			"total_cod",
			"total_net_paid",
			"batch_status",
			"utr_number",
		],
		order_by="remittance_date desc, creation desc",
		limit_page_length=5,
	)
	recent = [
		{
			"batch": b.name,
			"courier": b.courier,
			"date": _d(b.remittance_date),
			"orders": cint(b.orders_count),
			"cod_amount": flt(b.total_cod, 2),
			"deductions": flt(flt(b.total_cod) - flt(b.total_net_paid), 2),
			"net": flt(b.total_net_paid, 2),
			"status": b.batch_status,
			"utr": b.utr_number,
		}
		for b in batches
	]

	banner = [
		{"courier": c.name, "last_error": c.last_error, "time": _dt(c.last_settlement_sync)}
		for c in frappe.get_all(
			"Courier",
			filters={"connection_status": "Action needed"},
			fields=["name", "last_error", "last_settlement_sync"],
		)
	]
	return {
		"banner": banner,
		"kpis": kpis,
		"summary": summary,
		"status_table": status_table,
		"open_exceptions": open_exceptions,
		"recent_settlements": recent,
	}


def _exception_row(e):
	opened = e.opened_on or e.creation
	return {
		"name": e.name,
		"type": e.exception_type,
		"order_id": e.cod_parcel,
		"awb": e.awb,
		"courier": e.courier,
		"detail": e.detail,
		"impact": flt(e.impact, 2),
		"age_days": max(date_diff(nowdate(), getdate(opened)), 0) if opened else 0,
		"assignee": e.assignee,
	}


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def _order_row(p):
	return {
		"order_id": p.name,
		"date": _dt(p.date),
		"customer": p.customer_name,
		"amount": flt(p.amount, 2),
		"payment_mode": p.payment_mode,
		"awb": p.awb,
		"awb_missing": bool(not p.awb and p.order_status == "Fulfilled"),
		"courier": p.courier,
		"delivery_status": p.delivery_status,
		"cod_status": p.cod_status,
		"reconciliation_status": p.reconciliation_status,
	}


@frappe.whitelist()
def orders(
	tab: str = "All",
	courier: str | None = None,
	delivery_status: str | None = None,
	cod_status: str | None = None,
	reconciliation: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	search: str | None = None,
	sort: str = "date desc",
	page: int = 1,
	page_size: int = 20,
):
	_read()
	rows = _orders(courier, since=from_date, until=to_date)
	if delivery_status:
		rows = [p for p in rows if p.delivery_status == delivery_status]
	if cod_status:
		rows = [p for p in rows if p.cod_status == cod_status]
	if reconciliation:
		rows = [p for p in rows if p.reconciliation_status == reconciliation]

	tabs = {
		"All": lambda p: True,
		"COD": _is_cod,
		"Prepaid": lambda p: not _is_cod(p),
		"Unreconciled": lambda p: _is_cod(p)
		and p.reconciliation_status != "Reconciled"
		and p.delivery_status != "Cancelled",
		"Exceptions": lambda p: p.reconciliation_status == "Exception",
	}
	counts = {name: len([p for p in rows if fn(p)]) for name, fn in tabs.items()}
	selected = [_order_row(p) for p in rows if tabs.get(tab, tabs["All"])(p)]
	result = _paginate(selected, page, page_size, sort, search, ("order_id", "customer", "awb", "courier"))
	result["counts"] = counts
	return result


def _line_for(parcel):
	rows = frappe.db.sql(
		"""select l.*, r.name as batch, r.remittance_date, r.utr_number, r.source, r.batch_status, r.file_name
		from `tabRemittance Line` l join `tabCourier Remittance` r on r.name = l.parent
		where l.cod_parcel = %s and r.docstatus = 1
		order by r.remittance_date desc, r.creation desc limit 1""",
		parcel,
		as_dict=True,
	)
	return rows[0] if rows else None


def _settlement_block(p, doc, line):
	if p.payment_mode == "Prepaid":
		return None
	courier = frappe.get_cached_doc("Courier", p.courier) if p.courier else None
	exp = engine.expected_for(doc, line)
	pct = flt(courier.cod_fee_percent) if courier else 0
	has = line is not None

	def row(label, note, expected, actual, unexpected=False):
		diff = flt(actual - expected, 2) if actual is not None else None
		return {
			"label": label,
			"note": note,
			"expected": flt(expected, 2),
			"actual": flt(actual, 2) if actual is not None else None,
			"difference": diff,
			"unexpected": unexpected,
		}

	lines = [
		row(
			"COD amount",
			"Collected from customer",
			flt(p.cod_amount),
			(flt(line.cod_amount) or flt(p.cod_amount)) if has else None,
		),
		row(
			f"COD handling fee ({pct:g}%)",
			f"{pct:g}% of COD amount",
			-exp["expected_cod_fee"],
			-flt(line.cod_fee) if has else None,
		),
		row(
			"Forward freight",
			f"Rate card, {flt(p.declared_weight):g} kg",
			-exp["expected_freight"],
			-flt(line.freight) if has else None,
		),
	]
	if exp["expected_gst"] or (has and flt(line.gst)):
		lines.append(row("GST", "On fee and freight", -exp["expected_gst"], -flt(line.gst) if has else None))
	if has:
		for field, label in engine._UNEXPECTED_LABELS:
			if flt(line.get(field)) > 0:
				lines.append(row(label, "Not on rate card", 0, -flt(line.get(field)), True))
	lines.append(
		row(
			"Net settlement",
			"Amount paid out",
			exp["expected_settlement"],
			flt(line.net_paid) if has else None,
		)
	)
	net = lines[-1]
	return {
		"expected": net["expected"],
		"actual": net["actual"],
		"difference": net["difference"],
		"lines": lines,
	}


def _order_url(doc):
	"""Link to the order on its platform, derived from platform + external_id."""
	if doc.platform in ("Shopify", "WooCommerce", "Odoo") and doc.external_id:
		conn = frappe.get_cached_doc("Store Connection")
		try:
			return get_platform(doc.platform).order_url(doc.external_id, conn)
		except NotImplementedError:
			return None
	return None


@frappe.whitelist()
def order_detail(order_id: str):
	_read()
	if not frappe.db.exists("COD Parcel", order_id):
		frappe.throw(_("Order {0} not found").format(order_id), frappe.DoesNotExistError)
	doc = frappe.get_doc("COD Parcel", order_id)
	p = next(iter(_orders_for([doc.name])), None)
	line = _line_for(doc.name)
	exc_open = frappe.get_all(
		"COD Exception", filters={"cod_parcel": doc.name, "status": "Open"}, fields=["name", "exception_type"]
	)
	batch = line

	header = {
		"order_id": doc.name,
		"amount": flt(p.amount, 2),
		"customer": doc.customer_name,
		"badges": {
			"payment_mode": doc.payment_mode,
			"delivery_status": p.delivery_status,
			"cod_status": p.cod_status,
			"reconciliation_status": p.reconciliation_status,
		},
		"placed_at": _dt(p.date),
		"channel": doc.platform or "Online Store",
		"order_url": _order_url(doc),
	}

	delivered_ev = next(
		(e for e in doc.tracking_events or [] if (e.status or "").lower() == "delivered"), None
	)
	delivered_at = _dt(delivered_ev.event_time) if delivered_ev else _dt(doc.delivered_date)
	cod = _is_cod(doc)
	settled = doc.payout_status in SETTLED
	rec = p.reconciliation_status
	journey = [
		{
			"key": "placed",
			"title": "Order placed",
			"state": "done",
			"lines": [_dt(p.date), f"{doc.payment_mode} · {flt(p.amount):g}"],
		},
		{
			"key": "shipment",
			"title": "Shipment / AWB",
			"state": "done" if doc.awb else ("warn" if doc.order_status == "Fulfilled" else "pending"),
			"lines": [f"{doc.courier or '-'}", f"AWB {doc.awb}" if doc.awb else "No AWB assigned"],
		},
		{
			"key": "delivered",
			"title": "Delivered",
			"state": "done"
			if doc.status == "Delivered"
			else (
				"warn" if p.delivery_status in ("RTO initiated", "RTO delivered", "Cancelled") else "pending"
			),
			"lines": [delivered_at or "Not delivered yet", p.delivery_status],
		},
		{
			"key": "collected",
			"title": "COD collected",
			"state": "done" if (not cod or p.cod_status in ("Collected", "Settled")) else "pending",
			"lines": ["Prepaid order" if not cod else f"{flt(doc.cod_amount):g} to collect", p.cod_status],
		},
		{
			"key": "settled",
			"title": "Settled",
			"state": "done" if settled else ("warn" if doc.payout_status == "Missing" else "pending"),
			"lines": [
				f"Batch {doc.settlement_batch}, UTR {batch.utr_number}" if batch else "Awaiting settlement",
				_d(batch.remittance_date) if batch else (doc.payout_status or ""),
			],
		},
		{
			"key": "reconciliation",
			"title": "Reconciliation",
			"state": "done"
			if rec == "Reconciled"
			else ("warn" if rec in ("Mismatch", "Exception") else "pending"),
			"lines": [
				rec or "Not applicable",
				f"{e.exception_type} ({e.name})"
				if (e := next(iter(exc_open), None))
				else ("Within tolerance" if rec == "Reconciled" else ""),
			],
		},
	]

	weight_callout = None
	if flt(doc.charged_weight) > flt(doc.declared_weight):
		by = _d(add_days(batch.remittance_date, 7)) if batch else None
		weight_callout = {
			"declared": flt(doc.declared_weight),
			"charged": flt(doc.charged_weight),
			"text": f"Courier charged {flt(doc.charged_weight):g} kg against a declared "
			f"{flt(doc.declared_weight):g} kg. Weight disputes can be raised within 7 days of settlement"
			+ (f" (by {by})." if by else "."),
		}

	actions = ["add_note"]
	if doc.awb:
		actions.append("refresh_tracking")
	if exc_open:
		actions += ["view_exception", "resolve_exception"]
	if doc.payout_status in ("Short-paid", "Missing"):
		actions.append("raise_dispute")

	return {
		"header": header,
		"journey": journey,
		"settlement": _settlement_block(p, doc, line),
		"weight_callout": weight_callout,
		"customer": {
			"name": doc.customer_name,
			"phone": _mask_phone(doc.phone),
			"address": ", ".join(x for x in (doc.address, doc.city, doc.pincode) if x),
		},
		"shipment": {
			"courier": doc.courier,
			"awb": doc.awb,
			"declared_weight": flt(doc.declared_weight),
			"charged_weight": flt(doc.charged_weight),
			"delivery_status": p.delivery_status,
		},
		"settlement_card": (
			{
				"batch": batch.batch,
				"settled_on": _d(batch.remittance_date),
				"utr": batch.utr_number,
				"source": batch.source,
				"status": batch.batch_status,
			}
			if batch
			else None
		),
		"activity": [a | {"event_time": _dt(a["event_time"])} for a in engine.timeline(doc.name)],
		"actions": actions,
	}


@frappe.whitelist()
def add_note(order_id: str, text: str):
	"""Add a Comment to the order. Write role."""
	_write()
	text = (text or "").strip()
	if not text:
		frappe.throw(_("Note cannot be empty"))
	return engine.add_note(order_id, text)


@frappe.whitelist()
def raise_dispute(order_id: str):
	"""Open (or reuse) the order's exception and mark the dispute as raised. Write role."""
	_write()
	if not frappe.db.exists("COD Parcel", order_id):
		frappe.throw(_("Order {0} not found").format(order_id), frappe.DoesNotExistError)
	name = engine.raise_dispute(order_id)
	engine.add_note(order_id, _("Dispute raised ({0})").format(name))
	return {"exception": name}


@frappe.whitelist()
def resolve_order(order_id: str, note: str | None = None):
	"""Close the order's open exceptions as Resolved manually. Write role."""
	_write()
	names = frappe.get_all("COD Exception", filters={"cod_parcel": order_id, "status": "Open"}, pluck="name")
	if not names:
		frappe.throw(_("This order has no open exceptions"))
	for n in names:
		exc = frappe.get_doc("COD Exception", n)
		exc.status = "Resolved"
		exc.resolution = exc.resolution or "Resolved manually"
		if note:
			exc.resolution_note = note
		exc.save(ignore_permissions=True)
	engine.add_note(order_id, _("Marked resolved ({0})").format(", ".join(names)))
	return {"resolved": names}


def _orders_for(names):
	return _orders(names=names)


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------

SHIPMENT_STATUSES = ("Booked", "In Transit", "Delivered", "RTO", "Cancelled")


@frappe.whitelist()
def shipments(
	status: str = "All",
	courier: str | None = None,
	search: str | None = None,
	sort: str = "last_event_at desc",
	page: int = 1,
	page_size: int = 20,
):
	"""Shipment list: every COD Parcel with an AWB, filterable by shipment status."""
	_read()
	rows = [p for p in _orders(courier) if p.awb]
	counts = {"All": len(rows)}
	for st in SHIPMENT_STATUSES:
		counts[st] = len([p for p in rows if p.status == st])
	if status in SHIPMENT_STATUSES:
		rows = [p for p in rows if p.status == status]
	out = [
		{
			"awb": p.awb,
			"order_id": p.name,
			"courier": p.courier,
			"status": p.status,
			"delivery_status": p.delivery_status,
			"last_event": p.last_event or p.delivery_status,
			"last_event_at": _dt(p.last_event_at),
			"updated_ago": pretty_date(p.last_event_at) if p.last_event_at else None,
			"declared_weight": flt(p.declared_weight),
			"charged_weight": flt(p.charged_weight),
			"delivered_date": _d(p.delivered_date),
			"cod_amount": flt(p.cod_amount, 2),
			"order_status": p.order_status,
			"status_check": "Mismatch" if "Tracking mismatch" in p.open_types else "OK",
		}
		for p in rows
	]
	result = _paginate(out, page, page_size, sort, search, ("awb", "order_id", "courier"))
	stamps = [
		c.last_tracking_sync
		for c in frappe.get_all("Courier", fields=["last_tracking_sync"])
		if c.last_tracking_sync
	]
	result["counts"] = counts
	result["last_synced"] = _dt(max(stamps)) if stamps else None
	return result


@frappe.whitelist()
def shipment_detail(order_id: str):
	"""One shipment for the drawer: parcel summary + tracking events timeline."""
	_read()
	if not frappe.db.exists("COD Parcel", order_id):
		frappe.throw(_("Order {0} not found").format(order_id), frappe.DoesNotExistError)
	doc = frappe.get_doc("COD Parcel", order_id)
	return {
		"order_id": doc.name,
		"awb": doc.awb,
		"courier": doc.courier,
		"status": doc.status,
		"delivery_status": engine.delivery_status(doc.as_dict()),
		"order_status": doc.order_status,
		"payment_mode": doc.payment_mode,
		"cod_amount": flt(doc.cod_amount, 2),
		"payout_status": doc.payout_status,
		"declared_weight": flt(doc.declared_weight),
		"charged_weight": flt(doc.charged_weight),
		"delivered_date": _d(doc.delivered_date),
		"last_event": doc.last_event,
		"last_event_at": _dt(doc.last_event_at),
		"tracking_events": [
			{"event_time": _dt(e.event_time), "status": e.status or "", "location": e.location or ""}
			for e in doc.tracking_events or []
		],
	}


@frappe.whitelist()
def sync_tracking():
	"""Refresh tracking for every open shipment, per courier (one Sync Log row each); returns the number refreshed."""
	_write()
	from codsync.codsync.tracking import sync_tracking as sync_courier

	couriers = frappe.get_all(
		"COD Parcel",
		pluck="courier",
		distinct=True,
		filters={"status": ["in", ["Booked", "In Transit"]], "awb": ["is", "set"], "courier": ["is", "set"]},
	)
	done = 0
	for c in couriers:
		r = sync_courier(courier=c)
		done += r["checked"] - r["failed"]
	return done


@frappe.whitelist()
def webhook_url():
	_read()
	return {"url": frappe.utils.get_url("/api/method/codsync.codsync.api.webhook")}


RECON_STATES = ("Paid", "Short-paid", "Awaiting payout", "Missing", "Unknown")


@frappe.whitelist()
def remittance_batches():
	"""Submitted settlement batches for the Run matching selector."""
	_read()
	return [
		{
			"name": b.name,
			"courier": b.courier,
			"date": _d(b.remittance_date),
			"orders": cint(b.orders_count),
			"status": b.batch_status,
		}
		for b in frappe.get_all(
			"Courier Remittance",
			filters={"docstatus": 1},
			fields=["name", "courier", "remittance_date", "orders_count", "batch_status"],
			order_by="remittance_date desc, creation desc",
			limit_page_length=100,
		)
	]


@frappe.whitelist()
def reconciliation(
	status: str = "All",
	courier: str | None = None,
	batch: str | None = None,
	difference_not_zero: int = 0,
	search: str | None = None,
	sort: str = "order_id desc",
	page: int = 1,
	page_size: int = 12,
):
	"""Reconciliation table: COD parcels with expected vs actual settlement."""
	_read()
	base = [p for p in _orders(courier) if _is_cod(p) and p.delivery_status != "Cancelled"]
	if batch:
		base = [p for p in base if p.settlement_batch == batch]
	if cint(difference_not_zero):
		base = [p for p in base if abs(flt(p.difference)) > 0]

	counts = {"All": len(base)}
	cards = []
	for st in RECON_STATES:
		group = [p for p in base if p.payout_status == st]
		counts[st] = len(group)
		cards.append(
			{
				"key": st,
				"label": st,
				"count": len(group),
				"amount": flt(sum(flt(p.cod_amount) for p in group), 2),
			}
		)

	utrs = {k: v.utr_number for k, v in _batch_info(p.settlement_batch for p in base).items()}
	tol = _tolerance()
	rows = []
	for p in base:
		if status in RECON_STATES and p.payout_status != status:
			continue
		exp = flt(p.expected_settlement) or engine.expected_for(p.name)["expected_settlement"]
		if p.payout_status in SETTLED:
			actual, diff = flt(p.actual_settlement, 2), flt(p.difference, 2)
		elif p.payout_status == "Missing":
			actual, diff = "Not received", 0
		else:
			actual, diff = "Awaiting", 0
		rows.append(
			{
				"order_id": p.name,
				"courier": p.courier,
				"cod_amount": flt(p.cod_amount, 2),
				"expected_settlement": flt(exp, 2),
				"actual_settlement": actual,
				"difference": diff,
				"within_tolerance": abs(diff) <= tol,
				"payout_status": p.payout_status,
				"status": p.reconciliation_status,
				"settlement_batch": p.settlement_batch,
				"utr": utrs.get(p.settlement_batch),
				"order_url": _order_url(p),
			}
		)
	result = _paginate(rows, page, page_size, sort, search, ("order_id", "courier", "utr"))
	result["counts"] = counts
	result["cards"] = cards
	result["stats"] = {"net_difference": flt(sum(flt(p.difference) for p in base), 2)}
	return result


BATCH_STATUSES = ("Reconciled", "Mismatch", "Pending review")


@frappe.whitelist()
def settlements(
	status: str = "All batches",
	courier: str | None = None,
	source: str | None = None,
	search: str | None = None,
	sort: str = "date desc",
	page: int = 1,
	page_size: int = 12,
):
	"""Courier Remittance batches list."""
	_read()
	batches = frappe.get_all(
		"Courier Remittance",
		filters={"docstatus": 1},
		limit_page_length=0,
		order_by="remittance_date desc, creation desc",
		fields=[
			"name",
			"courier",
			"remittance_date",
			"orders_count",
			"total_cod",
			"total_net_paid",
			"utr_number",
			"source",
			"batch_status",
			"file_name",
		],
	)
	if courier:
		batches = [b for b in batches if b.courier == courier]
	rows = [
		{
			"batch": b.name,
			"courier": b.courier,
			"date": _d(b.remittance_date),
			"orders": cint(b.orders_count),
			"cod_amount": flt(b.total_cod, 2),
			"deductions": flt(flt(b.total_cod) - flt(b.total_net_paid), 2),
			"net": flt(b.total_net_paid, 2),
			"utr": b.utr_number,
			"source": b.source,
			"file_name": b.file_name,
			"status": b.batch_status,
		}
		for b in batches
	]
	counts = {"All batches": len(rows)}
	for st in BATCH_STATUSES:
		counts[st] = len([r for r in rows if r["status"] == st])
	if source in ("Excel", "API"):
		rows = [r for r in rows if r["source"] == source]
	if status in BATCH_STATUSES:
		rows = [r for r in rows if r["status"] == status]

	since = getdate(add_days(nowdate(), -30))
	recent = [r for r in rows if r["date"] and getdate(r["date"]) >= since]
	cod_30 = sum(r["cod_amount"] for r in recent)
	ded_30 = sum(r["deductions"] for r in recent)
	result = _paginate(rows, page, page_size, sort, search, ("batch", "courier", "utr"))
	result["counts"] = counts
	result["stats"] = {
		"settled_30d": flt(sum(r["net"] for r in recent), 2),
		"batches_30d": len(recent),
		"orders_30d": sum(r["orders"] for r in recent),
		"deductions_30d": flt(ded_30, 2),
		"deductions_pct": flt(ded_30 * 100 / cod_30, 2) if cod_30 else 0,
	}
	return result


@frappe.whitelist()
def settlement_detail(batch: str):
	"""One settlement batch: header, totals and its remittance lines."""
	_read()
	if not frappe.db.exists("Courier Remittance", batch):
		frappe.throw(_("Settlement {0} not found").format(batch), frappe.DoesNotExistError)
	doc = frappe.get_doc("Courier Remittance", batch)
	lines = []
	for l in doc.lines:
		unexpected = flt(l.weight_charge) + flt(l.rto_charge) + flt(l.other_charge)
		lines.append(
			{
				"row_no": l.row_no or l.idx,
				"awb": l.awb,
				"order_id": l.cod_parcel,
				"cod_amount": flt(l.cod_amount, 2),
				"freight": flt(l.freight, 2),
				"cod_fee": flt(l.cod_fee, 2),
				"gst": flt(l.gst, 2),
				"deductions": flt(flt(l.cod_amount) - flt(l.net_paid), 2),
				"net": flt(l.net_paid, 2),
				"expected": flt(l.expected_net, 2),
				"difference": flt(l.difference, 2),
				"unexpected": flt(unexpected, 2),
				"status": l.match_status,
			}
		)
	return {
		"batch": doc.name,
		"courier": doc.courier,
		"date": _d(doc.remittance_date),
		"utr": doc.utr_number,
		"source": doc.source,
		"status": doc.batch_status,
		"file_name": doc.file_name,
		"orders": cint(doc.orders_count),
		"totals": {
			"cod": flt(doc.total_cod, 2),
			"net": flt(doc.total_net_paid, 2),
			"deductions": flt(flt(doc.total_cod) - flt(doc.total_net_paid), 2),
			"difference": flt(sum(flt(l.difference) for l in doc.lines), 2),
		},
		"lines": lines,
	}


@frappe.whitelist()
def settlement_lines_csv(batch: str):
	"""Download a settlement batch's lines as a CSV file."""
	_read()
	import csv
	import io

	detail = settlement_detail(batch)
	buf = io.StringIO()
	w = csv.writer(buf)
	w.writerow(
		[
			"Row",
			"AWB",
			"Order",
			"COD amount",
			"Freight",
			"COD fee",
			"GST",
			"Deductions",
			"Net paid",
			"Expected",
			"Difference",
			"Unexpected",
			"Match status",
		]
	)
	for l in detail["lines"]:
		w.writerow(
			[
				l["row_no"],
				l["awb"],
				l["order_id"] or "",
				l["cod_amount"],
				l["freight"],
				l["cod_fee"],
				l["gst"],
				l["deductions"],
				l["net"],
				l["expected"],
				l["difference"],
				l["unexpected"],
				l["status"],
			]
		)
	frappe.response["filename"] = f"settlement-{batch}.csv"
	frappe.response["filecontent"] = buf.getvalue().encode("utf-8")
	frappe.response["type"] = "download"


@frappe.whitelist()
def import_preview(file_url: str, courier: str, mapping: dict | str | None = None):
	"""Dry run of a settlement file (CSV/XLSX in File): headers, mapping, rows with validation. Saves nothing. Write role."""
	_write()
	from codsync.codsync import importer

	if not courier or not frappe.db.exists("Courier", courier):
		frappe.throw(_("Choose a courier"))
	data = importer.preview_import(file_url, "Remittance", courier, _json(mapping))
	f = frappe.db.get_value("File", {"file_url": file_url}, ["file_name", "file_size"], as_dict=True)
	data["file"] = {
		"name": f.file_name if f else file_url,
		"size_kb": round((f.file_size or 0) / 1024, 1) if f else None,
		"rows": data["row_count"],
	}
	data["fields"] = list(importer.ALIASES["Remittance"])
	return data


@frappe.whitelist()
def import_commit(file_url: str, courier: str, mapping: dict | str | None = None, save_mapping: int = 0):
	"""Create + submit the Courier Remittance(s) from the file and run matching (importer.import_remittance). Write role."""
	_write()
	from codsync.codsync import importer

	if not courier or not frappe.db.exists("Courier", courier):
		frappe.throw(_("Choose a courier"))
	return importer.run_import("Remittance", file_url, courier, _json(mapping), cint(save_mapping))


# ---------------------------------------------------------------------------
# Exceptions (list, detail, resolve)
# ---------------------------------------------------------------------------

EXC_STAGES = ("Open", "In review", "Disputed", "Resolved")
DISPUTE_TYPES = ("Unexpected deduction", "Amount mismatch", "Missing settlement")
ACCEPT_TYPES = ("Unexpected deduction", "Amount mismatch")
MATCH_TYPES = ("Missing settlement", "Unknown AWB")
EXC_FIELDS = [
	"name",
	"exception_type",
	"status",
	"cod_parcel",
	"awb",
	"courier",
	"settlement_batch",
	"expected",
	"actual",
	"impact",
	"detail",
	"line_ref",
	"unexpected_label",
	"resolution",
	"resolution_note",
	"assignee",
	"opened_on",
	"resolved_on",
	"claim_amount",
	"dispute_status",
	"dispute_raised_on",
	"creation",
]


def _stage(e):
	"""Tab an exception belongs to: Resolved / Disputed / In review (assigned) / Open."""
	if e.status == "Resolved":
		return "Resolved"
	if e.dispute_status == "Raised with Courier":
		return "Disputed"
	return "In review" if e.assignee else "Open"


def _exc_list_row(e):
	opened = e.opened_on or e.creation
	end = e.resolved_on if e.status == "Resolved" and e.resolved_on else None
	return {
		"name": e.name,
		"type": e.exception_type,
		"stage": _stage(e),
		"status": e.status,
		"order_id": e.cod_parcel,
		"awb": e.awb,
		"courier": e.courier,
		"expected": flt(e.expected, 2),
		"actual": flt(e.actual, 2),
		"impact": flt(e.impact, 2),
		"detail": e.detail,
		"age_days": max(date_diff(getdate(end) if end else nowdate(), getdate(opened)), 0) if opened else 0,
		"assignee": e.assignee,
		"dispute_status": e.dispute_status,
	}


@frappe.whitelist()
def exceptions(filters: dict | str | None = None, page: int = 1, page_size: int = 20):
	"""Exceptions list. `filters` (dict or JSON): tab (Open / In review / Disputed / Resolved), exception_type,
	courier, assignee, search, sort (default `age_days desc`). Returns rows, total and per-tab counts."""
	_read()
	f = _json(filters, {}) or {}
	rows = [
		_exc_list_row(e)
		for e in frappe.get_all(
			"COD Exception", fields=EXC_FIELDS, order_by="creation desc", limit_page_length=0
		)
	]
	if f.get("exception_type"):
		rows = [r for r in rows if r["type"] == f["exception_type"]]
	if f.get("courier"):
		rows = [r for r in rows if r["courier"] == f["courier"]]
	if f.get("assignee"):
		rows = [r for r in rows if r["assignee"] == f["assignee"]]
	if f.get("search"):
		q = str(f["search"]).strip().lower()
		rows = [
			r
			for r in rows
			if any(q in str(r.get(k) or "").lower() for k in ("name", "order_id", "awb", "detail"))
		]
	counts = {s: sum(1 for r in rows if r["stage"] == s) for s in EXC_STAGES}
	tab = f.get("tab") or "Open"
	rows = [r for r in rows if r["stage"] == tab] if tab in EXC_STAGES else rows
	out = _paginate(rows, page, page_size, f.get("sort") or "age_days desc")
	out["counts"] = counts
	out["types"] = list(EXC_TYPES)
	return out


def _exc_activity(exc):
	items = [
		{
			"kind": "open",
			"title": "Exception opened",
			"detail": exc.detail or "",
			"event_time": _dt(exc.opened_on or exc.creation),
		}
	]
	for c in frappe.get_all(
		"Comment",
		filters={"reference_doctype": "COD Exception", "reference_name": exc.name, "comment_type": "Comment"},
		fields=["content", "creation", "comment_email"],
		order_by="creation asc",
	):
		items.append(
			{
				"kind": "note",
				"title": c.comment_email or "Note",
				"detail": frappe.utils.strip_html(c.content or ""),
				"event_time": _dt(c.creation),
			}
		)
	if exc.status == "Resolved":
		items.append(
			{
				"kind": "done",
				"title": f"Resolved: {exc.resolution or 'closed'}",
				"detail": exc.resolution_note or "",
				"event_time": _dt(exc.resolved_on),
			}
		)
	items.sort(key=lambda a: a["event_time"] or "")
	return items


def _exc_candidates(exc):
	"""Lines (for a parcel exception) or parcels (for an Unknown AWB exception) to match against."""
	if exc.status == "Resolved" or exc.exception_type not in MATCH_TYPES:
		return {"lines": [], "parcels": []}
	if exc.cod_parcel:
		lines = frappe.db.sql(
			"""select l.name, l.awb, l.parent as batch, l.net_paid, l.row_no from `tabRemittance Line` l
			join `tabCourier Remittance` r on r.name = l.parent
			where r.docstatus = 1 and l.match_status = 'Unknown' and (%(c)s is null or r.courier = %(c)s)
			order by r.remittance_date desc limit 50""",
			{"c": exc.courier},
			as_dict=True,
		)
		return {
			"lines": [
				{"name": l.name, "awb": l.awb, "batch": l.batch, "net": flt(l.net_paid, 2), "row": l.row_no}
				for l in lines
			],
			"parcels": [],
		}
	filters = {
		"payment_mode": "COD",
		"awb": ["is", "set"],
		"settlement_batch": ["is", "not set"],
		"status": ["in", ["Delivered", "In Transit"]],
	}
	if exc.courier:
		filters["courier"] = exc.courier
	parcels = frappe.get_all(
		"COD Parcel",
		filters=filters,
		fields=["name", "awb", "customer_name", "cod_amount"],
		order_by="delivered_date desc",
		limit_page_length=50,
	)
	return {
		"lines": [],
		"parcels": [
			{"name": p.name, "awb": p.awb, "customer": p.customer_name, "amount": flt(p.cod_amount, 2)}
			for p in parcels
		],
	}


def _exc_options(exc, candidates):
	if exc.status == "Resolved":
		return []
	opts = []
	if exc.exception_type in DISPUTE_TYPES:
		opts.append(
			(
				"raise_dispute",
				"Raise dispute with courier",
				"Claim the amount from the courier and track the dispute.",
			)
		)
	if exc.exception_type in ACCEPT_TYPES and exc.cod_parcel:
		opts.append(
			(
				"accept_deduction",
				"Accept deduction",
				"Agree the courier was right, mark the order Paid and reconciled.",
			)
		)
	if exc.exception_type in MATCH_TYPES:
		opts.append(
			(
				"match_line",
				"Match to another settlement line" if exc.cod_parcel else "Match to an order",
				"Use when the amount was paid under a different AWB."
				if exc.cod_parcel
				else "Link this payout line to the order it belongs to.",
			)
		)
	opts.append(("resolve_manually", "Mark resolved manually", "Close without changes. A note is required."))
	return [{"key": k, "label": l, "description": d, "default": i == 0} for i, (k, l, d) in enumerate(opts)]


def _exc_kv(exc, parcel):
	kv = []
	if exc.unexpected_label:
		kv.append(
			{"label": "Unexpected line", "value": f"{exc.unexpected_label} · {rs_text(abs(flt(exc.impact)))}"}
		)
	if parcel and (flt(parcel.declared_weight) or flt(parcel.charged_weight)):
		kv.append({"label": "Declared weight", "value": f"{flt(parcel.declared_weight):g} kg"})
		kv.append(
			{
				"label": "Charged weight",
				"value": f"{flt(parcel.charged_weight):g} kg"
				+ (f" ({exc.line_ref})" if exc.line_ref else ""),
				"bad": flt(parcel.charged_weight) > flt(parcel.declared_weight),
			}
		)
	elif exc.line_ref:
		kv.append({"label": "File line", "value": exc.line_ref})
	kv.append({"label": "AWB", "value": exc.awb or "—", "mono": True})
	if exc.settlement_batch:
		utr = frappe.db.get_value("Courier Remittance", exc.settlement_batch, "utr_number")
		kv.append({"label": "Batch", "value": exc.settlement_batch, "mono": True})
		kv.append({"label": "UTR", "value": utr or "—", "mono": True})
	return kv


def rs_text(n):
	return f"₹{flt(n):,.2f}"


@frappe.whitelist()
def exception_detail(name: str):
	"""Everything the resolve drawer shows for one exception."""
	_read()
	if not frappe.db.exists("COD Exception", name):
		frappe.throw(_("Exception {0} not found").format(name), frappe.DoesNotExistError)
	exc = frappe.get_doc("COD Exception", name)
	parcel = frappe.get_doc("COD Parcel", exc.cod_parcel) if exc.cod_parcel else None
	cand = _exc_candidates(exc)
	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User", "name": ["!=", "Guest"]},
		fields=["name", "full_name"],
		order_by="full_name asc",
		limit_page_length=200,
	)
	row = _exc_list_row(exc)
	return {
		"header": {
			"name": exc.name,
			"type": exc.exception_type,
			"order_id": exc.cod_parcel,
			"awb": exc.awb,
			"courier": exc.courier,
			"customer": parcel.customer_name if parcel else None,
			"batch": exc.settlement_batch,
			"opened_on": _dt(exc.opened_on or exc.creation),
			"status": exc.status,
			"stage": row["stage"],
			"age_days": row["age_days"],
			"detail": exc.detail,
			"assignee": exc.assignee,
		},
		"expected": flt(exc.expected, 2),
		"actual": flt(exc.actual, 2),
		"difference": flt(flt(exc.actual) - flt(exc.expected), 2),
		"impact": flt(exc.impact, 2),
		"kv": _exc_kv(exc, parcel),
		"resolution_options": _exc_options(exc, cand),
		"candidate_lines": cand["lines"],
		"candidate_parcels": cand["parcels"],
		"dispute": {
			"status": exc.dispute_status or "Not raised",
			"claim_amount": flt(exc.claim_amount, 2),
			"raised_on": _d(exc.dispute_raised_on),
			"suggested_claim": abs(flt(exc.impact, 2)),
		},
		"resolution": exc.resolution,
		"resolution_note": exc.resolution_note,
		"resolved_on": _dt(exc.resolved_on),
		"assignable_users": [{"name": u.name, "label": u.full_name or u.name} for u in users],
		"activity": _exc_activity(exc),
	}


def _log_exc(exc, text):
	"""Add the change to the exception's activity, and to the order's activity when there is one."""
	exc.add_comment("Comment", text)
	if exc.cod_parcel:
		engine.add_note(exc.cod_parcel, f"{exc.name}: {text}")


def _finish(exc, resolution, note):
	exc.status = "Resolved"
	exc.resolution = resolution
	if note:
		exc.resolution_note = note
	exc.save(ignore_permissions=True)


@frappe.whitelist()
def resolve_exception(name: str, action: str, payload: dict | str | None = None):
	"""Act on one exception. action / payload:
	raise_dispute {claim_amount, note}, accept_deduction {note}, match_line {line | parcel, note},
	resolve_manually {note (required), dispute_outcome (Resolved / Rejected, optional)}, assign {assignee ("" to unassign)}.
	Write role."""
	_write()
	p = _json(payload, {}) or {}
	if not frappe.db.exists("COD Exception", name):
		frappe.throw(_("Exception {0} not found").format(name), frappe.DoesNotExistError)
	exc = frappe.get_doc("COD Exception", name)
	if exc.status == "Resolved":
		frappe.throw(_("{0} is already resolved").format(name))
	note = (p.get("note") or "").strip()
	frappe.db.savepoint("codsync_resolve")
	try:
		if action == "raise_dispute":
			if exc.exception_type not in DISPUTE_TYPES:
				frappe.throw(_("A dispute cannot be raised for {0}").format(exc.exception_type))
			if exc.dispute_status == "Raised with Courier":
				frappe.throw(_("A dispute is already raised for {0}").format(name))
			claim = flt(
				p.get("claim_amount") if p.get("claim_amount") not in (None, "") else abs(flt(exc.impact))
			)
			if claim <= 0:
				frappe.throw(_("Claim amount must be greater than 0"))
			exc.resolution, exc.claim_amount = "Raise dispute", claim
			exc.dispute_status, exc.dispute_raised_on = (
				"Raised with Courier",
				nowdate(),
			)  # set here so the claim is kept
			if note:
				exc.resolution_note = note
			exc.save(ignore_permissions=True)
			_log_exc(
				exc, f"Dispute raised with courier, claim {rs_text(claim)}" + (f". {note}" if note else "")
			)
		elif action == "accept_deduction":
			if exc.exception_type not in ACCEPT_TYPES or not exc.cod_parcel:
				frappe.throw(_("A deduction cannot be accepted for {0}").format(exc.exception_type))
			parcel = frappe.db.get_value("COD Parcel", exc.cod_parcel, ["actual_settlement"], as_dict=True)
			frappe.db.set_value(
				"COD Parcel",
				exc.cod_parcel,
				{"payout_status": "Paid", "expected_settlement": parcel.actual_settlement, "difference": 0},
			)
			frappe.db.sql(
				"""update `tabRemittance Line` set match_status = 'Paid', difference = 0
				where cod_parcel = %s and match_status = 'Short-paid'""",
				exc.cod_parcel,
			)
			_finish(exc, "Accept deduction", note)
			_log_exc(exc, "Deduction accepted, order marked Paid" + (f". {note}" if note else ""))
		elif action == "match_line":
			_match(exc, p)
			exc.reload()
			_finish(exc, "Match to another line", note)
			_log_exc(exc, "Matched to another settlement line" + (f". {note}" if note else ""))
		elif action == "resolve_manually":
			if not note:
				frappe.throw(_("A note is required to resolve manually"))
			if (
				p.get("dispute_outcome") in ("Resolved", "Rejected")
				and exc.dispute_status == "Raised with Courier"
			):
				exc.dispute_status = p["dispute_outcome"]
			_finish(exc, "Resolved manually", note)
			_log_exc(exc, f"Resolved manually. {note}")
		elif action == "assign":
			user = (p.get("assignee") or "").strip()
			if user and not frappe.db.exists("User", {"name": user, "enabled": 1}):
				frappe.throw(_("User {0} not found or disabled").format(user))
			exc.assignee = user or None
			exc.save(ignore_permissions=True)
			_log_exc(exc, f"Assigned to {user}" if user else "Unassigned")
		else:
			frappe.throw(_("Unknown action {0}").format(action))
	except Exception:
		frappe.db.rollback(save_point="codsync_resolve")
		raise
	exc.reload()
	row = _exc_list_row(exc)
	return {
		"name": exc.name,
		"status": exc.status,
		"stage": row["stage"],
		"resolution": exc.resolution,
		"dispute_status": exc.dispute_status,
		"claim_amount": flt(exc.claim_amount, 2),
		"assignee": exc.assignee,
	}


def _match(exc, p):
	"""Point an Unknown payout line at the right order (by AWB) and run matching again."""
	if exc.exception_type not in MATCH_TYPES:
		frappe.throw(_("Matching is not available for {0}").format(exc.exception_type))
	if exc.cod_parcel:
		line = p.get("line")
		parcel = frappe.get_doc("COD Parcel", exc.cod_parcel)
		if not line:
			frappe.throw(_("Choose the settlement line to match"))
	else:
		parcel_name = p.get("parcel")
		if not parcel_name:
			frappe.throw(_("Choose the order to match"))
		parcel = frappe.get_doc("COD Parcel", parcel_name)
		line = (
			frappe.db.get_value(
				"Remittance Line",
				{
					"awb": engine.normalize_awb(exc.awb),
					"match_status": "Unknown",
					"parent": exc.settlement_batch,
				},
			)
			if exc.settlement_batch
			else None
		)
		if not line:
			frappe.throw(_("The payout line for AWB {0} was not found").format(exc.awb))
	if not parcel.awb:
		frappe.throw(_("Order {0} has no AWB to match against").format(parcel.name))
	row = frappe.db.get_value("Remittance Line", line, ["parent", "match_status"], as_dict=True)
	if (
		not row
		or row.match_status != "Unknown"
		or frappe.db.get_value("Courier Remittance", row.parent, "docstatus") != 1
	):
		frappe.throw(_("That line is not an unmatched line of a submitted batch"))
	frappe.db.set_value("Remittance Line", line, "awb", parcel.awb)
	engine.reconcile_remittance(row.parent)
	if frappe.db.get_value("Remittance Line", line, "match_status") == "Unknown":
		frappe.throw(_("The line could not be matched to {0}").format(parcel.name))


# ---------------------------------------------------------------------------
# Settings (Store Connection) and Sync Log
# ---------------------------------------------------------------------------

SETTINGS_MANAGERS = ("CODSync Manager", "System Manager")
PLATFORMS = ("Shopify", "WooCommerce", "Odoo")
# plain fields that save_settings may change
SETTINGS_TEXT = (
	"store_url",
	"store_name",
	"shopify_api_version",
	"woo_api_version",
	"odoo_database",
	"odoo_username",
	"cod_keyword",
	"cod_tag",
	"default_courier",
)
# write-only: never returned, only "saved" flags are
SECRET_FIELDS = (
	"shopify_client_id",
	"shopify_client_secret",
	"woo_consumer_key",
	"woo_consumer_secret",
	"odoo_api_key",
	"webhook_secret",
)
FETCH_FLAG = "codsync_fetching_orders"


def _manager():
	frappe.only_for(SETTINGS_MANAGERS)


def _is_saved(doc, field):
	try:
		return bool(doc.get_password(field, raise_exception=False))
	except Exception:
		return False


@frappe.whitelist()
def settings():
	"""Store Connection for the Settings page. Secrets are never returned, only whether they are saved. Read role."""
	_read()
	doc = frappe.get_doc("Store Connection")
	return {
		"store": {
			"platform": doc.platform,
			"enabled": bool(doc.enabled),
			"store_url": doc.store_url,
			"store_name": doc.store_name,
			"shopify_api_version": doc.shopify_api_version,
			"woo_api_version": doc.woo_api_version,
			"odoo_database": doc.odoo_database,
			"odoo_username": doc.odoo_username,
			"cod_keyword": doc.cod_keyword,
			"cod_tag": doc.cod_tag,
			"default_courier": doc.default_courier,
			"tolerance": flt(doc.tolerance, 2),
			"default_payout_cycle_days": cint(doc.default_payout_cycle_days),
		},
		"saved": {
			f: (
				_is_saved(doc, f)
				if f in ("shopify_client_secret", "woo_consumer_secret", "odoo_api_key", "webhook_secret")
				else bool(doc.get(f))
			)
			for f in SECRET_FIELDS
		},
		"courier_mapping": [
			{"source_name": r.source_name, "courier": r.courier} for r in doc.courier_mapping or []
		],
		"couriers": frappe.get_all("Courier", pluck="name", order_by="courier_name asc", limit_page_length=0),
		"platforms": list(PLATFORMS),
		"status": {
			"last_test_status": doc.last_test_status,
			"last_tested_on": _dt(doc.last_tested_on),
			"last_synced_on": _dt(doc.last_synced_on),
		},
		"fetching": bool(frappe.cache().get_value(FETCH_FLAG)),
		"webhook_url": frappe.utils.get_url("/api/method/codsync.codsync.api.webhook"),
		"can_edit": bool(set(frappe.get_roles()) & set(SETTINGS_MANAGERS)),
	}


@frappe.whitelist()
def save_settings(values: dict | str | None = None):
	"""Save Store Connection settings. `values` (dict or JSON) may hold store fields, tolerance,
	default_payout_cycle_days, courier_mapping [{source_name, courier}] and secrets (only non-empty
	secrets are written; blank keeps the saved one). Returns settings(). CODSync Manager or System Manager."""
	_manager()
	v = _json(values, {}) or {}
	doc = frappe.get_doc("Store Connection")
	if "platform" in v:
		if v["platform"] not in PLATFORMS:
			frappe.throw(_("Platform must be one of {0}").format(", ".join(PLATFORMS)))
		doc.platform = v["platform"]
	if "enabled" in v:
		doc.enabled = 1 if v["enabled"] else 0
	for f in SETTINGS_TEXT:
		if f in v:
			value = (v[f] or "").strip() or None
			if f == "store_url" and value:
				value = value.replace("https://", "").replace("http://", "").strip("/")
			if f == "default_courier" and value and not frappe.db.exists("Courier", value):
				frappe.throw(_("Courier {0} not found").format(value))
			doc.set(f, value)
	if "tolerance" in v:
		if flt(v["tolerance"]) < 0:
			frappe.throw(_("Tolerance cannot be negative"))
		doc.tolerance = flt(v["tolerance"])
	if "default_payout_cycle_days" in v:
		if cint(v["default_payout_cycle_days"]) < 1:
			frappe.throw(_("Payout cycle must be at least 1 day"))
		doc.default_payout_cycle_days = cint(v["default_payout_cycle_days"])
	for f in SECRET_FIELDS:
		if (v.get(f) or "").strip():
			doc.set(f, v[f].strip())
	if "courier_mapping" in v:
		rows, seen = [], set()
		for r in v["courier_mapping"] or []:
			src, courier = (r.get("source_name") or "").strip(), (r.get("courier") or "").strip()
			if not src and not courier:
				continue
			if not src or not courier:
				frappe.throw(_("Each courier mapping needs a source name and a courier"))
			if not frappe.db.exists("Courier", courier):
				frappe.throw(_("Courier {0} not found").format(courier))
			if src.lower() in seen:
				frappe.throw(_("Source name {0} is mapped twice").format(src))
			seen.add(src.lower())
			rows.append({"source_name": src, "courier": courier})
		doc.set("courier_mapping", rows)
	if doc.enabled and not doc.store_url:
		frappe.throw(_("Store URL is required while the connection is enabled"))
	doc.save()
	return settings()


@frappe.whitelist()
def test_connection():
	"""Run the platform's connection test with the saved credentials; stamps last_test_status. Manager role."""
	_manager()
	doc = frappe.get_doc("Store Connection")
	out = doc.test_connection()
	out["status"] = settings()["status"]
	return out


def _fetch_orders_job(user):
	try:
		# background job: run as the user who started the fetch
		frappe.set_user(user)  # nosemgrep
		frappe.get_doc("Store Connection").fetch_orders()
	except Exception:
		pass  # the platform adapter already wrote the failure to Sync Log
	finally:
		frappe.cache().delete_value(FETCH_FLAG)
		# background job: nothing else commits the sync log rows
		frappe.db.commit()  # nosemgrep


@frappe.whitelist(methods=["POST"])
def fetch_orders():
	"""Pull orders from the store in the background (one run at a time). Progress and result: sync_log() / settings().
	Manager role."""
	_manager()
	if frappe.cache().get_value(FETCH_FLAG):
		return {"queued": False, "running": True}
	frappe.cache().set_value(FETCH_FLAG, 1, expires_in_sec=900)
	frappe.enqueue(
		"codsync.codsync.ui_api._fetch_orders_job", queue="long", timeout=3600, user=frappe.session.user
	)
	return {"queued": True, "running": True}


@frappe.whitelist()
def sync_log(page: int = 1, page_size: int = 10, status: str | None = None, operation: str | None = None):
	"""Recent Sync Log rows, newest first. Request and response payloads are never returned. Read role."""
	_read()
	filters = {}
	if status:
		filters["status"] = status
	if operation:
		filters["operation"] = operation
	total = frappe.db.count("Sync Log", filters)
	page, page_size = max(cint(page) or 1, 1), min(max(cint(page_size) or 10, 1), 100)
	rows = frappe.get_all(
		"Sync Log",
		filters=filters,
		order_by="creation desc",
		limit_start=(page - 1) * page_size,
		limit_page_length=page_size,
		fields=[
			"name",
			"creation",
			"platform",
			"operation",
			"status",
			"error_message",
			"http_status",
			"duration_ms",
			"reference_doctype",
			"reference_name",
			"attempt",
		],
	)
	return {
		"rows": [
			{
				"name": r.name,
				"time": _dt(r.creation),
				"platform": r.platform,
				"operation": r.operation,
				"status": r.status,
				"error": (r.error_message or "")[:300] or None,
				"http_status": r.http_status,
				"duration_ms": r.duration_ms,
				"reference": (f"{r.reference_doctype} {r.reference_name}" if r.reference_name else None),
			}
			for r in rows
		],
		"total": total,
		"operations": frappe.get_all("Sync Log", pluck="operation", distinct=True, order_by="operation asc"),
	}


# ---------------------------------------------------------------------------
# Reports: wrappers over the Frappe script reports in codsync/codsync/report
# ---------------------------------------------------------------------------

# name -> (module folder, description, filters the report query honours)
REPORTS = {
	"COD Aging": ("cod_aging", "Delivered COD not yet paid, bucketed by days since delivery.", ("courier",)),
	"Courier Outstanding": (
		"courier_outstanding",
		"COD collected, paid, short and still outstanding per courier.",
		("courier",),
	),
	"Payout Reconciliation": (
		"payout_reconciliation",
		"Order-level expected net vs amount received, by delivery date.",
		("courier", "from_date", "to_date"),
	),
	"Unmatched Payout Lines": (
		"unmatched_payout_lines",
		"Payout lines whose AWB matched no order, by remittance date.",
		("courier", "from_date", "to_date"),
	),
}


@frappe.whitelist()
def reports_list():
	"""The available reports with the filters each one supports."""
	_read()
	return [{"name": n, "description": d, "filters": list(f)} for n, (_m, d, f) in REPORTS.items()]


def _run_report(name, filters):
	if name not in REPORTS:
		frappe.throw(_("Unknown report {0}").format(name))
	folder, _desc, allowed = REPORTS[name]
	f = {k: v for k, v in (_json(filters, {}) or {}).items() if k in allowed and v not in (None, "")}
	if f.get("from_date") and f.get("to_date") and getdate(f["from_date"]) > getdate(f["to_date"]):
		frappe.throw(_("From date cannot be after To date"))
	result = frappe.get_attr(f"codsync.codsync.report.{folder}.{folder}.execute")(frappe._dict(f))
	columns = [{"key": c["fieldname"], "label": str(c["label"]), "type": c["fieldtype"]} for c in result[0]]
	return columns, [dict(r) for r in result[1]], f


@frappe.whitelist()
def run_report(name: str, filters: dict | str | None = None):
	"""Run a report with {courier, from_date, to_date}; unsupported filters are ignored (see reports_list)."""
	_read()
	columns, rows, applied = _run_report(name, filters)
	return {"name": name, "columns": columns, "rows": rows, "total": len(rows), "filters": applied}


@frappe.whitelist()
def report_csv(name: str, filters: dict | str | None = None):
	"""Download a report's rows (same filters as run_report) as a CSV file."""
	_read()
	import csv
	import io

	columns, rows, _applied = _run_report(name, filters)
	buf = io.StringIO()
	w = csv.writer(buf)
	w.writerow([c["label"] for c in columns])
	for r in rows:
		w.writerow(["" if r.get(c["key"]) is None else r.get(c["key"]) for c in columns])
	frappe.response["filename"] = f"{name.lower().replace(' ', '-')}-{nowdate()}.csv"
	frappe.response["filecontent"] = buf.getvalue().encode("utf-8")
	frappe.response["type"] = "download"
