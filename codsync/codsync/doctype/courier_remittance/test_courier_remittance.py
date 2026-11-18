"""Lifecycle tests for courier remittance."""

import frappe
from frappe.utils import add_days, nowdate

from codsync.tests.doctype_case import DocTypeCase
from codsync.tests.helpers import NET_1KG


class TestCourierRemittance(DocTypeCase):
	prefix = "DTR"

	def line(self, awb, **kw):
		return {"awb": awb, "cod_amount": 1000, "freight": 50, "cod_fee": 20, "gst": 12.6, "net_paid": NET_1KG, **kw}

	def test_needs_at_least_one_line(self):
		with self.assertRaises(frappe.ValidationError):
			self.fx.make_remittance("EMPTY", [])

	def test_future_date_is_rejected(self):
		doc = frappe.get_doc(
			{
				"doctype": "Courier Remittance", "courier": self.fx.courier, "remittance_id": "DTR-FUT",
				"remittance_date": add_days(nowdate(), 3), "lines": [self.line("DTRX1")],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_totals_are_computed_from_lines(self):
		rem = self.fx.make_remittance("TOT", [self.line("DTRX2"), self.line("DTRX3", net_paid=500)])
		self.assertEqual(rem.total_cod, 2000)
		self.assertEqual(rem.total_deductions, 2 * (50 + 20 + 12.6))
		self.assertEqual(rem.total_net_paid, NET_1KG + 500)

	def test_remittance_id_is_unique(self):
		self.fx.make_remittance("DUP", [self.line("DTRX4")])
		with self.assertRaises(frappe.DuplicateEntryError):
			self.fx.make_remittance("DUP", [self.line("DTRX4")])

	def test_same_awb_twice_in_a_file_is_allowed_through(self):
		self.assertEqual(len(self.fx.make_remittance("TWICE", [self.line("DTRX5"), self.line("DTRX5")]).lines), 2)

	def test_submit_runs_matching_and_marks_missing(self):
		paid = self.fx.make_parcel("1")
		late = self.fx.make_parcel("2", delivered_date=add_days(nowdate(), -10))
		rem = self.fx.make_remittance("SUB", [self.line(paid.awb)], submit=True)
		self.assertEqual(rem.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Courier Remittance", rem.name, "batch_status"), "Reconciled")
		self.assertEqual(frappe.db.get_value("COD Parcel", paid.name, "payout_status"), "Paid")
		self.assertEqual(frappe.db.get_value("COD Parcel", late.name, "payout_status"), "Missing")

	def test_draft_remittance_is_not_matched(self):
		p = self.fx.make_parcel("3")
		self.fx.make_remittance("DRAFT", [self.line(p.awb)])
		self.assertFalse(frappe.db.get_value("COD Parcel", p.name, "settlement_batch"))


	def test_save_recomputes_totals_after_line_changes(self):
		rem = self.fx.make_remittance("EDIT", [self.line("DTREDIT")])
		rem.lines[0].cod_amount = 500
		rem.lines[0].freight = 30
		rem.lines[0].cod_fee = 10
		rem.lines[0].gst = 5
		rem.lines[0].net_paid = 455
		rem.save(ignore_permissions=True)
		rem.reload()
		self.assertEqual((rem.total_cod, rem.total_deductions, rem.total_net_paid), (500, 45, 455))
