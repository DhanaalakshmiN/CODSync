"""Store settings lifecycle and whitelisted controller methods; no external requests."""

from unittest.mock import patch

import frappe

from codsync.tests.doctype_case import DocTypeCase

CONTROLLER = "codsync.codsync.doctype.store_connection.store_connection"


class TestStoreConnection(DocTypeCase):
	prefix = "DTSC"

	def setUp(self):
		super().setUp()
		self.fx.set_settings(platform="Shopify", store_url="test-shop.myshopify.com")

	def test_base_currency_is_upper_cased_on_save(self):
		self.fx.set_settings(base_currency="inr")
		doc = frappe.get_doc("Store Connection")
		doc.base_currency = "usd"
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.reload().base_currency, "USD")

	def test_blank_base_currency_falls_back_to_default(self):
		doc = frappe.get_doc("Store Connection")
		doc.base_currency = ""
		with patch("codsync.codsync.currency.default_base_currency", return_value="INR"):
			doc.save(ignore_permissions=True)
		self.assertEqual(doc.reload().base_currency, "INR")

	def connection(self):
		return frappe.get_doc("Store Connection")

	def test_test_connection_returns_adapter_result(self):
		doc = self.connection()
		with patch(f"{CONTROLLER}.get_platform") as get_platform:
			get_platform.return_value.test_connection.return_value = (True, "Connected")
			self.assertEqual(
				doc.test_connection(), {"ok": True, "message": "Connected", "platform": "Shopify"}
			)
			get_platform.assert_called_once_with("Shopify")
			get_platform.return_value.test_connection.assert_called_once_with(doc)

	def test_unsupported_connection_returns_failure(self):
		doc = self.connection()
		with patch(f"{CONTROLLER}.get_platform") as get_platform:
			get_platform.return_value.test_connection.side_effect = NotImplementedError("Not supported")
			self.assertEqual(
				doc.test_connection(), {"ok": False, "message": "Not supported", "platform": "Shopify"}
			)

	def test_fetch_orders_returns_adapter_result(self):
		doc = self.connection()
		with patch(f"{CONTROLLER}.get_platform") as get_platform:
			get_platform.return_value.fetch_orders.return_value = {"created": 2}
			self.assertEqual(doc.fetch_orders(), {"created": 2})
			get_platform.return_value.fetch_orders.assert_called_once_with(doc)

	def test_unsupported_fetch_raises_validation_error(self):
		doc = self.connection()
		with patch(f"{CONTROLLER}.get_platform") as get_platform:
			get_platform.return_value.fetch_orders.side_effect = NotImplementedError("Not supported")
			with self.assertRaisesRegex(frappe.ValidationError, "Not supported"):
				doc.fetch_orders()

	def test_recalculation_returns_engine_result(self):
		doc = self.connection()
		with patch(
			"codsync.codsync.engine.recalculate_currency_amounts", return_value={"checked": 2}
		) as recalculate:
			self.assertEqual(doc.recalculate_currency_amounts(), {"checked": 2})
			recalculate.assert_called_once_with()

	def test_viewer_cannot_call_manager_methods(self):
		doc = self.connection()
		viewer = self.fx.make_user("CODSync Viewer")
		frappe.set_user(viewer)
		try:
			with (
				patch(f"{CONTROLLER}.get_platform") as get_platform,
				patch("codsync.codsync.engine.recalculate_currency_amounts") as recalculate,
			):
				for method in (doc.test_connection, doc.fetch_orders, doc.recalculate_currency_amounts):
					with self.subTest(method=method.__name__), self.assertRaises(frappe.PermissionError):
						method()
				get_platform.assert_not_called()
				recalculate.assert_not_called()
		finally:
			frappe.set_user("Administrator")
