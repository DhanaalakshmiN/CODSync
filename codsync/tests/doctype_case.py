"""Shared setup for controller lifecycle tests."""

import frappe
from frappe.tests import IntegrationTestCase

from codsync.tests.helpers import Fixture


class DocTypeCase(IntegrationTestCase):
	prefix = "DTX"

	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user("Administrator")
		self.fx = Fixture(self.prefix)
		self.addCleanup(self.fx.cleanup)
		self.fx.default_settings()
		self.fx.make_courier()
