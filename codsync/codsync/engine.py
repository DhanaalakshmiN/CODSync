"""CODSync engine: expected charges, disputes, order timeline and notes."""

import re

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_datetime, today

EXCEPTION_TYPE_BY_PAYOUT = {
	"Short-paid": "Unexpected deduction",
	"Missing": "Missing settlement",
}


def get_tolerance():
	"""Store Connection.tolerance (defaults to 1.00 until the settings are saved)."""
	value = frappe.db.get_single_value("Store Connection", "tolerance")
	return 1.0 if value in (None, "") else flt(value)


def expected_for(parcel, line=None):
	"""Expected COD fee, freight, GST and settlement for a parcel.

	freight = base_freight + additional_freight_per_kg x kg above base_weight_kg,
	using the courier's charged weight when known, else the declared weight.
	A courier without rate data falls back to the remittance line's own
	freight / fee / gst (if a line is given).
	"""
	doc = frappe.get_doc("COD Parcel", parcel) if isinstance(parcel, str) else parcel
	courier = frappe.get_cached_doc("Courier", doc.courier) if doc.courier else None
	cod = flt(doc.cod_amount)

	if courier and (
		flt(courier.cod_fee_percent) or flt(courier.base_freight) or flt(courier.additional_freight_per_kg)
	):
		fee = cod * flt(courier.cod_fee_percent) / 100
		# expected = what WE expect pre-payout: the declared weight. Using the
		# courier's charged weight here would absorb over-billing into the
		# expectation and hide the weight discrepancy the exception should flag.
		weight = flt(doc.declared_weight) or flt(doc.charged_weight)
		freight = flt(courier.base_freight) + flt(courier.additional_freight_per_kg) * max(
			0, weight - flt(courier.base_weight_kg)
		)
		gst = (fee + freight) * flt(courier.gst_percent) / 100
	elif line is not None:
		fee, freight, gst = flt(line.cod_fee), flt(line.freight), flt(line.gst)
	else:
		fee = freight = gst = 0

	return {
		"expected_cod_fee": flt(fee, 2),
		"expected_freight": flt(freight, 2),
		"expected_gst": flt(gst, 2),
		"expected_settlement": flt(cod - fee - freight - gst, 2),
	}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


def upsert_exception(exception_type, cod_parcel=None, awb=None, **fields):
	"""One OPEN exception per parcel (or AWB) + type: update it if it exists."""
	filters = {"exception_type": exception_type, "status": "Open"}
	if cod_parcel:
		filters["cod_parcel"] = cod_parcel
	else:
		filters["awb"] = awb
	name = frappe.db.get_value("COD Exception", filters)
	if name:
		exc = frappe.get_doc("COD Exception", name)
		exc.update(fields)
	else:
		exc = frappe.get_doc(
			{
				"doctype": "COD Exception",
				"exception_type": exception_type,
				"cod_parcel": cod_parcel,
				"awb": awb,
				"status": "Open",
				**fields,
			}
		)
	exc.save(ignore_permissions=True) if name else exc.insert(ignore_permissions=True)
	return exc


def resolve_exceptions(exception_type, cod_parcel, note):
	"""Auto-resolve open exceptions of a type for a parcel; returns how many were cleared."""
	names = frappe.get_all(
		"COD Exception",
		pluck="name",
		filters={"exception_type": exception_type, "cod_parcel": cod_parcel, "status": "Open"},
	)
	for n in names:
		frappe.db.set_value(
			"COD Exception",
			n,
			{
				"status": "Resolved",
				"resolution": "Resolved manually",
				"resolution_note": note,
				"resolved_on": frappe.utils.now_datetime(),
			},
		)
	return len(names)


# ---------------------------------------------------------------------------
# Line / batch reconciliation
# ---------------------------------------------------------------------------

_UNEXPECTED_LABELS = (
	("weight_charge", "Weight discrepancy charge"),
	("rto_charge", "RTO charge"),
	("other_charge", "Other charge"),
)


def normalize_awb(value):
	"""Canonical AWB match key: trim, uppercase, drop spaces / dashes / quotes,
	and turn Excel's numeric forms (1.23E+11, 12345.0) back into plain digits."""
	s = re.sub(r"[\s\-\"']", "", str(value or "").strip().upper())
	if s and ("." in s or "E" in s) and re.fullmatch(r"\d+(\.\d+)?([Ee][+-]?\d+)?", s):
		try:
			f = float(s)
			if f == int(f):
				return str(int(f))
		except (ValueError, OverflowError):
			pass
	return s


def _awb_parcels():
	"""{normalized AWB: [parcel names]} for every parcel that has an AWB."""
	out = {}
	for name, awb in frappe.get_all(
		"COD Parcel",
		filters={"awb": ["is", "set"]},
		fields=["name", "awb"],
		limit_page_length=0,
		as_list=True,
	):
		out.setdefault(normalize_awb(awb), []).append(name)
	return out


AMOUNT_FIELDS = (
	"cod_amount",
	"freight",
	"cod_fee",
	"gst",
	"net_paid",
	"rto_charge",
	"weight_charge",
	"other_charge",
)


def _line_errors(line):
	"""Row-level validation before matching: AWB present, amounts numeric, net_paid >= 0."""
	errors = []
	if not normalize_awb(line.awb):
		errors.append("AWB is missing")
	for field in AMOUNT_FIELDS:
		value = line.get(field)
		if value in (None, ""):
			continue
		if isinstance(value, str):
			try:
				value = float(value.replace(",", ""))
			except ValueError:
				errors.append(f"{field} is not numeric ({value})")
				continue
		if field == "net_paid" and flt(value) < 0:
			errors.append(f"net_paid is negative ({value})")
	return errors


def reconcile_line(line, parcel):
	"""Reconcile one matched Remittance Line against its COD Parcel.

	Returns {"clean", "unknown", "difference", "cleared", "payout_status"}.
	"""
	batch = frappe.db.get_value(
		"Courier Remittance", line.parent, ["name", "courier", "file_name"], as_dict=True
	) or frappe._dict(name=line.parent)
	line_ref = f"{batch.file_name or batch.name}, row {line.row_no or line.idx}"
	awb = normalize_awb(line.awb)

	if not parcel:
		frappe.db.set_value("Remittance Line", line.name, "match_status", "Unknown")
		upsert_exception(
			"Unknown AWB",
			awb=awb,
			courier=batch.courier,
			settlement_batch=batch.name,
			detail=f"AWB {awb} is not in COD Parcels",
			actual=flt(line.net_paid),
			impact=flt(line.net_paid),
			line_ref=line_ref,
		)
		return {"clean": False, "unknown": True, "difference": 0, "cleared": 0, "payout_status": "Unknown"}

	if isinstance(parcel, str):
		parcel = frappe.get_doc("COD Parcel", parcel)
	exp = expected_for(parcel, line)
	expected = exp["expected_settlement"]
	actual = flt(line.net_paid)
	difference = flt(actual - expected, 2)
	unexpected = flt(line.weight_charge) + flt(line.rto_charge) + flt(line.other_charge)
	within = abs(difference) <= get_tolerance()
	payout_status = "Short-paid" if difference < 0 and not within else "Paid"

	frappe.db.set_value(
		"Remittance Line",
		line.name,
		{
			"expected_net": expected,
			"match_status": payout_status,
			"cod_parcel": parcel.name,
			"difference": difference,
		},
	)
	frappe.db.set_value(
		"COD Parcel",
		parcel.name,
		{
			"expected_settlement": expected,
			"actual_settlement": actual,
			"difference": difference,
			"settlement_batch": batch.name,
			"payout_status": payout_status,
			"charged_weight": flt(line.charged_weight) or parcel.charged_weight,
		},
	)

	common = dict(
		awb=parcel.awb,
		courier=parcel.courier,
		settlement_batch=batch.name,
		line_ref=line_ref,
		expected=expected,
		actual=actual,
	)
	if unexpected > 0:
		label = max(_UNEXPECTED_LABELS, key=lambda x: flt(line.get(x[0])))[1]
		upsert_exception(
			"Unexpected deduction",
			parcel.name,
			impact=-unexpected,
			detail=f"{label} of {unexpected:.2f} deducted",
			unexpected_label=label,
			**common,
		)
	elif line.cod_amount and flt(line.cod_amount) != flt(parcel.cod_amount):
		upsert_exception(
			"Amount mismatch",
			parcel.name,
			impact=difference,
			detail=f"Collected {flt(line.cod_amount):g} of {flt(parcel.cod_amount):g}",
			**common,
		)
	elif not within:
		upsert_exception(
			"Amount mismatch",
			parcel.name,
			impact=difference,
			detail=f"Expected {expected:.2f}, received {actual:.2f}",
			**common,
		)
	else:
		cleared = resolve_exceptions(
			"Missing settlement", parcel.name, "Settlement received within tolerance"
		)
		return {
			"clean": True,
			"unknown": False,
			"difference": difference,
			"cleared": cleared,
			"payout_status": payout_status,
		}
	return {
		"clean": False,
		"unknown": False,
		"difference": difference,
		"cleared": 0,
		"payout_status": payout_status,
	}


def reconcile_remittance(remittance_name):
	"""Match every line of a Courier Remittance to its COD Parcel by normalized AWB.

	Each line resolves to exactly one outcome:
	  matched   - one eligible parcel (still graded Paid / Short-paid by tolerance)
	  unknown   - no parcel has this AWB
	  duplicate - the AWB belongs to more than one parcel
	  ambiguous - parcel found but not matchable: repeated AWB in this batch,
	              Prepaid parcel, or already settled in another batch
	Bad rows (missing AWB, non-numeric amounts, negative net_paid) are skipped
	with a Sync Log entry. Idempotent: re-running never duplicates exceptions.
	"""
	remittance = frappe.get_doc("Courier Remittance", remittance_name)
	parcel_map = _awb_parcels()
	batch_ref = remittance.file_name or remittance.name
	seen = {}
	counts = {"matched": 0, "short-paid": 0, "unknown": 0, "exceptions": 0}
	skipped = []
	has_mismatch = False
	cleared = 0

	for line in remittance.lines:
		row = line.row_no or line.idx
		awb = normalize_awb(line.awb)
		errors = _line_errors(line)
		if errors:
			frappe.db.set_value("Remittance Line", line.name, "match_status", "Unknown")
			upsert_exception(
				"Unknown AWB",
				awb=awb,
				courier=remittance.courier,
				settlement_batch=remittance.name,
				detail="; ".join(errors),
				line_ref=f"{batch_ref}, row {row}",
			)
			counts["unknown"] += 1
			counts["exceptions"] += 1
			skipped.append({"row": row, "awb": awb, "errors": errors})
			continue

		parcel = None
		exc_type = "Unknown AWB"
		if awb in seen:
			outcome, reason = "ambiguous", f"Duplicate AWB in this batch; row {seen[awb]} matched first"
			exc_type = "Duplicate AWB"
		else:
			names = parcel_map.get(awb) or []
			if not names:
				outcome, reason = "unknown", f"AWB {awb} is not in COD Parcels"
			elif len(names) > 1:
				outcome, reason = (
					"duplicate",
					f"AWB {awb} matches {len(names)} parcels: " + ", ".join(names[:5]),
				)
				exc_type = "Duplicate AWB"
			else:
				parcel = frappe.get_doc("COD Parcel", names[0])
				if (parcel.payment_mode or "COD") == "Prepaid":
					outcome, reason = "ambiguous", f"Parcel {parcel.name} is Prepaid, not a COD order"
				elif parcel.settlement_batch and parcel.settlement_batch != remittance.name:
					outcome, reason = (
						"ambiguous",
						f"Parcel {parcel.name} is already settled in {parcel.settlement_batch}",
					)
				else:
					outcome, reason = "matched", None

		if outcome == "matched":
			seen[awb] = row
			# an earlier file may have flagged this AWB as unknown; it is known now
			for unk in frappe.get_all(
				"COD Exception",
				pluck="name",
				filters={"exception_type": "Unknown AWB", "awb": awb, "status": "Open"},
			):
				frappe.db.set_value(
					"COD Exception",
					unk,
					{
						"status": "Resolved",
						"resolution": "Match to another line",
						"resolution_note": "Matched by reconciliation",
						"resolved_on": frappe.utils.now_datetime(),
					},
				)
			if remittance.courier and parcel.courier and parcel.courier != remittance.courier:
				upsert_exception(
					"Tracking mismatch",
					parcel.name,
					awb=awb,
					courier=remittance.courier,
					settlement_batch=remittance.name,
					detail=f"Settlement from {remittance.courier} but parcel shipped via {parcel.courier}",
				)
				counts["exceptions"] += 1
			result = reconcile_line(line, parcel)
			cleared += result["cleared"]
			if result["payout_status"] == "Short-paid":
				counts["short-paid"] += 1
			else:
				counts["matched"] += 1
			if not result["clean"]:
				counts["exceptions"] += 1
				has_mismatch = True
			continue

		# unmatched: never link the parcel, never touch its settlement numbers
		frappe.db.set_value(
			"Remittance Line",
			line.name,
			{"match_status": "Unknown", "cod_parcel": None, "expected_net": 0, "difference": 0},
		)
		counts["unknown"] += 1
		counts["exceptions"] += 1
		upsert_exception(
			exc_type,
			cod_parcel=parcel.name if parcel else None,
			awb=awb,
			courier=remittance.courier,
			settlement_batch=remittance.name,
			detail=reason,
			line_ref=f"{batch_ref}, row {row}",
			**(
				{"actual": flt(line.net_paid), "impact": flt(line.net_paid)}
				if exc_type == "Unknown AWB"
				else {}
			),
		)

	if skipped:
		from codsync.codsync.synclog import log_sync

		log_sync(
			"Excel" if (remittance.source or "Excel") == "Excel" else "Courier",
			"Reconciliation",
			"Success",
			reference_doctype="Courier Remittance",
			reference_name=remittance.name,
			error_message=f"{len(skipped)} row(s) skipped",
			response_payload={"skipped": skipped},
		)

	batch_status = "Mismatch" if has_mismatch else ("Pending review" if counts["unknown"] else "Reconciled")
	frappe.db.set_value(
		"Courier Remittance",
		remittance.name,
		{"batch_status": batch_status, "orders_count": len(remittance.lines)},
	)
	return {
		"batch_status": batch_status,
		"orders_count": len(remittance.lines),
		"cleared": cleared,
		"counts": counts,
		"skipped": skipped,
	}


@frappe.whitelist()
def raise_dispute(parcel):
	"""Open (or reuse) the parcel's COD Exception and mark the dispute as raised. Write role."""
	frappe.only_for(("System Manager", "CODSync Manager", "CODSync Operator"))
	doc = frappe.get_doc("COD Parcel", parcel)
	name = frappe.db.get_value("COD Exception", {"cod_parcel": doc.name, "status": "Open"})
	if name:
		exc = frappe.get_doc("COD Exception", name)
	else:
		impact = -flt(doc.cod_amount) if doc.payout_status == "Missing" else flt(doc.difference)
		exc = frappe.get_doc(
			{
				"doctype": "COD Exception",
				"exception_type": EXCEPTION_TYPE_BY_PAYOUT.get(doc.payout_status, "Amount mismatch"),
				"cod_parcel": doc.name,
				"awb": doc.awb,
				"courier": doc.courier,
				"settlement_batch": doc.settlement_batch,
				"expected": doc.expected_settlement,
				"actual": doc.actual_settlement,
				"impact": impact,
				"status": "Open",
				"opened_on": frappe.utils.now_datetime(),
			}
		)
	exc.resolution = "Raise dispute"
	exc.save(ignore_permissions=True)
	return exc.name


@frappe.whitelist()
def add_note(order_id, text):
	"""Add a note (Comment) to the parcel named by this order id."""
	doc = frappe.get_doc("COD Parcel", order_id)
	doc.add_comment("Comment", text)
	return True


def _act(kind, title, detail, when, ref_doctype=None, ref_name=None):
	return {
		"kind": kind,
		"title": title,
		"detail": detail or "",
		"event_time": get_datetime(when) if when else None,
		"ref_doctype": ref_doctype,
		"ref_name": ref_name,
	}


@frappe.whitelist()
def timeline(parcel):
	"""Build the order timeline (oldest first) from the parcel and related records."""
	doc = frappe.get_doc("COD Parcel", parcel)
	out = []

	if doc.order_date:
		out.append(
			_act(
				"done",
				"Order placed",
				f"{doc.payment_mode or 'COD'} order, total {flt(doc.order_total or doc.cod_amount)}",
				doc.order_date,
			)
		)
	if doc.awb:
		out.append(_act("done", "Shipment created", f"AWB {doc.awb}", doc.creation, "COD Parcel", doc.name))

	titles = {"in transit": "In transit", "out for delivery": "Out for delivery", "delivered": "Delivered"}
	for ev in doc.tracking_events or []:
		key = (ev.status or "").strip().lower()
		title = titles.get(key, ev.status)
		if key == "delivered" and doc.payment_mode != "Prepaid":
			title = "Delivered - COD collected"
		out.append(_act("done", title, ev.location, ev.event_time))

	batches = frappe.db.sql(
		"""select distinct r.name, r.utr_number, r.source, r.remittance_date, r.creation
		from `tabRemittance Line` l join `tabCourier Remittance` r on r.name = l.parent
		where l.cod_parcel = %s and r.docstatus = 1""",
		doc.name,
		as_dict=True,
	)
	for b in batches:
		out.append(
			_act(
				"done",
				"Settlement imported",
				f"Batch {b.name}, UTR {b.utr_number or '-'}, source {b.source or '-'}",
				b.remittance_date or b.creation,
				"Courier Remittance",
				b.name,
			)
		)

	for e in frappe.get_all(
		"COD Exception",
		filters={"cod_parcel": doc.name},
		fields=[
			"name",
			"exception_type",
			"detail",
			"status",
			"opened_on",
			"resolved_on",
			"resolution",
			"creation",
		],
	):
		out.append(
			_act(
				"warn",
				"Reconciliation mismatch",
				f"{e.exception_type}. {e.detail or ''}".strip(),
				e.opened_on or e.creation,
				"COD Exception",
				e.name,
			)
		)
		if e.status == "Resolved":
			out.append(
				_act(
					"done",
					"Exception resolved",
					e.resolution,
					e.resolved_on or e.creation,
					"COD Exception",
					e.name,
				)
			)

	for c in frappe.get_all(
		"Comment",
		filters={"reference_doctype": "COD Parcel", "reference_name": doc.name, "comment_type": "Comment"},
		fields=["content", "creation", "name"],
	):
		out.append(
			_act("grey", "Note", frappe.utils.strip_html(c.content or ""), c.creation, "Comment", c.name)
		)

	out.sort(key=lambda a: a["event_time"] or get_datetime("1970-01-01"))
	return out


# ---------------------------------------------------------------------------
# Derived display statuses (pure functions over a parcel dict / doc)
# ---------------------------------------------------------------------------

BLOCKING_EXCEPTIONS = {"Missing settlement", "Missing AWB", "Tracking mismatch", "Unknown AWB"}
MISMATCH_EXCEPTIONS = {"Unexpected deduction", "Amount mismatch", "Duplicate AWB"}


def _text(p, key):
	return (p.get(key) or "").strip().lower()


def _rto_phase(p):
	"""'initiated' / 'delivered' when the courier is returning the parcel, else None."""
	if p.get("status") != "RTO" and "rto" not in _text(p, "last_event"):
		return None
	if "deliver" in _text(p, "last_event") or "deliver" in _text(p, "last_event"):
		return "delivered"
	return "initiated"


def delivery_status(p):
	if p.get("order_status") == "Cancelled" or p.get("status") == "Cancelled":
		return "Cancelled"
	phase = _rto_phase(p)
	if phase:
		return f"RTO {phase}"
	if p.get("order_status") == "Returned":
		return "RTO delivered"
	if p.get("status") == "Delivered":
		return "Delivered"
	if not p.get("awb"):
		return "Fulfilled" if p.get("order_status") == "Fulfilled" else "Unfulfilled"
	events = _text(p, "last_event")
	if "out for delivery" in events:
		return "Out for delivery"
	if p.get("status") == "In Transit":
		return "In transit"
	return "Pickup scheduled"


def cod_status(p):
	if p.get("payment_mode") == "Prepaid":
		return "Not applicable"
	if p.get("payout_status") == "Unknown":
		return "Unknown"
	if not p.get("awb"):
		return "Awaiting shipment"
	if p.get("status") == "Delivered":
		return "Settled" if p.get("payout_status") in ("Paid", "Short-paid") else "Collected"
	return "Not collected"


def reconciliation_status(p, open_exception_types=()):
	if p.get("payment_mode") == "Prepaid":
		return None
	open_types = set(open_exception_types)
	if open_types & BLOCKING_EXCEPTIONS:
		return "Exception"
	if open_types & MISMATCH_EXCEPTIONS or p.get("payout_status") == "Short-paid":
		return "Mismatch"
	if p.get("payout_status") == "Paid":
		return "Reconciled"
	return "Pending"


@frappe.whitelist()
def statuses(parcel):
	"""delivery / COD / reconciliation status of one parcel."""
	doc = frappe.get_doc("COD Parcel", parcel).as_dict()
	open_types = frappe.get_all(
		"COD Exception", pluck="exception_type", filters={"cod_parcel": parcel, "status": "Open"}
	)
	return {
		"delivery_status": delivery_status(doc),
		"cod_status": cod_status(doc),
		"reconciliation_status": reconciliation_status(doc, open_types),
	}


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def _sync_exception(exception_type, parcels, condition, build, note, counts, keep=None):
	"""Open/update exceptions for parcels meeting `condition`; resolve ones that no longer do.

	`keep(exc)` blocks auto-resolution (used for settlement-courier mismatches,
	which the store-vs-courier detector does not know about).
	"""
	active = set()
	for p in parcels:
		if condition(p):
			active.add(p.name)
			upsert_exception(exception_type, p.name, awb=p.awb, courier=p.courier, **build(p))
	for exc in frappe.get_all(
		"COD Exception",
		fields=["name", "cod_parcel"],
		filters={
			"exception_type": exception_type,
			"status": "Open",
			"cod_parcel": ["in", [p.name for p in parcels] or [""]],
		},
	):
		if exc.cod_parcel not in active and not (keep and keep(exc)):
			frappe.db.set_value(
				"COD Exception",
				exc.name,
				{
					"status": "Resolved",
					"resolution": "Resolved manually",
					"resolution_note": note,
					"resolved_on": frappe.utils.now_datetime(),
				},
			)
			counts["resolved"] += 1
	counts["opened"][exception_type] = len(active)


def run_reconciliation(courier=None):
	"""Idempotent detectors (Missing settlement, Missing AWB, Tracking mismatch).

	Returns {"opened": {type: open count}, "resolved": n, "statuses": {reconciliation status: n}}.
	"""
	from codsync.codsync.matching import mark_missing

	couriers = [courier] if courier else frappe.get_all("Courier", filters={"is_active": 1}, pluck="name")
	for c in couriers:
		mark_missing(c)

	filters = {"courier": courier} if courier else {}
	fields = [
		"name",
		"awb",
		"courier",
		"status",
		"payout_status",
		"settlement_batch",
		"cod_amount",
		"expected_settlement",
		"order_status",
		"order_date",
		"creation",
		"last_event",
		"payment_mode",
		"delivered_date",
	]
	parcels = frappe.get_all("COD Parcel", filters=filters, fields=fields)
	counts = {"opened": {}, "resolved": 0}
	cutoff = add_to_date(frappe.utils.now_datetime(), hours=-24)

	_sync_exception(
		"Missing settlement",
		parcels,
		lambda p: p.status == "Delivered" and p.payout_status == "Missing" and not p.settlement_batch,
		lambda p: {
			"detail": f"Delivered {p.delivered_date}, no settlement received",
			"expected": flt(p.expected_settlement) or flt(p.cod_amount),
			"actual": 0,
			"impact": -(flt(p.expected_settlement) or flt(p.cod_amount)),
		},
		"Settlement received",
		counts,
	)

	_sync_exception(
		"Missing AWB",
		parcels,
		lambda p: p.order_status == "Fulfilled"
		and not p.awb
		and p.status != "Cancelled"
		and get_datetime(p.order_date or p.creation) < cutoff,
		lambda p: {"detail": "Fulfilled on the store for over 24h but no AWB"},
		"AWB added",
		counts,
	)

	def mismatch(p):
		phase = _rto_phase(p)
		return (p.order_status == "Fulfilled" and bool(phase)) or (
			p.order_status == "Cancelled" and p.status in ("In Transit", "Delivered")
		)

	_sync_exception(
		"Tracking mismatch",
		parcels,
		mismatch,
		lambda p: {"detail": f"Store {p.order_status}, courier {p.last_event or p.status}"},
		"Store and courier agree again",
		counts,
		keep=lambda e: (e.detail or "").startswith("Settlement from"),
	)

	open_by_parcel = {}
	for e in frappe.get_all(
		"COD Exception",
		fields=["cod_parcel", "exception_type"],
		filters={"status": "Open", "cod_parcel": ["is", "set"]},
	):
		open_by_parcel.setdefault(e.cod_parcel, set()).add(e.exception_type)
	statuses_count = {}
	for p in parcels:
		st = reconciliation_status(p, open_by_parcel.get(p.name, ()))
		if st:
			statuses_count[st] = statuses_count.get(st, 0) + 1
	counts["statuses"] = statuses_count
	return counts


# ---------------------------------------------------------------------------
# Settlement sync
# ---------------------------------------------------------------------------


def sync_settlements(courier):
	"""Fetch a settlement batch from the courier adapter and import it as a remittance."""
	from codsync.codsync.synclog import log_sync
	from codsync.codsync.tracking import NotSupported, get_adapter

	try:
		batch = get_adapter(courier).fetch_settlements(courier)
		if not batch or not batch.get("lines"):
			frappe.db.set_value("Courier", courier, "last_settlement_sync", frappe.utils.now_datetime())
			log_sync(
				"Courier",
				"Settlement Sync",
				"Success",
				reference_doctype="Courier",
				reference_name=courier,
				response_payload={"result": "no settlements"},
			)
			return None
		doc = frappe.get_doc(
			{
				"doctype": "Courier Remittance",
				"courier": courier,
				"source": "API",
				"remittance_id": batch["remittance_id"],
				"remittance_date": batch["remittance_date"],
				"utr_number": batch.get("utr_number"),
				"lines": batch["lines"],
			}
		)
		doc.insert(ignore_permissions=True)
		doc.submit()
		frappe.db.set_value(
			"Courier",
			courier,
			{
				"last_settlement_sync": frappe.utils.now_datetime(),
				"connection_status": "Connected",
				"last_error": "",
			},
		)
		log_sync(
			"Courier",
			"Settlement Sync",
			"Success",
			reference_doctype="Courier Remittance",
			reference_name=doc.name,
			response_payload={"result": "imported", "lines": len(batch["lines"])},
		)
		return doc.name
	except NotSupported:
		frappe.db.set_value("Courier", courier, "settlement_via", "Excel")
		log_sync(
			"Courier",
			"Settlement Sync",
			"Success",
			reference_doctype="Courier",
			reference_name=courier,
			response_payload={"result": "not supported, using Excel"},
		)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"CODSync sync_settlements: {courier}")
		frappe.db.set_value(
			"Courier", courier, {"connection_status": "Action needed", "last_error": str(e)[:140]}
		)
		log_sync(
			"Courier",
			"Settlement Sync",
			"Failed",
			reference_doctype="Courier",
			reference_name=courier,
			error_message=str(e),
		)
	return None


def run_hourly_settlement_sync():
	"""Hourly job: run each enabled courier's settlement sync once per day after its sync time."""
	now = frappe.utils.now_datetime()
	for c in frappe.get_all(
		"Courier",
		filters={"is_active": 1, "settlement_sync_enabled": 1},
		fields=["name", "settlement_sync_time", "last_settlement_sync"],
	):
		due_at = frappe.utils.get_datetime(f"{now.date()} {c.settlement_sync_time or '09:00:00'}")
		if now >= due_at and not (c.last_settlement_sync and c.last_settlement_sync >= due_at):
			sync_settlements(c.name)
