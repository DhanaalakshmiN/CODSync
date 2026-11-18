"""Lifecycle tests for cod parcel."""

import frappe

from codsync.tests.doctype_case import DocTypeCase


class TestCODParcel(DocTypeCase):
	prefix = "DTP"

	def test_order_id_is_unique(self):
		self.fx.make_parcel("1")
		with self.assertRaises(frappe.DuplicateEntryError):
			self.fx.make_parcel("1", awb="DTPOTHER1")

	def test_awb_is_unique(self):
		first = self.fx.make_parcel("2")
		with self.assertRaises((frappe.DuplicateEntryError, frappe.UniqueValidationError)):
			self.fx.make_parcel("3", awb=first.awb)

	def test_many_unfulfilled_orders_can_have_no_awb(self):
		a = self.fx.make_parcel("4", awb="", status="Booked", delivered_date=None)
		b = self.fx.make_parcel("5", awb="  ", status="Booked", delivered_date=None)
		self.assertIsNone(a.awb)
		self.assertIsNone(b.awb)

	def test_awb_is_upper_cased_and_spaces_removed(self):
		p = self.fx.make_parcel("6", awb=" dtp ab 12 ")
		self.assertEqual(p.awb, "DTPAB12")

	def test_prepaid_parcel_has_zero_cod(self):
		self.assertEqual(self.fx.make_parcel("7", payment_mode="Prepaid", cod=500).cod_amount, 0)

	def test_cod_amount_must_be_positive(self):
		for bad in (0, -10):
			with self.assertRaises(frappe.ValidationError):
				self.fx.make_parcel(f"8{abs(bad)}", cod=bad)

	def test_delivered_needs_a_delivered_date(self):
		with self.assertRaises(frappe.ValidationError):
			self.fx.make_parcel("9", status="Delivered", delivered_date=None)
		self.assertTrue(self.fx.make_parcel("10", status="In Transit", delivered_date=None).name)


	def test_save_normalizes_changed_awb(self):
		parcel = self.fx.make_parcel("SAVE")
		parcel.awb = " dtp updated 12 "
		parcel.save(ignore_permissions=True)
		self.assertEqual(parcel.reload().awb, "DTPUPDATED12")

	def test_save_rejects_delivery_without_date(self):
		parcel = self.fx.make_parcel("DELIVERY", status="In Transit", delivered_date=None)
		parcel.status = "Delivered"
		with self.assertRaisesRegex(frappe.ValidationError, "Delivered Date is required"):
			parcel.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("COD Parcel", parcel.name, "status"), "In Transit")
