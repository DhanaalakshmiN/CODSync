app_name = "codsync"
app_title = "CODSync"
app_publisher = "Dhanaa Lakshmi"
app_description = "Reconcile courier COD payouts with shipment records and identify paid, short-paid, missing, or unknown payments."
app_email = "dhanaalakshminarayanan@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "codsync",
# 		"logo": "/assets/codsync/logo.png",
# 		"title": "Codsync",
# 		"route": "/codsync",
# 		"has_permission": "codsync.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/codsync/css/codsync.css"
app_include_js = "/assets/codsync/js/import_dialog.js"
after_request = ["codsync.shopify_frame.allow_shopify_frame"]
auth_hooks = ["codsync.shopify_auth.authenticate"]
# include js, css files in header of web template
# web_include_css = "/assets/codsync/css/codsync.css"
# web_include_js = "/assets/codsync/js/codsync.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "codsync/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "codsync/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "codsync.utils.jinja_methods",
# 	"filters": "codsync.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "codsync.install.before_install"
# after_install = "codsync.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "codsync.uninstall.before_uninstall"
# after_uninstall = "codsync.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "codsync.utils.before_app_install"
# after_app_install = "codsync.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "codsync.utils.before_app_uninstall"
# after_app_uninstall = "codsync.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "codsync.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "codsync.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["codsync.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# COD Ledger single page app: /cod-ledger and every sub path render www/cod-ledger.html
website_route_rules = [
	{"from_route": "/cod-ledger/<path:app_path>", "to_route": "cod-ledger"},
]

scheduler_events = {
	"hourly": [
		"codsync.codsync.tracking.run_hourly_tracking",
		"codsync.codsync.engine.run_hourly_settlement_sync",
	],
	"daily": [
		"codsync.codsync.tasks.run_daily_mark_missing",
		"codsync.codsync.tasks.run_daily_reconciliation",
		"codsync.codsync.disputes.send_follow_ups",
	],
}

# Testing
# -------

# before_tests = "codsync.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "codsync.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "codsync.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "codsync.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["codsync.utils.before_request"]
# after_request = ["codsync.utils.after_request"]

# Job Events
# ----------
# before_job = ["codsync.utils.before_job"]
# after_job = ["codsync.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"codsync.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
