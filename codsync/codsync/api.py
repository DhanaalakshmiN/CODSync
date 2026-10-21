"""CODSync public API endpoints.

webhook()      - guest-accessible; the platform adapter (codsync.codsync.platforms)
                 verifies the request, process_order() upserts the COD Parcel in
                 the background. No platform logic lives here.
process_order() - internal, runs in the worker.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from codsync.codsync.platforms import get_platform
from codsync.codsync.synclog import log_sync


@frappe.whitelist(allow_guest=True)
def webhook():
	"""Receive a store webhook: adapter verifies it, processing is enqueued."""
	raw_body = frappe.request.get_data()
	headers = frappe.request.headers

	conn = frappe.get_cached_doc("Store Connection")
	if not conn.enabled:
		frappe.response["http_status_code"] = 403
		return {"error": "Store connection is disabled"}

	platform = get_platform(conn.platform)
	if not platform.verify_webhook(headers, raw_body, conn):
		log_sync(
			conn.platform,
			"Webhook Order",
			"Failed",
			error_message="Invalid webhook signature or shop",
			endpoint=frappe.request.path,
		)
		frappe.response["http_status_code"] = 401
		return {"error": "Invalid signature"}

	try:
		payload = json.loads(raw_body)
	except Exception:
		frappe.response["http_status_code"] = 400
		return {"error": "Invalid JSON"}

	frappe.enqueue(
		"codsync.codsync.api.process_order",
		payload=payload,
		queue="short",
		is_async=True,
	)
	log_sync(
		conn.platform,
		"Webhook Order",
		"Success",
		external_id=str(payload.get("id") or ""),
		endpoint=frappe.request.path,
	)
	frappe.response["http_status_code"] = 200
	return {"status": "queued"}


# webhooks registered before the endpoint was renamed still point here
shopify_webhook = webhook


def process_order(payload):
	"""Upsert the COD Parcel for a platform order payload. Runs in the worker."""
	conn = frappe.get_cached_doc("Store Connection")
	try:
		_upsert_order(get_platform(conn.platform).parse_order(payload, conn), conn)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "CODSync process_order")
		order_ref = (
			payload.get("name") or payload.get("order_number") or payload.get("id") or "?"
			if isinstance(payload, dict)
			else "?"
		)
		log_sync(
			conn.platform,
			"Webhook Order",
			"Failed",
			error_message=f"Order {order_ref}: {e}",
			external_id=str(payload.get("id") or ""),
			response_payload={"payload_keys": sorted(payload)} if isinstance(payload, dict) else None,
		)


def _upsert_order(values, conn):
	order_id = values.pop("order_id")
	if not order_id:
		return
	awb = values.pop("awb", None)
	tracking_company = values.pop("tracking_company", None)
	declared_weight = flt(values.pop("declared_weight", None) or 0)

	existed = frappe.db.exists("COD Parcel", order_id)
	if existed:
		parcel = frappe.get_doc("COD Parcel", order_id)
		parcel.update(values)
	else:
		parcel = frappe.get_doc({"doctype": "COD Parcel", "order_id": order_id, "status": "Booked", **values})
	if parcel.order_status == "Cancelled":
		parcel.status = "Cancelled"

	# AWB / courier / weight are set once, when the first fulfillment with tracking arrives
	if awb and not parcel.awb:
		owner = frappe.db.get_value("COD Parcel", {"awb": awb})
		if not owner or owner == parcel.name:
			parcel.awb = awb
			parcel.courier = _resolve_courier(tracking_company, conn)
			if declared_weight:
				parcel.declared_weight = declared_weight

	if existed:
		parcel.save(ignore_permissions=True)
	else:
		parcel.insert(ignore_permissions=True)
	frappe.db.set_single_value("Store Connection", "last_synced_on", now_datetime())


def _resolve_courier(source_name, conn):
	"""Map the platform's courier label to a Courier via Store Connection courier_mapping."""
	if source_name:
		for row in conn.courier_mapping or []:
			if (row.source_name or "").strip().lower() == source_name.strip().lower():
				return row.courier
	if conn.default_courier:
		return conn.default_courier
	if source_name:
		if not frappe.db.exists("Courier", source_name):
			frappe.get_doc({"doctype": "Courier", "courier_name": source_name}).insert(
				ignore_permissions=True
			)
		return source_name
	frappe.throw(_("Cannot determine courier for order"))


@frappe.whitelist()
def sync_orders():
	"""Fetch orders from the connected store and upsert COD Parcels."""
	frappe.only_for(("System Manager", "CODSync Manager"))
	conn = frappe.get_doc("Store Connection")
	try:
		return get_platform(conn.platform).fetch_orders(conn)
	except NotImplementedError as e:
		frappe.throw(str(e))
