import os

import frappe

no_cache = 1


def get_context(context):
	"""Embedded shell loaded inside Shopify admin. Public: data calls carry the Shopify session token."""
	assets = frappe.get_app_path("codsync", "public", "frontend")

	def version(name):
		try:
			return int(os.path.getmtime(os.path.join(assets, name)))
		except OSError:
			return 0

	context.no_cache = 1
	context.show_sidebar = False
	context.title = "CODSync"
	context.api_key = frappe.conf.get("shopify_client_id") or ""
	context.codsync = frappe.as_json({"embedded": True, "csrf_token": "", "user": "Guest", "site": frappe.local.site})
	context.js_version = version("app.js")
	context.css_version = version("app.css")
