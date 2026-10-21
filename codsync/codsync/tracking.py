import datetime

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime


class NotSupported(Exception):
	"""Adapter cannot provide this capability (e.g. API settlements)."""


class BaseAdapter:
	def fetch_settlements(self, courier):
		"""Return a remittance batch dict or None. Adapters without support raise NotSupported."""
		raise NotSupported(_("Settlement API not supported"))

	def get_tracking(self, awb):
		"""Return dict or None.

		Dict schema:
		    {
		        "events": [{"event_time": str, "status": str, "location": str}],
		        "status": str,
		        "delivered_date": str|None,
		    }
		"""
		raise NotImplementedError


_MOCK_SEQUENCE = [
	("Picked Up", None),
	("In Transit", None),
	("Out for Delivery", None),
	("Delivered", True),
]


class MockAdapter(BaseAdapter):
	"""Deterministic, network-free adapter for testing."""

	def fetch_settlements(self, courier):
		"""Batch: delivered parcels of this courier that have no settlement yet."""
		from codsync.codsync.engine import expected_for

		parcels = frappe.get_all(
			"COD Parcel",
			filters={
				"courier": courier,
				"status": "Delivered",
				"awb": ["is", "set"],
				"settlement_batch": ["is", "not set"],
				"payment_mode": "COD",
			},
			pluck="name",
		)
		lines = []
		for name in parcels:
			parcel = frappe.get_doc("COD Parcel", name)
			exp = expected_for(parcel)
			lines.append(
				{
					"awb": parcel.awb,
					"cod_amount": parcel.cod_amount,
					"freight": exp["expected_freight"],
					"cod_fee": exp["expected_cod_fee"],
					"gst": exp["expected_gst"],
					"net_paid": exp["expected_settlement"],
				}
			)
		stamp = now_datetime().strftime("%Y%m%d%H%M%S")
		return {
			"remittance_id": f"API-{courier}-{stamp}"[:140],
			"remittance_date": now_datetime().date(),
			"utr_number": f"MOCKUTR{stamp}",
			"lines": lines,
		}

	def get_tracking(self, awb):
		base = datetime.datetime(2026, 1, 1, 10, 0, 0)
		events = []
		delivered_date = None
		status = "Booked"
		for i, (s, is_delivered) in enumerate(_MOCK_SEQUENCE):
			ts = (base + datetime.timedelta(hours=i * 8)).strftime("%Y-%m-%d %H:%M:%S")
			events.append({"event_time": ts, "status": s, "location": "Hub"})
			status = s
			if is_delivered:
				delivered_date = ts[:10]
		return {"events": events, "status": status, "delivered_date": delivered_date}


_MILESTONE_MAP = {
	"delivered": "Delivered",
	"in_transit": "In Transit",
	"out_for_delivery": "In Transit",
	"failed_attempt": "In Transit",
	"available_for_pickup": "In Transit",
	"exception": "In Transit",
	"info_received": "Booked",
	"pending": "Booked",
}


class Ship24Adapter(BaseAdapter):
	def __init__(self, courier):
		self._courier = courier

	def _api_key(self):
		return frappe.get_doc("Courier", self._courier).get_password("api_key")

	def get_tracking(self, awb):
		import requests

		try:
			api_key = self._api_key()
			resp = requests.post(
				"https://api.ship24.com/public/v1/trackers/track",
				headers={
					"Authorization": f"Bearer {api_key}",
					"Content-Type": "application/json",
				},
				json={"trackingNumber": awb},
				timeout=20,
			)
			resp.raise_for_status()
			data = resp.json()
		except Exception:
			# Never raise; add a comment on the parcel later in caller
			return None

		trackings = (data.get("data") or {}).get("trackings") or []
		if not trackings:
			return None

		tracking = trackings[0]
		raw_events = tracking.get("events") or []
		events = []
		for ev in raw_events:
			ts = ev.get("occurrenceDatetime") or ""
			# Normalise ISO datetime string
			if ts and "T" in ts:
				ts = ts.replace("T", " ")[:19]
			events.append(
				{
					"event_time": ts,
					"status": ev.get("status") or "",
					"location": ev.get("location") or "",
				}
			)

		shipment = tracking.get("shipment") or {}
		milestone = (shipment.get("statusMilestone") or "").lower()
		status = _MILESTONE_MAP.get(milestone, "In Transit")

		delivered_date = None
		if status == "Delivered":
			for ev in reversed(events):
				if ev["event_time"]:
					delivered_date = ev["event_time"][:10]
					break

		return {"events": events, "status": status, "delivered_date": delivered_date}


def get_adapter(courier):
	"""Return the active tracking adapter for a courier, falling back to Mock."""
	account = frappe.db.get_value(
		"Courier", {"name": courier, "is_active": 1}, ["tracking_provider"], as_dict=True
	)
	if account and account.get("tracking_provider") == "Ship24":
		return Ship24Adapter(courier)
	return MockAdapter()


@frappe.whitelist()
def update_parcel_tracking(parcel):
	"""Fetch tracking events and append only NEW ones (dedupe on event_time+status).

	Updates parcel status and delivered_date. Never touches payout_status.
	"""
	doc = frappe.get_doc("COD Parcel", parcel)
	if not doc.awb:
		return
	adapter = get_adapter(doc.courier)
	result = adapter.get_tracking(doc.awb)

	if result is None:
		doc.add_comment("Comment", _("Tracking not found"))
		return

	# Build a set of existing (event_time, status) pairs
	existing = {(str(ev.event_time or ""), str(ev.status or "")) for ev in doc.tracking_events}

	new_events = []
	for ev in result.get("events") or []:
		key = (str(ev.get("event_time") or ""), str(ev.get("status") or ""))
		if key not in existing:
			new_events.append(ev)
			existing.add(key)

	for ev in new_events:
		doc.append(
			"tracking_events",
			{
				"event_time": ev.get("event_time"),
				"status": ev.get("status"),
				"location": ev.get("location"),
			},
		)

	new_status = result.get("status")
	if new_status:
		doc.status = new_status
	if result.get("delivered_date") and not doc.delivered_date:
		from frappe.utils import getdate

		doc.delivered_date = getdate(result["delivered_date"])

	if doc.tracking_events:
		last = doc.tracking_events[-1]
		doc.last_event, doc.last_event_at = last.status, last.event_time
	doc.save(ignore_permissions=True)
	if doc.courier:
		frappe.db.set_value("Courier", doc.courier, "last_tracking_sync", now_datetime())


@frappe.whitelist()
def sync_tracking(courier=None, parcel=None):
	"""Manually refresh tracking for one COD Parcel or all of a Courier's active parcels.

	Returns {"checked", "updated", "failed"} and writes one Sync Log row
	(platform Courier, operation Tracking Sync) with the counts and any error.
	"""
	from codsync.codsync.synclog import log_sync

	frappe.only_for(("System Manager", "CODSync Manager", "CODSync Operator"))
	if not (courier or parcel):
		frappe.throw(_("courier or parcel is required"))

	if parcel:
		if not frappe.db.get_value("COD Parcel", parcel, "awb"):
			frappe.throw(_("Parcel {0} has no AWB yet").format(parcel))
		targets = [parcel]
	else:
		targets = frappe.get_all(
			"COD Parcel",
			pluck="name",
			filters={"courier": courier, "status": ["in", ["Booked", "In Transit"]], "awb": ["is", "set"]},
		)

	snap = ("status", "last_event", "last_event_at")
	checked = updated = failed = 0
	error = None
	for name in targets:
		checked += 1
		try:
			before = frappe.db.get_value("COD Parcel", name, snap, as_dict=True)
			update_parcel_tracking(name)
			after = frappe.db.get_value("COD Parcel", name, snap, as_dict=True)
			if (after.status, after.last_event, after.last_event_at) != (
				before.status,
				before.last_event,
				before.last_event_at,
			):
				updated += 1
		except Exception as e:
			failed += 1
			error = error or str(e)
			frappe.log_error(frappe.get_traceback(), f"CODSync sync_tracking: {name}")

	result = {"checked": checked, "updated": updated, "failed": failed}
	log_sync(
		"Courier",
		"Tracking Sync",
		"Failed" if failed else "Success",
		reference_doctype="COD Parcel" if parcel else "Courier",
		reference_name=parcel or courier,
		error_message=error,
		response_payload=result,
	)
	return result


def _courier_due(courier):
	"""Courier tracking is due when enabled (or unconfigured) and its interval has elapsed."""
	c = frappe.db.get_value(
		"Courier",
		courier,
		["tracking_sync_enabled", "tracking_interval_min", "last_tracking_sync", "connection_status"],
		as_dict=True,
	)
	if not c:
		return True
	if not c.tracking_sync_enabled and c.connection_status:
		return False
	if c.last_tracking_sync and c.tracking_interval_min:
		return now_datetime() >= add_to_date(c.last_tracking_sync, minutes=c.tracking_interval_min)
	return True


def run_hourly_tracking():
	"""Scheduler job: refresh tracking for Booked/In Transit parcels."""
	from codsync.codsync.synclog import log_sync

	parcels = frappe.get_all(
		"COD Parcel",
		filters={"status": ["in", ["Booked", "In Transit"]], "awb": ["is", "set"]},
		fields=["name", "courier"],
	)
	due = {}
	for p in parcels:
		if p.courier not in due:
			due[p.courier] = _courier_due(p.courier)
	runs = {}  # courier -> {"ok": n, "failed": n, "error": first message}
	for p in parcels:
		if not due[p.courier]:
			continue
		run = runs.setdefault(p.courier, {"ok": 0, "failed": 0, "error": None})
		try:
			update_parcel_tracking(p.name)
			run["ok"] += 1
		except Exception as e:
			run["failed"] += 1
			run["error"] = run["error"] or str(e)
			frappe.log_error(frappe.get_traceback(), f"Tracking update failed: {p.name}")
	for courier, run in runs.items():
		log_sync(
			"Courier",
			"Tracking Sync",
			"Failed" if run["failed"] else "Success",
			reference_doctype="Courier",
			reference_name=courier,
			error_message=run["error"],
			response_payload=run,
		)
