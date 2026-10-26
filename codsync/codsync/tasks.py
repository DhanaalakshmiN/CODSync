"""Scheduled tasks for CODSync."""

import frappe

from codsync.codsync.engine import run_reconciliation
from codsync.codsync.matching import mark_missing


def run_daily_order_sync():
	"""Daily scheduler job: re-pull orders from the connected store.

	Webhooks are the primary feed; this is the safety net so a missed delivery
	(Shopify gives up after retries) never leaves the ledger stale. Upserts by
	external_id, so re-running is idempotent.
	"""
	conn = frappe.get_doc("Store Connection")
	if not conn.enabled:
		return
	try:
		frappe.set_user("Administrator")  # nosemgrep: scheduled job, not a web request
		conn.fetch_orders()
	except NotImplementedError:
		pass  # platform without order fetch (WooCommerce/Odoo stubs); already logged by the adapter
	except Exception:
		frappe.log_error(frappe.get_traceback(), "CODSync scheduled order sync")
	finally:
		frappe.db.commit()  # nosemgrep: scheduled job must persist its Sync Log rows


def run_daily_mark_missing():
	"""Daily scheduler job: run mark_missing for every active Courier."""
	couriers = frappe.get_all(
		"Courier",
		filters={"is_active": 1},
		pluck="name",
	)
	for courier in couriers:
		try:
			mark_missing(courier)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"mark_missing failed for courier: {courier}",
			)


def run_daily_reconciliation():
	"""Daily scheduler job: detectors (Missing settlement / Missing AWB / Tracking mismatch)."""
	try:
		run_reconciliation()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "CODSync run_reconciliation")
