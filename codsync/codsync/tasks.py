"""Scheduled tasks for CODSync."""

import frappe

from codsync.codsync.engine import run_reconciliation
from codsync.codsync.matching import mark_missing


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
