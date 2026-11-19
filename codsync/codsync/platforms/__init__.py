"""Shopify adapter registry for the standalone CODSync Shopify app."""

import frappe
from frappe import _

from codsync.codsync.platforms.shopify import ShopifyPlatform

PLATFORMS = {
	ShopifyPlatform.name: ShopifyPlatform,
}


def get_platform(name):
	"""Return the adapter instance for a platform name (default Shopify)."""
	cls = PLATFORMS.get(name) or ShopifyPlatform
	if name and name not in PLATFORMS:
		frappe.throw(_("Unknown platform {0}").format(name))
	return cls()
