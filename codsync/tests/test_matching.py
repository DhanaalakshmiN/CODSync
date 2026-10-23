"""AWB normalisation, row validation and the outcomes of reconcile_remittance."""

import frappe
from frappe.tests import IntegrationTestCase

from codsync.codsync.engine import _line_errors, normalize_awb, reconcile_remittance
from codsync.tests.helpers import NET_1KG, Fixture


class TestNormalizeAwb(IntegrationTestCase):
	def test_trims_uppercases_and_strips_noise(self):
		self.assertEqual(normalize_awb("  ab-12 3  "), "AB123")
		self.assertEqual(normalize_awb('"dl 77-x\''), "DL77X")

	def test_excel_numeric_forms_become_digits(self):
		self.assertEqual(normalize_awb("1.23E+11"), "123000000000")
		self.assertEqual(normalize_awb("1.23e+11"), "123000000000")
		self.assertEqual(normalize_awb("12345.0"), "12345")
		self.assertEqual(normalize_awb(12345.0), "12345")

	def test_clean_value_is_unchanged(self):
		self.assertEqual(normalize_awb("DLV1234567"), "DLV1234567")
		self.assertEqual(normalize_awb("1.5"), "1.5")  # not a whole number: left alone

	def test_empty_and_none(self):
		self.assertEqual(normalize_awb(None), "")
		self.assertEqual(normalize_awb(""), "")
		self.assertEqual(normalize_awb("  - "), "")


class TestLineErrors(IntegrationTestCase):
	def line(self, **kw):
		return frappe._dict({"awb": "AWB1", "net_paid": 100, **kw})

	def test_valid_row_has_no_errors(self):
		self.assertEqual(_line_errors(self.line(cod_amount="1,000.50", freight=50)), [])

	def test_missing_awb(self):
		self.assertEqual(_line_errors(self.line(awb="  ")), ["AWB is missing"])
		self.assertEqual(_line_errors(self.line(awb=None)), ["AWB is missing"])

	def test_non_numeric_amount(self):
		errors = _line_errors(self.line(cod_amount="abc"))
		self.assertEqual(len(errors), 1)
		self.assertIn("cod_amount is not numeric", errors[0])

	def test_negative_net_paid(self):
		errors = _line_errors(self.line(net_paid=-5))
		self.assertEqual(len(errors), 1)
		self.assertIn("net_paid is negative", errors[0])


class TestReconcileRemittance(IntegrationTestCase):
	def setUp(self):
		self.fx = Fixture("MTX")
		self.fx.default_settings()
		self.fx.make_courier()
		self.fx.make_courier("MTX-OTHER")

	def tearDown(self):
		self.fx.cleanup()

	def run_batch(self, rid, lines, **kw):
		rem = self.fx.make_remittance(rid, lines, **kw)
		return rem, reconcile_remittance(rem.name)

	def test_matched(self):
		p = self.fx.make_parcel("A1")
		rem, res = self.run_batch("R1", [{"awb": p.awb, "cod_amount": 1000, "net_paid": NET_1KG}])
		self.assertEqual(res["counts"], {"matched": 1, "short-paid": 0, "unknown": 0, "exceptions": 0})
		self.assertEqual(res["batch_status"], "Reconciled")
		p.reload()
		self.assertEqual((p.payout_status, p.settlement_batch, p.difference), ("Paid", rem.name, 0))
		self.assertEqual(frappe.db.get_value("Remittance Line", {"parent": rem.name}, "cod_parcel"), p.name)

	def test_matching_ignores_awb_formatting(self):
		p = self.fx.make_parcel("A2")
		messy = f" {p.awb[:4].lower()}-{p.awb[4:]} "
		_, res = self.run_batch("R2", [{"awb": messy, "cod_amount": 1000, "net_paid": NET_1KG}])
		self.assertEqual(res["counts"]["matched"], 1)

	def test_unknown_awb_creates_exception(self):
		_, res = self.run_batch("R3", [{"awb": "MTXNOSUCH1", "net_paid": 500}])
		self.assertEqual(res["counts"]["unknown"], 1)
		self.assertEqual(res["batch_status"], "Pending review")
		excs = self.fx.exceptions(exception_type="Unknown AWB", awb="MTXNOSUCH1")
		self.assertEqual([e.status for e in excs], ["Open"])

	def test_same_awb_twice_in_one_batch_is_flagged_duplicate(self):
		p = self.fx.make_parcel("A3")
		rem, res = self.run_batch(
			"R4",
			[
				{"awb": p.awb, "cod_amount": 1000, "net_paid": NET_1KG},
				{"awb": p.awb, "cod_amount": 1000, "net_paid": NET_1KG},
			],
		)
		self.assertEqual((res["counts"]["matched"], res["counts"]["unknown"]), (1, 1))
		dup = self.fx.exceptions(exception_type="Duplicate AWB")
		self.assertEqual(len(dup), 1)
		self.assertEqual(dup[0].awb, p.awb)
		statuses = frappe.get_all("Remittance Line", filters={"parent": rem.name}, pluck="match_status", order_by="idx")
		self.assertEqual(statuses, ["Paid", "Unknown"])

	def test_prepaid_parcel_is_not_matched(self):
		p = self.fx.make_parcel("A4", payment_mode="Prepaid")
		_, res = self.run_batch("R5", [{"awb": p.awb, "net_paid": 100}])
		self.assertEqual((res["counts"]["matched"], res["counts"]["unknown"]), (0, 1))
		p.reload()
		self.assertFalse(p.settlement_batch)
		self.assertEqual(len(self.fx.exceptions(cod_parcel=p.name)), 1)

	def test_parcel_already_settled_in_another_batch_is_not_rematched(self):
		p = self.fx.make_parcel("A5")
		first, _ = self.run_batch("R6", [{"awb": p.awb, "cod_amount": 1000, "net_paid": NET_1KG}])
		_, res = self.run_batch("R7", [{"awb": p.awb, "cod_amount": 1000, "net_paid": NET_1KG}])
		self.assertEqual((res["counts"]["matched"], res["counts"]["unknown"]), (0, 1))
		p.reload()
		self.assertEqual(p.settlement_batch, first.name)  # untouched

	def test_courier_mismatch_raises_tracking_mismatch_but_still_matches(self):
		p = self.fx.make_parcel("A6", courier="MTX-OTHER")
		_, res = self.run_batch("R8", [{"awb": p.awb, "cod_amount": 1000, "net_paid": NET_1KG}])
		self.assertEqual(res["counts"]["matched"], 1)
		self.assertEqual(res["counts"]["exceptions"], 1)
		self.assertEqual(len(self.fx.exceptions(exception_type="Tracking mismatch", cod_parcel=p.name)), 1)

	def test_rerunning_matching_creates_no_duplicate_exceptions(self):
		short = self.fx.make_parcel("A7")
		rem, _ = self.run_batch(
			"R9",
			[
				{"awb": short.awb, "cod_amount": 1000, "weight_charge": 60, "net_paid": NET_1KG - 60},
				{"awb": "MTXGHOST9", "net_paid": 300},
			],
		)
		first = len(self.fx.exceptions())
		self.assertEqual(first, 2)
		for _i in range(2):
			reconcile_remittance(rem.name)
		self.assertEqual(len(self.fx.exceptions()), first)
		self.assertEqual(len(self.fx.exceptions(status="Open")), first)

	def test_unknown_awb_exception_resolves_when_parcel_appears_later(self):
		awb = "MTXLATE001"
		self.run_batch("R10", [{"awb": awb, "net_paid": NET_1KG}])
		self.assertEqual(len(self.fx.exceptions(exception_type="Unknown AWB", status="Open")), 1)
		self.fx.make_parcel("LATE001", awb=awb)
		_, res = self.run_batch("R11", [{"awb": awb, "cod_amount": 1000, "net_paid": NET_1KG}])
		self.assertEqual(res["counts"]["matched"], 1)
		self.assertEqual(len(self.fx.exceptions(exception_type="Unknown AWB", status="Open")), 0)
		self.assertEqual(len(self.fx.exceptions(exception_type="Unknown AWB", status="Resolved")), 1)

	def test_bad_rows_are_skipped_with_a_reason(self):
		# a Currency column cannot hold text, so the reachable bad rows are: AWB that
		# normalises to nothing, and a negative payout
		p = self.fx.make_parcel("A8")
		neg = self.fx.make_parcel("A9")
		_, res = self.run_batch(
			"R12",
			[
				{"awb": " - ", "net_paid": 10},
				{"awb": neg.awb, "cod_amount": 1000, "net_paid": -5},
				{"awb": p.awb, "cod_amount": 1000, "net_paid": NET_1KG},
			],
		)
		self.assertEqual([s["errors"][0].split(" (")[0] for s in res["skipped"]], ["AWB is missing", "net_paid is negative"])
		self.assertEqual((res["counts"]["matched"], res["counts"]["unknown"]), (1, 2))
		neg.reload()
		self.assertFalse(neg.settlement_batch)  # a skipped row never touches the parcel
