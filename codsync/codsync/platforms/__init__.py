"""Platform adapter registry.

Adding a platform = one adapter file + its option on the platform Selects
(Store Connection, COD Parcel, Sync Log). api.py and ui_api.py only ever
call get_platform(); Shopify is fully implemented, WooCommerce and Odoo are
stubs that raise NotImplementedError until they are built.
"""

import frappe
from frappe import _

from codsync.codsync.platforms.base import BasePlatform, get_creds
from codsync.codsync.platforms.odoo import OdooPlatform
from codsync.codsync.platforms.shopify import ShopifyPlatform
from codsync.codsync.platforms.woocommerce import WooCommercePlatform

PLATFORMS = {
	ShopifyPlatform.name: ShopifyPlatform,
	WooCommercePlatform.name: WooCommercePlatform,
	OdooPlatform.name: OdooPlatform,
}


def get_platform(name):
	"""Return the adapter instance for a platform name (default Shopify)."""
	cls = PLATFORMS.get(name) or ShopifyPlatform
	if name and name not in PLATFORMS:
		frappe.throw(_("Unknown platform {0}").format(name))
	return cls()
