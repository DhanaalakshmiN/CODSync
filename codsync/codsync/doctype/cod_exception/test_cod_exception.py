"""Lifecycle tests for cod exception."""

import frappe
from frappe.utils import nowdate

from codsync.tests.doctype_case import DocTypeCase


class TestCODException(DocTypeCase):
	prefix = "DTE"

	def make(self, **kw):
		return frappe.get_doc(
			{"doctype": "COD Exception", "exception_type": "Amount mismatch", "courier": self.fx.courier, "status": "Open", "impact": -80, **kw}
		).insert(ignore_permissions=True)

	def test_opened_on_is_stamped_on_creation(self):
		self.assertTrue(self.make().opened_on)

	def test_resolved_on_is_stamped_when_resolved(self):
		exc = self.make()
		self.assertFalse(exc.resolved_on)
		exc.status = "Resolved"
		exc.save(ignore_permissions=True)
		self.assertTrue(exc.resolved_on)

	def test_raise_dispute_resolution_sets_the_claim(self):
		exc = self.make()
		exc.resolution = "Raise dispute"
		exc.save(ignore_permissions=True)
		self.assertEqual((exc.claim_amount, exc.dispute_status, str(exc.dispute_raised_on)), (80, "Raised with Courier", nowdate()))

	def test_raise_dispute_does_not_restart_a_dispute_in_progress(self):
		exc = self.make(dispute_status="Sent to courier", claim_amount=50)
		exc.resolution = "Raise dispute"
		exc.save(ignore_permissions=True)
		self.assertEqual((exc.claim_amount, exc.dispute_status), (50, "Sent to courier"))

	def test_unknown_exception_type_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.make(exception_type="Made up")


	def test_resolution_timestamp_is_preserved_on_later_save(self):
		exc = self.make(status="Resolved")
		resolved_on = exc.resolved_on
		exc.resolution_note = "Reviewed again"
		exc.save(ignore_permissions=True)
		self.assertEqual(exc.reload().resolved_on, resolved_on)
