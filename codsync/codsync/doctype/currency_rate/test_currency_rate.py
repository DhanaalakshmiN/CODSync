"""Lifecycle tests for currency rate."""

import frappe
from frappe.utils import add_days, nowdate

from codsync.tests.doctype_case import DocTypeCase


class TestCurrencyRate(DocTypeCase):
	prefix = "DTC"

	def setUp(self):
		super().setUp()
		self.rate_date = add_days(nowdate(), -10000)
		while frappe.db.exists("Currency Rate", f"AUD-INR-{self.rate_date}"):
			self.rate_date = add_days(self.rate_date, -1)

	def tearDown(self):
		name = f"AUD-INR-{self.rate_date}"
		if frappe.db.exists("Currency Rate", name):
			frappe.delete_doc("Currency Rate", name, ignore_permissions=True, force=True)
		super().tearDown()

	def make(self, **kw):
		values = {"doctype": "Currency Rate", "from_currency": "aud", "to_currency": "inr", "rate_date": self.rate_date, "rate": 55, "source": "Manual"}
		values.update(kw)
		return frappe.get_doc(values).insert(ignore_permissions=True)

	def test_codes_are_upper_cased_and_name_follows_the_pair_and_date(self):
		doc = self.make()
		self.assertEqual((doc.from_currency, doc.to_currency), ("AUD", "INR"))
		self.assertEqual(doc.name, f"AUD-INR-{self.rate_date}")

	def test_same_currency_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.make(to_currency="AUD")

	def test_rate_must_be_positive(self):
		for bad in (0, -1):
			with self.assertRaises(frappe.ValidationError):
				self.make(rate=bad)

	def test_second_rate_for_same_pair_and_day_is_rejected(self):
		self.make()
		with self.assertRaises(frappe.ValidationError):
			self.make(rate=56)

	def test_cached_rate_is_cleared_on_update_and_delete(self):
		from codsync.codsync.currency import cache_key

		doc = self.make()
		key = cache_key("AUD", "INR", doc.rate_date)
		frappe.cache.set_value(key, 55)
		doc.rate = 57
		doc.save(ignore_permissions=True)
		self.assertIsNone(frappe.cache.get_value(key))
		frappe.cache.set_value(key, 57)
		frappe.delete_doc("Currency Rate", doc.name, ignore_permissions=True, force=True)
		self.assertIsNone(frappe.cache.get_value(key))

