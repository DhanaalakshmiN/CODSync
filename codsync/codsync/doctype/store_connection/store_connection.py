import frappe
from frappe.model.document import Document

from codsync.codsync.platforms import get_platform


class StoreConnection(Document):
	@frappe.whitelist()
	def test_connection(self):
		frappe.only_for(("System Manager", "CODSync Manager"))
		try:
			ok, message = get_platform(self.platform).test_connection(self)
		except NotImplementedError as e:
			ok, message = False, str(e)
		return {"ok": ok, "message": message, "platform": self.platform}

	@frappe.whitelist()
	def fetch_orders(self):
		frappe.only_for(("System Manager", "CODSync Manager"))
		try:
			return get_platform(self.platform).fetch_orders(self)
		except NotImplementedError as e:
			frappe.throw(str(e))

	@frappe.whitelist()
	def recalculate_currency_amounts(self):
		frappe.only_for(("System Manager", "CODSync Manager"))
		from codsync.codsync.engine import recalculate_currency_amounts

		return recalculate_currency_amounts()

	def validate(self):
		from codsync.codsync.currency import default_base_currency

		self.base_currency = (self.base_currency or default_base_currency()).upper()
