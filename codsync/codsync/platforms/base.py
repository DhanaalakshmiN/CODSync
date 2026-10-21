"""Platform adapter contract and the credential helper.

Adapters never read platform-specific Store Connection field names directly:
get_creds(conn) maps them to generic keys, so adding a platform never
scatters field names outside its adapter.
"""

import frappe
from frappe import _


def get_creds(conn):
	"""Generic credentials for a Store Connection doc.

	Returns {client_id, client_secret, api_key, api_version, webhook_secret, extra};
	passwords are decrypted, missing values are None.
	"""

	def val(field):
		v = conn.get(field)
		return v if v not in (None, "") else None

	def pwd(field):
		try:
			return conn.get_password(field, raise_exception=False)
		except Exception:
			return None

	platform = conn.get("platform")
	if platform == "Shopify":
		return {
			"client_id": val("shopify_client_id"),
			"client_secret": pwd("shopify_client_secret"),
			"api_version": val("shopify_api_version") or "2026-10",
			"webhook_secret": pwd("webhook_secret"),
			"extra": {},
		}
	if platform == "WooCommerce":
		return {
			"client_id": val("woo_consumer_key"),
			"client_secret": pwd("woo_consumer_secret"),
			"api_version": val("woo_api_version") or "wc/v3",
			"webhook_secret": pwd("webhook_secret"),
			"extra": {},
		}
	if platform == "Odoo":
		return {
			"client_id": val("odoo_username"),
			"client_secret": None,
			"api_key": pwd("odoo_api_key"),
			"api_version": None,
			"webhook_secret": None,
			"extra": {"database": val("odoo_database"), "url": val("store_url")},
		}
	return {
		"client_id": None,
		"client_secret": None,
		"api_key": None,
		"api_version": None,
		"webhook_secret": None,
		"extra": {},
	}


class BasePlatform:
	"""One storefront platform. Shopify is implemented; WooCommerce and Odoo follow.

	Adding a platform = one adapter file + its option on the platform Selects
	(Store Connection, COD Parcel, Sync Log).
	"""

	name = None

	def verify_webhook(self, headers, raw_body, conn):
		"""True when the webhook request is authentic for this connection."""
		raise NotImplementedError

	def parse_order(self, payload, conn):
		"""Map a platform order payload to COD Parcel field values.

		Returns a dict of COD Parcel fieldnames (order_id, platform, external_id,
		order_date, order_total, payment_mode, cod_amount, order_status, customer
		fields...) plus helper keys the caller applies: awb, tracking_company
		(the platform's courier label) and declared_weight.
		"""
		raise NotImplementedError

	def test_connection(self, conn):
		"""Return (ok, message) without placing an order."""
		raise NotImplementedError(frappe._("Platform {0} is not available yet").format(self.name))

	def fetch_orders(self, conn):
		"""Pull orders from the platform and upsert COD Parcels; return counts."""
		raise NotImplementedError(frappe._("Platform {0} is not available yet").format(self.name))

	def order_url(self, external_id, conn):
		"""Link to the order on the platform (None when not linkable)."""
		return None
