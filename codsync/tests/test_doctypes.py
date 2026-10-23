"""DocType rules: validation, uniqueness, computed fields, hooks and role permissions."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from codsync.tests.helpers import NET_1KG, Fixture


class DocTypeCase(IntegrationTestCase):
	prefix = "DTX"

	def setUp(self):
		self.fx = Fixture(self.prefix)
		self.fx.default_settings()
		self.fx.make_courier()

	def tearDown(self):
		self.fx.cleanup()


class TestCODParcel(DocTypeCase):
	prefix = "DTP"

	def test_order_id_is_unique(self):
		self.fx.make_parcel("1")
		with self.assertRaises(frappe.DuplicateEntryError):
			self.fx.make_parcel("1", awb="DTPOTHER1")

	def test_awb_is_unique(self):
		first = self.fx.make_parcel("2")
		with self.assertRaises((frappe.DuplicateEntryError, frappe.UniqueValidationError)):
			self.fx.make_parcel("3", awb=first.awb)

	def test_many_unfulfilled_orders_can_have_no_awb(self):
		a = self.fx.make_parcel("4", awb="", status="Booked", delivered_date=None)
		b = self.fx.make_parcel("5", awb="  ", status="Booked", delivered_date=None)
		self.assertIsNone(a.awb)
		self.assertIsNone(b.awb)

	def test_awb_is_upper_cased_and_spaces_removed(self):
		p = self.fx.make_parcel("6", awb=" dtp ab 12 ")
		self.assertEqual(p.awb, "DTPAB12")

	def test_prepaid_parcel_has_zero_cod(self):
		self.assertEqual(self.fx.make_parcel("7", payment_mode="Prepaid", cod=500).cod_amount, 0)

	def test_cod_amount_must_be_positive(self):
		for bad in (0, -10):
			with self.assertRaises(frappe.ValidationError):
				self.fx.make_parcel(f"8{abs(bad)}", cod=bad)

	def test_delivered_needs_a_delivered_date(self):
		with self.assertRaises(frappe.ValidationError):
			self.fx.make_parcel("9", status="Delivered", delivered_date=None)
		self.assertTrue(self.fx.make_parcel("10", status="In Transit", delivered_date=None).name)


class TestCourierRemittance(DocTypeCase):
	prefix = "DTR"

	def line(self, awb, **kw):
		return {"awb": awb, "cod_amount": 1000, "freight": 50, "cod_fee": 20, "gst": 12.6, "net_paid": NET_1KG, **kw}

	def test_needs_at_least_one_line(self):
		with self.assertRaises(frappe.ValidationError):
			self.fx.make_remittance("EMPTY", [])

	def test_future_date_is_rejected(self):
		doc = frappe.get_doc(
			{
				"doctype": "Courier Remittance", "courier": self.fx.courier, "remittance_id": "DTR-FUT",
				"remittance_date": add_days(nowdate(), 3), "lines": [self.line("DTRX1")],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_totals_are_computed_from_lines(self):
		rem = self.fx.make_remittance("TOT", [self.line("DTRX2"), self.line("DTRX3", net_paid=500)])
		self.assertEqual(rem.total_cod, 2000)
		self.assertEqual(rem.total_deductions, 2 * (50 + 20 + 12.6))
		self.assertEqual(rem.total_net_paid, NET_1KG + 500)

	def test_remittance_id_is_unique(self):
		self.fx.make_remittance("DUP", [self.line("DTRX4")])
		with self.assertRaises(frappe.DuplicateEntryError):
			self.fx.make_remittance("DUP", [self.line("DTRX4")])

	def test_same_awb_twice_in_a_file_is_allowed_through(self):
		self.assertEqual(len(self.fx.make_remittance("TWICE", [self.line("DTRX5"), self.line("DTRX5")]).lines), 2)

	def test_submit_runs_matching_and_marks_missing(self):
		paid = self.fx.make_parcel("1")
		late = self.fx.make_parcel("2", delivered_date=add_days(nowdate(), -10))
		rem = self.fx.make_remittance("SUB", [self.line(paid.awb)], submit=True)
		self.assertEqual(rem.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Courier Remittance", rem.name, "batch_status"), "Reconciled")
		self.assertEqual(frappe.db.get_value("COD Parcel", paid.name, "payout_status"), "Paid")
		self.assertEqual(frappe.db.get_value("COD Parcel", late.name, "payout_status"), "Missing")

	def test_draft_remittance_is_not_matched(self):
		p = self.fx.make_parcel("3")
		self.fx.make_remittance("DRAFT", [self.line(p.awb)])
		self.assertFalse(frappe.db.get_value("COD Parcel", p.name, "settlement_batch"))


class TestCurrencyRate(DocTypeCase):
	prefix = "DTC"

	def setUp(self):
		super().setUp()
		frappe.db.delete("Currency Rate", {"from_currency": "AUD", "to_currency": "INR"})

	def tearDown(self):
		frappe.db.delete("Currency Rate", {"from_currency": "AUD", "to_currency": "INR"})
		super().tearDown()

	def make(self, **kw):
		values = {"doctype": "Currency Rate", "from_currency": "aud", "to_currency": "inr", "rate_date": nowdate(), "rate": 55, "source": "Manual"}
		values.update(kw)
		return frappe.get_doc(values).insert(ignore_permissions=True)

	def test_codes_are_upper_cased_and_name_follows_the_pair_and_date(self):
		doc = self.make()
		self.assertEqual((doc.from_currency, doc.to_currency), ("AUD", "INR"))
		self.assertEqual(doc.name, f"AUD-INR-{nowdate()}")

	def test_same_currency_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.make(to_currency="AUD")

	def test_rate_must_be_positive(self):
		for bad in (0, -1):
			with self.assertRaises(frappe.ValidationError):
				self.make(rate=bad)

	def test_second_rate_for_same_pair_and_day_is_rejected(self):
		self.make()
		with self.assertRaises(frappe.ValidationError):
			self.make(rate=56)

	def test_cached_rate_is_cleared_on_update_and_delete(self):
		from codsync.codsync.currency import cache_key

		doc = self.make()
		key = cache_key("AUD", "INR", doc.rate_date)
		frappe.cache.set_value(key, 55)
		doc.rate = 57
		doc.save(ignore_permissions=True)
		self.assertIsNone(frappe.cache.get_value(key))
		frappe.cache.set_value(key, 57)
		frappe.delete_doc("Currency Rate", doc.name, ignore_permissions=True, force=True)
		self.assertIsNone(frappe.cache.get_value(key))


class TestCODException(DocTypeCase):
	prefix = "DTE"

	def make(self, **kw):
		return frappe.get_doc(
			{"doctype": "COD Exception", "exception_type": "Amount mismatch", "courier": self.fx.courier, "status": "Open", "impact": -80, **kw}
		).insert(ignore_permissions=True)

	def test_opened_on_is_stamped_on_creation(self):
		self.assertTrue(self.make().opened_on)

	def test_resolved_on_is_stamped_when_resolved(self):
		exc = self.make()
		self.assertFalse(exc.resolved_on)
		exc.status = "Resolved"
		exc.save(ignore_permissions=True)
		self.assertTrue(exc.resolved_on)

	def test_raise_dispute_resolution_sets_the_claim(self):
		exc = self.make()
		exc.resolution = "Raise dispute"
		exc.save(ignore_permissions=True)
		self.assertEqual((exc.claim_amount, exc.dispute_status, str(exc.dispute_raised_on)), (80, "Raised with Courier", nowdate()))

	def test_raise_dispute_does_not_restart_a_dispute_in_progress(self):
		exc = self.make(dispute_status="Sent to courier", claim_amount=50)
		exc.resolution = "Raise dispute"
		exc.save(ignore_permissions=True)
		self.assertEqual((exc.claim_amount, exc.dispute_status), (50, "Sent to courier"))

	def test_unknown_exception_type_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.make(exception_type="Made up")


class TestCourierAndStoreConnection(DocTypeCase):
	prefix = "DTS"

	def test_courier_name_is_unique(self):
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({"doctype": "Courier", "courier_name": self.fx.courier}).insert(ignore_permissions=True)

	def test_base_currency_is_upper_cased_on_save(self):
		self.fx.set_settings(base_currency="inr")
		doc = frappe.get_doc("Store Connection")
		doc.base_currency = "usd"
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.base_currency, "USD")

	def test_blank_base_currency_falls_back_to_default(self):
		doc = frappe.get_doc("Store Connection")
		doc.base_currency = ""
		doc.save(ignore_permissions=True)
		self.assertTrue(doc.base_currency)


class TestPermissions(IntegrationTestCase):
	"""Role rules as configured on each DocType (read from metadata, so no user session or Redis needed)."""

	def can(self, doctype, role, ptype):
		return any(
			p.role == role and p.permlevel == 0 and p.get(ptype)
			for p in frappe.get_meta(doctype).permissions
		)

	def roles_with(self, doctype, ptype):
		return {p.role for p in frappe.get_meta(doctype).permissions if p.permlevel == 0 and p.get(ptype)}

	def test_viewer_reads_but_cannot_write(self):
		for dt in ("COD Parcel", "COD Exception", "Courier", "Courier Remittance", "Currency Rate"):
			self.assertTrue(self.can(dt, "CODSync Viewer", "read"), dt)
			for ptype in ("write", "create", "delete"):
				self.assertFalse(self.can(dt, "CODSync Viewer", ptype), f"{dt} {ptype}")

	def test_operator_can_work_on_orders_and_exceptions(self):
		for dt in ("COD Parcel", "COD Exception"):
			self.assertTrue(self.can(dt, "CODSync Operator", "read"), dt)
			self.assertTrue(self.can(dt, "CODSync Operator", "write"), dt)

	def test_managers_can_edit_couriers_and_rates(self):
		for dt in ("Courier", "Currency Rate"):
			self.assertTrue(self.can(dt, "CODSync Manager", "write"), dt)

	def test_store_connection_is_for_managers_only(self):
		self.assertEqual(self.roles_with("Store Connection", "read"), {"CODSync Manager", "System Manager"})
		self.assertEqual(self.roles_with("Store Connection", "write"), {"CODSync Manager", "System Manager"})

	def test_sync_log_is_hidden_from_operators_but_not_viewers(self):
		self.assertTrue(self.can("Sync Log", "CODSync Viewer", "read"))
		self.assertFalse(self.can("Sync Log", "CODSync Operator", "read"))
		self.assertEqual(self.roles_with("Sync Log", "write") - {"System Manager"}, set())

	def test_every_codsync_role_exists(self):
		for role in ("CODSync Manager", "CODSync Operator", "CODSync Viewer"):
			self.assertTrue(frappe.db.exists("Role", role), role)
