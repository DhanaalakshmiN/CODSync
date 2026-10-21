"""Sync Log writer: one row per integration event.

Used by the webhook, tracking / settlement sync, Excel imports and the
connection test instead of only frappe.log_error. Never raises: a logging
failure must not break the caller.
"""

import json

import frappe

MAX_PAYLOAD_CHARS = 16000


def _payload(value):
	if value in (None, ""):
		return None
	if not isinstance(value, str):
		value = json.dumps(value, default=str)
	return value[:MAX_PAYLOAD_CHARS]


def log_sync(
	platform,
	operation,
	status,
	*,
	error_message=None,
	error_code=None,
	http_status=None,
	endpoint=None,
	external_id=None,
	request_payload=None,
	response_payload=None,
	reference_doctype=None,
	reference_name=None,
	duration_ms=None,
	attempt=1,
):
	"""Insert a Sync Log row. platform: Shopify/WooCommerce/Odoo/Courier/Excel."""
	try:
		frappe.get_doc(
			{
				"doctype": "Sync Log",
				"platform": platform,
				"operation": operation,
				"status": status,
				"attempt": attempt,
				"duration_ms": duration_ms,
				"http_status": http_status,
				"error_message": (error_message or None) and str(error_message)[:500],
				"error_code": error_code,
				"endpoint": endpoint,
				"request_payload": _payload(request_payload),
				"response_payload": _payload(response_payload),
				"external_id": str(external_id)[:140] if external_id else None,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "CODSync log_sync")
