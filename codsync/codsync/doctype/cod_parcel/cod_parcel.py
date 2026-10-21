import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class CODParcel(Document):
	def before_insert(self):
		# naming (field:awb) runs before validate, so normalise here too
		self.normalize_awb()

	def validate(self):
		self.normalize_awb()
		if (self.payment_mode or "COD") == "Prepaid":
			self.cod_amount = 0
		elif flt(self.cod_amount) <= 0:
			frappe.throw(_("COD Amount must be greater than 0"))
		if self.status == "Delivered" and not self.delivered_date:
			frappe.throw(_("Delivered Date is required when Status is Delivered"))

	def normalize_awb(self):
		# empty AWB is stored as None so the unique index allows many unfulfilled orders
		self.awb = "".join((self.awb or "").split()).upper() or None
