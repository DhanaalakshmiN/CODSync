import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate


class CourierRemittance(Document):
	def validate(self):
		if not self.lines:
			frappe.throw(_("At least one line is required"))
		if getdate(self.remittance_date) > getdate(nowdate()):
			frappe.throw(_("Remittance Date cannot be in the future"))

		# duplicate AWBs inside one file are allowed through: matching keeps the
		# first line and flags the rest as Duplicate AWB exceptions
		self.total_cod = sum(flt(r.cod_amount) for r in self.lines)
		self.total_deductions = sum(flt(r.freight) + flt(r.cod_fee) + flt(r.gst) for r in self.lines)
		self.total_net_paid = sum(flt(r.net_paid) for r in self.lines)

	def on_submit(self):
		from codsync.codsync.matching import mark_missing, reconcile_remittance

		reconcile_remittance(self.name)
		mark_missing(self.courier)
