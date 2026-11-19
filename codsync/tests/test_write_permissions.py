"""Role-gated writes also enforce the caller's normal DocType permissions."""

import inspect
from contextlib import contextmanager
from unittest.mock import patch

import frappe

from codsync.codsync import engine, tracking, ui_api
from codsync.tests.doctype_case import DocTypeCase


class TestWritePermissions(DocTypeCase):
	prefix = "PERMW"

	@contextmanager
	def as_role(self, role):
		user = self.fx.make_user(role)
		previous_user = frappe.session.user
		try:
			frappe.set_user(user)
			yield
		finally:
			frappe.set_user(previous_user)

	def test_viewer_cannot_raise_dispute(self):
		parcel = self.fx.make_parcel("DENIED", payout_status="Missing")
		with self.as_role("CODSync Viewer"), self.assertRaises(frappe.PermissionError):
			inspect.unwrap(engine.raise_dispute)(parcel.name)
		self.assertFalse(frappe.db.exists("COD Exception", {"cod_parcel": parcel.name}))

	def test_operator_can_raise_and_resolve_dispute(self):
		parcel = self.fx.make_parcel("ALLOWED", payout_status="Missing")
		with self.as_role("CODSync Operator"):
			name = inspect.unwrap(engine.raise_dispute)(parcel.name)
			self.assertEqual(
				frappe.db.get_value("COD Exception", name, "dispute_status"), "Raised with Courier"
			)
			result = inspect.unwrap(ui_api.resolve_exception)(name, "resolve_manually", {"note": "Reviewed"})
			self.assertEqual(result["status"], "Resolved")

	def test_internal_exception_writer_enforces_doctype_permissions(self):
		with self.as_role("CODSync Viewer"), self.assertRaises(frappe.PermissionError):
			engine.upsert_exception("Unknown AWB", awb="PERMWDENIED", courier=self.fx.courier)
		self.assertFalse(frappe.db.exists("COD Exception", {"awb": "PERMWDENIED"}))
		with self.as_role("CODSync Operator"):
			exc = engine.upsert_exception("Unknown AWB", awb="PERMWALLOWED", courier=self.fx.courier)
			self.assertTrue(exc.name)

	def test_viewer_cannot_update_tracking(self):
		parcel = self.fx.make_parcel("TRACKDENIED", status="Booked", delivered_date=None)
		with self.as_role("CODSync Viewer"), patch.object(tracking, "get_adapter") as adapter:
			with self.assertRaises(frappe.PermissionError):
				inspect.unwrap(tracking.update_parcel_tracking)(parcel.name)
			adapter.assert_not_called()

	def test_operator_can_update_tracking(self):
		parcel = self.fx.make_parcel("TRACKALLOWED", status="Booked", delivered_date=None)
		with self.as_role("CODSync Operator"), patch.object(tracking, "get_adapter") as adapter:
			adapter.return_value.get_tracking.return_value = {"events": [], "status": "In Transit"}
			inspect.unwrap(tracking.update_parcel_tracking)(parcel.name)
		self.assertEqual(parcel.reload().status, "In Transit")
