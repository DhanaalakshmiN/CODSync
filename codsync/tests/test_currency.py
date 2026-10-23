"""Currency conversion, rate fallbacks and foreign-order tolerance. All network calls are mocked."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from codsync.codsync import currency
from codsync.codsync.engine import payout_decision
from codsync.codsync.rate_providers.base import ProviderError

FRANK = "codsync.codsync.rate_providers.frankfurter.FrankfurterProvider.get_rate"
OPEN_ER = "codsync.codsync.rate_providers.open_er_api.OpenErApiProvider.get_rate"
REQUESTS = "codsync.codsync.rate_providers.frankfurter.requests.get"


class TestCurrency(IntegrationTestCase):
	def setUp(self):
		self.conn = frappe.get_doc("Store Connection")
		self._saved = {
			f: self.conn.get(f)
			for f in ("base_currency", "rate_provider", "max_rate_age_days", "fx_tolerance_amount", "fx_tolerance_percent")
		}
		self.set_conn(
			base_currency="INR",
			rate_provider="Frankfurter",
			max_rate_age_days=7,
			fx_tolerance_amount=1,
			fx_tolerance_percent=0.5,
		)
		frappe.db.delete("Currency Rate", {"from_currency": "USD", "to_currency": "INR"})
		self.clear_cache()

	def tearDown(self):
		self.set_conn(**self._saved)
		frappe.db.delete("Currency Rate", {"from_currency": "USD", "to_currency": "INR"})
		self.clear_cache()

	def set_conn(self, **values):
		for k, v in values.items():
			frappe.db.set_single_value("Store Connection", k, v)
		frappe.clear_document_cache("Store Connection", "Store Connection")

	def clear_cache(self):
		for d in (today(), add_days(today(), -3), add_days(today(), -30)):
			frappe.cache.delete_value(currency.cache_key("USD", "INR", d))

	def add_row(self, days_ago, rate, source="API"):
		return frappe.get_doc(
			{
				"doctype": "Currency Rate",
				"from_currency": "USD",
				"to_currency": "INR",
				"rate_date": add_days(today(), -days_ago),
				"rate": rate,
				"source": source,
			}
		).insert(ignore_permissions=True)

	def test_base_currency_makes_no_api_call(self):
		with patch(FRANK) as f, patch(OPEN_ER) as o:
			self.assertEqual(currency.convert_to_base(100, "INR"), (100, 1.0, ""))
		f.assert_not_called()
		o.assert_not_called()

	def test_base_currency_comes_from_settings(self):
		self.set_conn(base_currency="USD")
		with patch(FRANK) as f:
			self.assertEqual(currency.get_rate_with_source("USD")[0], 1.0)
		f.assert_not_called()

	def test_foreign_order_uses_mocked_rate_and_saves_it(self):
		with patch(FRANK, return_value=94.47):
			total, rate, source = currency.convert_to_base(50, "USD")
		self.assertEqual((total, rate, source), (4723.5, 94.47, "API"))
		self.assertEqual(
			frappe.db.get_value("Currency Rate", {"from_currency": "USD", "rate_date": today()}, "source"),
			"API",
		)

	def test_api_failure_with_fresh_fallback(self):
		self.add_row(3, 93.0)
		with patch(FRANK, side_effect=ProviderError("down")), patch(OPEN_ER, side_effect=ProviderError("down")):
			rate, source = currency.get_rate_with_source("USD")
		self.assertEqual((rate, source), (93.0, "Fallback"))
		self.assertTrue(
			frappe.db.exists("Sync Log", {"status": "Warning", "operation": "Currency Rate"})
			or not self.conn.platform
		)

	def test_api_failure_with_expired_fallback_throws(self):
		self.add_row(30, 90.0)
		with patch(FRANK, side_effect=ProviderError("down")), patch(OPEN_ER, side_effect=ProviderError("down")):
			with self.assertRaises(frappe.ValidationError):
				currency.get_rate("USD")

	def test_second_provider_used_when_first_fails(self):
		with patch(FRANK, side_effect=ProviderError("unsupported")), patch(OPEN_ER, return_value=95.5):
			self.assertEqual(currency.get_rate_with_source("USD"), (95.5, "API"))

	def test_manual_rate_wins_over_api(self):
		self.add_row(0, 99.0, source="Manual")
		with patch(FRANK, return_value=94.0) as f, patch(OPEN_ER, return_value=94.0):
			self.assertEqual(currency.get_rate_with_source("USD"), (99.0, "Manual"))
		f.assert_not_called()

	def test_provider_http_call_is_mocked(self):
		class Resp:
			def raise_for_status(self):
				pass

			def json(self):
				return {"rates": {"INR": 91.25}}

		with patch(REQUESTS, return_value=Resp()) as get:
			self.assertEqual(currency.get_rate("USD"), 91.25)
		self.assertEqual(get.call_args.kwargs["params"], {"base": "USD", "symbols": "INR"})

	def test_tolerance_boundary_for_foreign_parcel(self):
		parcel = frappe._dict(order_currency="USD")
		# expected 1000 -> tolerance max(1.00, 0.5% = 5.00) = 5.00
		self.assertEqual(payout_decision(parcel, 1000, 995)[1:], (True, "Paid"))
		self.assertEqual(payout_decision(parcel, 1000, 994.99)[1:], (False, "Short-paid"))
		# small order: the absolute amount wins (expected 100 -> max(1.00, 0.50))
		self.assertEqual(payout_decision(parcel, 100, 99)[1:], (True, "Paid"))
		self.assertEqual(payout_decision(parcel, 100, 98.99)[1:], (False, "Short-paid"))

	def test_same_currency_keeps_plain_tolerance(self):
		parcel = frappe._dict(order_currency="INR")
		tolerance = frappe.db.get_single_value("Store Connection", "tolerance") or 1
		expected = 1000
		# 0.5% would be 5.00, but a base-currency parcel only gets the plain tolerance
		self.assertEqual(payout_decision(parcel, expected, expected - tolerance)[2], "Paid")
		self.assertEqual(payout_decision(parcel, expected, expected - tolerance - 0.01)[2], "Short-paid")

	def test_difference_value_is_not_changed_by_tolerance(self):
		difference, within, status = payout_decision(frappe._dict(order_currency="USD"), 1000, 997)
		self.assertEqual((difference, within, status), (-3, True, "Paid"))
