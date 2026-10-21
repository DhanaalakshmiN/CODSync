import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, today


class CODException(Document):
	def validate(self):
		if self.is_new() and not self.opened_on:
			self.opened_on = now_datetime()
		if self.status == "Resolved" and not self.resolved_on:
			self.resolved_on = now_datetime()
		if self.resolution == "Raise dispute" and (self.dispute_status or "Not raised") == "Not raised":
			self.claim_amount = abs(flt(self.impact))
			self.dispute_status = "Raised with Courier"
			self.dispute_raised_on = today()
