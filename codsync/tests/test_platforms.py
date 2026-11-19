"""Shopify-only configuration and existing Shopify integration behavior, without a database."""

import base64
import hashlib
import hmac
import inspect
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe

from codsync.codsync import api, platforms, ui_api
from codsync.codsync.platforms.base import get_creds
from codsync.codsync.platforms.shopify import ShopifyPlatform

ROOT = Path(__file__).resolve().parents[1]


class TestShopifyOnly(unittest.TestCase):
	def test_registry_keeps_shopify_and_default(self):
		self.assertEqual(set(platforms.PLATFORMS), {"Shopify"})
		for name in ("Shopify", "", None):
			self.assertIsInstance(platforms.get_platform(name), ShopifyPlatform)

	def test_removed_platforms_are_rejected(self):
		for name in ("WooCommerce", "Odoo", "Unknown"):
			with (
				self.subTest(platform=name),
				patch.object(platforms, "_", side_effect=lambda text: text),
				patch.object(platforms.frappe, "throw", side_effect=frappe.ValidationError),
			):
				with self.assertRaises(frappe.ValidationError):
					platforms.get_platform(name)

	def connection(self):
		values = {
			"platform": "Shopify",
			"shopify_client_id": "test-client",
			"shopify_api_version": "2026-10",
			"store_url": "example.myshopify.com",
		}
		passwords = {
			"shopify_client_secret": "test-secret",
			"webhook_secret": "test-signing-secret",
			"rate_api_key": "test-rate-key",
		}
		conn = MagicMock()
		conn.get.side_effect = values.get
		conn.get_password.side_effect = lambda field, **kwargs: passwords.get(field)
		conn.store_url = values["store_url"]
		return conn

	def test_existing_shopify_credentials_and_rate_key_are_preserved(self):
		conn = self.connection()
		self.assertEqual(
			get_creds(conn),
			{
				"client_id": "test-client",
				"client_secret": "test-secret",
				"api_version": "2026-10",
				"webhook_secret": "test-signing-secret",
				"extra": {},
				"rate_api_key": "test-rate-key",
			},
		)
		conn.save.assert_not_called()
		conn.set.assert_not_called()

	def test_shopify_api_version_default_is_preserved(self):
		conn = self.connection()
		original = conn.get.side_effect
		conn.get.side_effect = lambda field: None if field == "shopify_api_version" else original(field)
		self.assertEqual(get_creds(conn)["api_version"], "2026-10")

	def test_signed_shopify_webhook_still_verifies(self):
		body = b'{"id": 123}'
		signature = base64.b64encode(hmac.new(b"test-signing-secret", body, hashlib.sha256).digest()).decode()
		headers = {"X-Shopify-Shop-Domain": "example.myshopify.com", "X-Shopify-Hmac-Sha256": signature}
		adapter = platforms.get_platform("Shopify")
		self.assertTrue(adapter.verify_webhook(headers, body, self.connection()))
		self.assertFalse(adapter.verify_webhook(headers, b'{"id": 456}', self.connection()))
		self.assertFalse(
			adapter.verify_webhook(
				{**headers, "X-Shopify-Shop-Domain": "other.myshopify.com"}, body, self.connection()
			)
		)
		self.assertIs(api.shopify_webhook, api.webhook)

	def test_cod_and_prepaid_order_mapping_is_preserved(self):
		adapter = ShopifyPlatform()
		with (
			patch("codsync.codsync.platforms.shopify.get_base_currency", return_value="INR"),
			patch("codsync.codsync.platforms.shopify.convert_to_base", return_value=(1000, 1, "")),
		):
			payload = {
				"id": 123,
				"name": "#123",
				"total_price": "1000",
				"currency": "INR",
				"payment_gateway_names": ["Cash on delivery"],
				"fulfillments": [{"tracking_number": " ab 123 ", "tracking_company": "Courier"}],
			}
			cod = adapter.parse_order(payload, self.connection())
			prepaid = adapter.parse_order({**payload, "payment_gateway_names": ["Card"]}, self.connection())
		self.assertEqual(
			(cod["order_id"], cod["platform"], cod["cod_amount"], cod["awb"]),
			("#123", "Shopify", 1000, "AB123"),
		)
		self.assertEqual((prepaid["payment_mode"], prepaid["cod_amount"]), ("Prepaid", 0))

	def test_metadata_removes_other_credentials_without_renaming_shopify_fields(self):
		doc = json.loads((ROOT / "codsync/doctype/store_connection/store_connection.json").read_text())
		fields = {field["fieldname"]: field for field in doc["fields"]}
		self.assertEqual(fields["platform"]["options"], "Shopify")
		self.assertEqual(fields["platform"]["default"], "Shopify")
		self.assertTrue(
			{
				"shopify_client_id",
				"shopify_client_secret",
				"shopify_api_version",
				"access_token",
				"token_expiry",
				"webhook_secret",
			}
			<= fields.keys()
		)
		self.assertFalse(any(name.startswith(("woo_", "odoo_", "woocommerce_")) for name in fields))
		self.assertTrue(set(doc["field_order"]) <= fields.keys())
		for doctype, expected in (
			("cod_parcel", {"Shopify", "Excel", "Manual"}),
			("sync_log", {"Shopify", "Courier", "Excel"}),
		):
			doc = json.loads((ROOT / f"codsync/doctype/{doctype}/{doctype}.json").read_text())
			field = next(field for field in doc["fields"] if field["fieldname"] == "platform")
			self.assertEqual(set(field["options"].split()), expected)

	def test_settings_response_exposes_only_shopify_configuration(self):
		doc = frappe._dict(
			platform="Shopify",
			store_url="example.myshopify.com",
			shopify_api_version="2026-10",
			courier_mapping=[],
		)
		with (
			patch.object(ui_api, "_read"),
			patch.object(ui_api, "_is_saved", return_value=True),
			patch.object(ui_api, "frappe", MagicMock()) as mocked,
		):
			mocked.get_doc.return_value = doc
			mocked.get_list.return_value = []
			mocked.get_roles.return_value = []
			out = inspect.unwrap(ui_api.settings)()
		self.assertEqual(out["platforms"], ["Shopify"])
		self.assertEqual(set(out["saved"]), {"shopify_client_id", "shopify_client_secret", "webhook_secret"})
		self.assertFalse(any(name.startswith(("woo_", "odoo_")) for name in out["store"]))

	def test_settings_reject_removed_platforms_before_saving(self):
		for platform in ("WooCommerce", "Odoo"):
			with (
				self.subTest(platform=platform),
				patch.object(ui_api, "_manager"),
				patch.object(ui_api, "_", side_effect=lambda text: text),
				patch.object(ui_api, "frappe", MagicMock()) as mocked,
			):
				mocked.throw.side_effect = frappe.ValidationError
				with self.assertRaises(frappe.ValidationError):
					inspect.unwrap(ui_api.save_settings)({"platform": platform})
				mocked.get_doc.return_value.save.assert_not_called()

	def test_blank_secret_is_not_overwritten_when_saving_shopify_settings(self):
		with (
			patch.object(ui_api, "_manager"),
			patch.object(ui_api, "settings", return_value={}),
			patch.object(ui_api, "frappe", MagicMock()) as mocked,
		):
			doc = mocked.get_doc.return_value
			doc.enabled = True
			doc.store_url = "example.myshopify.com"
			inspect.unwrap(ui_api.save_settings)(
				{"platform": "Shopify", "store_name": "Updated", "shopify_client_secret": ""}
			)
			doc.set.assert_called_once_with("store_name", "Updated")
			doc.save.assert_called_once_with()
