import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class CurrencyRate(Document):
	def validate(self):
		self.from_currency = (self.from_currency or "").upper()
		self.to_currency = (self.to_currency or "").upper()
		if self.from_currency == self.to_currency:
			frappe.throw(_("From and To currency must differ"))
		if flt(self.rate) <= 0:
			frappe.throw(_("Rate must be greater than zero"))
		if self.is_new() and frappe.db.exists("Currency Rate", self._expected_name()):
			frappe.throw(
				_(
					"A rate for {0} to {1} on {2} already exists. Edit it and set Source to Manual instead."
				).format(self.from_currency, self.to_currency, self.rate_date)
			)

	def _expected_name(self):
		return f"{self.from_currency}-{self.to_currency}-{self.rate_date}"

	def on_update(self):
		self.clear_rate_cache()

	def on_trash(self):
		self.clear_rate_cache()

	def clear_rate_cache(self):
		from codsync.codsync.currency import cache_key

		frappe.cache.delete_value(cache_key(self.from_currency, self.to_currency, self.rate_date))
