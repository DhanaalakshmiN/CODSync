"""DocType rules: validation, uniqueness, computed fields, hooks and role permissions."""

import frappe
from frappe.tests import IntegrationTestCase

from codsync.tests.doctype_case import DocTypeCase


class TestCourier(DocTypeCase):
	prefix = "DTS"

	def test_courier_name_is_unique(self):
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({"doctype": "Courier", "courier_name": self.fx.courier}).insert(ignore_permissions=True)


class TestPermissions(IntegrationTestCase):
	"""Role rules as configured on each DocType (read from metadata, so no user session or Redis needed)."""

	def can(self, doctype, role, ptype):
		return any(
			p.role == role and p.permlevel == 0 and p.get(ptype)
			for p in frappe.get_meta(doctype).permissions
		)

	def roles_with(self, doctype, ptype):
		return {p.role for p in frappe.get_meta(doctype).permissions if p.permlevel == 0 and p.get(ptype)}

	def test_viewer_reads_but_cannot_write(self):
		for dt in ("COD Parcel", "COD Exception", "Courier", "Courier Remittance", "Currency Rate"):
			self.assertTrue(self.can(dt, "CODSync Viewer", "read"), dt)
			for ptype in ("write", "create", "delete"):
				self.assertFalse(self.can(dt, "CODSync Viewer", ptype), f"{dt} {ptype}")

	def test_operator_can_work_on_orders_and_exceptions(self):
		for dt in ("COD Parcel", "COD Exception"):
			self.assertTrue(self.can(dt, "CODSync Operator", "read"), dt)
			self.assertTrue(self.can(dt, "CODSync Operator", "write"), dt)

	def test_managers_can_edit_couriers_and_rates(self):
		for dt in ("Courier", "Currency Rate"):
			self.assertTrue(self.can(dt, "CODSync Manager", "write"), dt)

	def test_store_connection_is_for_managers_only(self):
		self.assertEqual(self.roles_with("Store Connection", "read"), {"CODSync Manager", "System Manager"})
		self.assertEqual(self.roles_with("Store Connection", "write"), {"CODSync Manager", "System Manager"})

	def test_sync_log_is_hidden_from_operators_but_not_viewers(self):
		self.assertTrue(self.can("Sync Log", "CODSync Viewer", "read"))
		self.assertFalse(self.can("Sync Log", "CODSync Operator", "read"))
		self.assertEqual(self.roles_with("Sync Log", "write") - {"System Manager"}, set())

	def test_every_codsync_role_exists(self):
		for role in ("CODSync Manager", "CODSync Operator", "CODSync Viewer"):
			self.assertTrue(frappe.db.exists("Role", role), role)
