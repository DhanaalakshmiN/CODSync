"""Shared builders for the matching / reconciliation / refund tests.

Every test creates its own Courier with a known rate card, so no expected
amount depends on the site's data:
  COD fee 2 %, GST 18 % (on fee + freight), base freight 50 up to 1 kg,
  +10 per extra kg, payout cycle 7 days, tolerance 1.00, fx tolerance max(1.00, 0.5 %).
  COD 1000 at 1 kg -> 1000 - 20 - 50 - 12.60 = 917.40
  COD 1000 at 3 kg -> 1000 - 20 - 70 - 16.20 = 893.80
"""

import frappe
from frappe.utils import add_days, nowdate

RATE_CARD = {
	"cod_fee_percent": 2,
	"gst_percent": 18,
	"base_weight_kg": 1,
	"base_freight": 50,
	"additional_freight_per_kg": 10,
	"payout_cycle_days": 7,
}
NET_1KG = 917.40  # COD 1000, declared 1 kg
NET_3KG = 893.80  # COD 1000, declared 3 kg


class Fixture:
	"""Creates records under one courier name and removes them all again."""

	def __init__(self, prefix):
		self.prefix = prefix
		self.courier = f"{prefix}-COURIER"
		self._saved_conn = {}
		self.users = []

	# ---- users ----------------------------------------------------------------
	def make_user(self, role, key=None):
		"""A throw-away enabled user holding only `role`; returns the email."""
		email = f"{self.prefix.lower()}-{key or role.split()[-1].lower()}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "User", "email": email, "first_name": self.prefix, "enabled": 1,
				"send_welcome_email": 0, "roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)
		self.users.append(email)
		return email

	# ---- store settings -------------------------------------------------
	def set_settings(self, **values):
		for k, v in values.items():
			self._saved_conn.setdefault(k, frappe.db.get_single_value("Store Connection", k))
			frappe.db.set_single_value("Store Connection", k, v)
		frappe.clear_document_cache("Store Connection", "Store Connection")

	def default_settings(self):
		self.set_settings(
			base_currency="INR", tolerance=1, fx_tolerance_amount=1, fx_tolerance_percent=0.5
		)

	# ---- records ----------------------------------------------------------
	def make_courier(self, name=None, **extra):
		name = name or self.courier
		self.purge_courier(name)
		doc = frappe.get_doc(
			{"doctype": "Courier", "courier_name": name, "is_active": 1, **RATE_CARD, **extra}
		).insert(ignore_permissions=True)
		frappe.clear_document_cache("Courier", doc.name)
		return doc.name

	def make_parcel(self, key, courier=None, cod=1000, **kw):
		values = {
			"doctype": "COD Parcel",
			"order_id": f"{self.prefix}-{key}",
			"courier": courier or self.courier,
			"awb": f"{self.prefix}AWB{key}".replace("-", ""),
			"payment_mode": "COD",
			"cod_amount": cod,
			"status": "Delivered",
			"delivered_date": nowdate(),
			"declared_weight": 1,
		}
		values.update(kw)
		return frappe.get_doc(values).insert(ignore_permissions=True)

	def make_remittance(self, rid, lines, courier=None, submit=False):
		"""lines: dicts with at least awb + net_paid. Draft unless submit=True (submit runs matching)."""
		doc = frappe.get_doc(
			{
				"doctype": "Courier Remittance",
				"courier": courier or self.courier,
				"remittance_id": f"{self.prefix}-{rid}",
				"remittance_date": nowdate(),
				"source": "Excel",
				"lines": lines,
			}
		).insert(ignore_permissions=True)
		if submit:
			doc.submit()
		return doc

	def exceptions(self, **filters):
		return frappe.get_all(
			"COD Exception",
			filters={"courier": self.courier, **filters},
			fields=["name", "exception_type", "status", "awb", "cod_parcel", "dispute_status"],
		)

	# ---- cleanup ----------------------------------------------------------
	def purge_courier(self, name):
		remittances = frappe.get_all("Courier Remittance", filters={"courier": name}, pluck="name")
		parcels = frappe.get_all("COD Parcel", filters={"courier": name}, pluck="name")
		excs = frappe.get_all("COD Exception", filters={"courier": name}, pluck="name") + (
			frappe.get_all("COD Exception", filters={"cod_parcel": ["in", parcels]}, pluck="name") if parcels else []
		)
		if excs:
			frappe.db.delete("Dispute Stage Log", {"parent": ["in", excs]})
			frappe.db.delete("Comment", {"reference_doctype": "COD Exception", "reference_name": ["in", excs]})
			frappe.db.delete("COD Exception", {"name": ["in", excs]})
		if remittances:
			frappe.db.delete("Sync Log", {"reference_name": ["in", remittances]})
			frappe.db.delete("Remittance Line", {"parent": ["in", remittances]})
			frappe.db.delete("Courier Remittance", {"name": ["in", remittances]})
		frappe.db.delete("Sync Log", {"reference_doctype": "Courier", "reference_name": name})
		if parcels:
			frappe.db.delete("COD Parcel", {"name": ["in", parcels]})
		if frappe.db.exists("Courier", name):
			frappe.delete_doc("Courier", name, force=True, ignore_permissions=True)

	def cleanup(self):
		frappe.set_user("Administrator")
		for email in self.users:
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		self.users = []
		for name in frappe.get_all("Courier", filters={"name": ["like", f"{self.prefix}-%"]}, pluck="name"):
			self.purge_courier(name)
		for k, v in self._saved_conn.items():
			frappe.db.set_single_value("Store Connection", k, v)
		self._saved_conn = {}
		frappe.clear_document_cache("Store Connection", "Store Connection")


def days_ago(n):
	return add_days(nowdate(), -n)
