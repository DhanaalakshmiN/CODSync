import os

import frappe

ROLES = {"CODSync Manager", "CODSync Operator", "CODSync Viewer", "System Manager"}
no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/cod-ledger"
		raise frappe.Redirect

	if not ROLES & set(frappe.get_roles()):
		raise frappe.PermissionError(frappe._("You need a CODSync role to open COD Ledger"))

	assets = frappe.get_app_path("codsync", "public", "frontend")

	def version(name):
		try:
			return int(os.path.getmtime(os.path.join(assets, name)))
		except OSError:
			return 0

	context.no_cache = 1
	context.show_sidebar = False
	context.title = "COD Ledger"
	context.codsync = frappe.as_json(
		{
			"csrf_token": frappe.sessions.get_csrf_token(),
			"user": frappe.session.user,
			"full_name": frappe.utils.get_fullname(),
			"site": frappe.local.site,
		}
	)
	context.js_version = version("app.js")
	context.css_version = version("app.css")
