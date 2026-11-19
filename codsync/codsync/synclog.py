"""Sync Log writer: one row per integration event.

Used by the webhook, tracking / settlement sync, Excel imports and the
connection test instead of only frappe.log_error. Never raises: a logging
failure must not break the caller.
"""

import json
from dataclasses import dataclass, replace

import frappe

MAX_PAYLOAD_CHARS = 16000


def _payload(value):
	if value in (None, ""):
		return None
	if not isinstance(value, str):
		value = json.dumps(value, default=str)
	return value[:MAX_PAYLOAD_CHARS]


@dataclass
class SyncLogDetails:
	"""Optional metadata for one integration event."""

	error_message: object = None
	error_code: str | None = None
	http_status: int | None = None
	endpoint: str | None = None
	external_id: object = None
	request_payload: object = None
	response_payload: object = None
	reference_doctype: str | None = None
	reference_name: str | None = None
	duration_ms: float | None = None
	attempt: int = 1


def log_sync(platform, operation, status, *, details: SyncLogDetails | None = None, **legacy_details):
	"""Insert an event with grouped metadata; existing metadata keywords remain supported."""
	try:
		d = replace(details or SyncLogDetails(), **legacy_details)
		frappe.get_doc(
			{
				"doctype": "Sync Log",
				"platform": platform,
				"operation": operation,
				"status": status,
				"attempt": d.attempt,
				"duration_ms": d.duration_ms,
				"http_status": d.http_status,
				"error_message": (d.error_message or None) and str(d.error_message)[:500],
				"error_code": d.error_code,
				"endpoint": d.endpoint,
				"request_payload": _payload(d.request_payload),
				"response_payload": _payload(d.response_payload),
				"external_id": str(d.external_id)[:140] if d.external_id else None,
				"reference_doctype": d.reference_doctype,
				"reference_name": d.reference_name,
			}
		).insert(
			ignore_permissions=True
		)  # nosemgrep: append-only integration audit logging, including rejected requests
	except Exception:
		frappe.log_error(frappe.get_traceback(), "CODSync log_sync")
