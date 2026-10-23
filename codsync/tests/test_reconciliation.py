"""Expected charges, payout tolerance, missing settlements, batch status and derived statuses."""

import frappe
from frappe.tests import IntegrationTestCase

from codsync.codsync.engine import (
	cod_status,
	delivery_status,
	expected_for,
	payout_decision,
	reconcile_remittance,
	reconciliation_status,
	run_reconciliation,
)
from codsync.codsync.matching import mark_missing
from codsync.tests.helpers import NET_1KG, NET_3KG, Fixture, days_ago


class TestExpectedFor(IntegrationTestCase):
	def setUp(self):
		self.fx = Fixture("RCE")
		self.fx.default_settings()
		self.fx.make_courier()
		self.fx.make_courier("RCE-NORATE", cod_fee_percent=0, gst_percent=0, base_freight=0, additional_freight_per_kg=0)

	def tearDown(self):
		self.fx.cleanup()

	def parcel(self, **kw):
		return frappe._dict({"courier": self.fx.courier, "cod_amount": 1000, "declared_weight": 1, "charged_weight": 0, **kw})

	def test_net_is_cod_minus_fee_freight_and_gst(self):
		exp = expected_for(self.parcel())
		self.assertEqual(exp["expected_cod_fee"], 20)
		self.assertEqual(exp["expected_freight"], 50)
		self.assertEqual(exp["expected_gst"], 12.6)
		self.assertEqual(exp["expected_settlement"], NET_1KG)

	def test_freight_adds_per_kg_above_base_weight(self):
		exp = expected_for(self.parcel(declared_weight=3))
		self.assertEqual(exp["expected_freight"], 70)  # 50 + 10 x (3 - 1)
		self.assertEqual(exp["expected_settlement"], NET_3KG)

	def test_weight_at_or_below_base_adds_nothing(self):
		self.assertEqual(expected_for(self.parcel(declared_weight=0.4))["expected_freight"], 50)

	def test_declared_weight_is_used_not_charged_weight(self):
		exp = expected_for(self.parcel(declared_weight=1, charged_weight=5))
		self.assertEqual(exp["expected_freight"], 50)
		self.assertEqual(exp["expected_settlement"], NET_1KG)

	def test_courier_without_rate_card_falls_back_to_line_charges(self):
		line = frappe._dict(cod_fee=15, freight=40, gst=9.9)
		parcel = frappe._dict(courier="RCE-NORATE", cod_amount=1000, declared_weight=1)
		self.assertEqual(expected_for(parcel, line)["expected_settlement"], 935.1)


class TestPayoutDecision(IntegrationTestCase):
	def setUp(self):
		self.fx = Fixture("RCP")
		self.fx.default_settings()

	def tearDown(self):
		self.fx.cleanup()

	def test_short_by_half_a_rupee_is_paid(self):
		self.assertEqual(payout_decision(frappe._dict(order_currency="INR"), NET_1KG, NET_1KG - 0.5), (-0.5, True, "Paid"))

	def test_tolerance_boundary_is_inclusive(self):
		parcel = frappe._dict(order_currency="INR")
		self.assertEqual(payout_decision(parcel, 1000, 999)[2], "Paid")
		self.assertEqual(payout_decision(parcel, 1000, 998.99)[2], "Short-paid")

	def test_short_by_sixty_is_short_paid(self):
		difference, within, status = payout_decision(frappe._dict(order_currency="INR"), NET_1KG, NET_1KG - 60)
		self.assertEqual((difference, within, status), (-60, False, "Short-paid"))

	def test_overpaid_is_paid_and_difference_is_kept(self):
		difference, _within, status = payout_decision(frappe._dict(order_currency="INR"), NET_1KG, NET_1KG + 22.6)
		self.assertEqual((difference, status), (22.6, "Paid"))

	def test_custom_tolerance_is_read_from_settings(self):
		self.fx.set_settings(tolerance=5)
		parcel = frappe._dict(order_currency="INR")
		self.assertEqual(payout_decision(parcel, 1000, 995)[2], "Paid")
		self.assertEqual(payout_decision(parcel, 1000, 994.99)[2], "Short-paid")

	def test_foreign_order_uses_percentage_tolerance(self):
		# expected 917.40 -> max(1.00, 0.5 % = 4.587) = 4.587
		foreign, home = frappe._dict(order_currency="USD"), frappe._dict(order_currency="INR")
		self.assertEqual(payout_decision(foreign, NET_1KG, NET_1KG - 4)[2], "Paid")
		self.assertEqual(payout_decision(foreign, NET_1KG, NET_1KG - 5)[2], "Short-paid")
		self.assertEqual(payout_decision(home, NET_1KG, NET_1KG - 4)[2], "Short-paid")  # same gap, base currency

	def test_foreign_small_order_uses_absolute_tolerance(self):
		foreign = frappe._dict(order_currency="USD")
		self.assertEqual(payout_decision(foreign, 100, 99)[2], "Paid")
		self.assertEqual(payout_decision(foreign, 100, 98.5)[2], "Short-paid")


class TestReconcileLine(IntegrationTestCase):
	"""End to end through reconcile_remittance, so the exceptions are real."""

	def setUp(self):
		self.fx = Fixture("RCL")
		self.fx.default_settings()
		self.fx.make_courier()

	def tearDown(self):
		self.fx.cleanup()

	def settle(self, key, rid, net, **line):
		parcel = self.fx.make_parcel(key, **line.pop("parcel", {}))
		rem = self.fx.make_remittance(rid, [{"awb": parcel.awb, "cod_amount": 1000, "net_paid": net, **line}])
		res = reconcile_remittance(rem.name)
		parcel.reload()
		return parcel, rem, res

	def test_half_rupee_short_is_paid_with_no_exception(self):
		parcel, _, res = self.settle("L1", "R1", NET_1KG - 0.5)
		self.assertEqual((parcel.payout_status, parcel.difference), ("Paid", -0.5))
		self.assertEqual(res["batch_status"], "Reconciled")
		self.assertEqual(self.fx.exceptions(), [])

	def test_sixty_short_with_weight_charge_raises_unexpected_deduction(self):
		parcel, _, res = self.settle("L2", "R2", NET_1KG - 60, weight_charge=60)
		self.assertEqual((parcel.payout_status, parcel.difference), ("Short-paid", -60))
		self.assertEqual(res["counts"]["short-paid"], 1)
		self.assertEqual([e.exception_type for e in self.fx.exceptions()], ["Unexpected deduction"])

	def test_sixty_short_without_a_reason_raises_amount_mismatch(self):
		parcel, _, _ = self.settle("L3", "R3", NET_1KG - 60)
		self.assertEqual(parcel.payout_status, "Short-paid")
		self.assertEqual([e.exception_type for e in self.fx.exceptions()], ["Amount mismatch"])

	def test_overpaid_is_paid_but_flagged_for_review(self):
		# tolerance only decides Paid / Short-paid; an overpayment outside it still
		# opens an Amount mismatch so someone looks at it, and the batch is a Mismatch
		parcel, _, res = self.settle("L4", "R4", NET_1KG + 22.6)
		self.assertEqual((parcel.payout_status, parcel.difference), ("Paid", 22.6))
		self.assertEqual([e.exception_type for e in self.fx.exceptions()], ["Amount mismatch"])
		self.assertEqual(res["batch_status"], "Mismatch")

	def test_foreign_order_within_percentage_tolerance_is_paid(self):
		parcel, _, _ = self.settle("L5", "R5", NET_1KG - 4, parcel={"order_currency": "USD"})
		self.assertEqual((parcel.payout_status, parcel.difference), ("Paid", -4))
		self.assertEqual(self.fx.exceptions(), [])

	def test_same_gap_on_base_currency_order_is_short_paid(self):
		parcel, _, _ = self.settle("L6", "R6", NET_1KG - 4)
		self.assertEqual((parcel.payout_status, parcel.difference), ("Short-paid", -4))
		self.assertEqual(len(self.fx.exceptions()), 1)

	def test_batch_is_reconciled_only_when_every_line_is_paid(self):
		good, bad = self.fx.make_parcel("L7"), self.fx.make_parcel("L8")
		ok = self.fx.make_remittance("R7", [{"awb": good.awb, "cod_amount": 1000, "net_paid": NET_1KG}])
		self.assertEqual(reconcile_remittance(ok.name)["batch_status"], "Reconciled")
		mixed = self.fx.make_remittance("R8", [{"awb": bad.awb, "cod_amount": 1000, "net_paid": NET_1KG - 60}])
		self.assertEqual(reconcile_remittance(mixed.name)["batch_status"], "Mismatch")
		self.assertEqual(frappe.db.get_value("Courier Remittance", mixed.name, "batch_status"), "Mismatch")


class TestMissingSettlement(IntegrationTestCase):
	def setUp(self):
		self.fx = Fixture("RCM")
		self.fx.default_settings()
		self.fx.make_courier()  # payout cycle 7 days

	def tearDown(self):
		self.fx.cleanup()

	def payout(self, parcel):
		return frappe.db.get_value("COD Parcel", parcel.name, "payout_status")

	def test_statuses_by_age_and_payment_mode(self):
		late = self.fx.make_parcel("M1", delivered_date=days_ago(10))
		fresh = self.fx.make_parcel("M2", delivered_date=days_ago(2))
		prepaid = self.fx.make_parcel("M3", payment_mode="Prepaid", delivered_date=days_ago(10))
		transit = self.fx.make_parcel("M4", status="In Transit", delivered_date=None)
		mark_missing(self.fx.courier)
		self.assertEqual(self.payout(late), "Missing")
		self.assertEqual(self.payout(fresh), "Awaiting payout")
		self.assertNotIn(self.payout(prepaid), ("Missing", "Awaiting payout"))
		self.assertEqual(self.payout(transit), "Not due")

	def test_only_overdue_delivered_parcels_raise_an_exception(self):
		late = self.fx.make_parcel("M5", delivered_date=days_ago(10))
		fresh = self.fx.make_parcel("M6", delivered_date=days_ago(2))
		prepaid = self.fx.make_parcel("M7", payment_mode="Prepaid", delivered_date=days_ago(10))
		run_reconciliation(self.fx.courier)
		excs = self.fx.exceptions(exception_type="Missing settlement")
		self.assertEqual([e.cod_parcel for e in excs], [late.name])
		self.assertEqual(self.fx.exceptions(cod_parcel=fresh.name), [])
		self.assertEqual(self.fx.exceptions(cod_parcel=prepaid.name), [])

	def test_running_detector_twice_does_not_duplicate(self):
		self.fx.make_parcel("M8", delivered_date=days_ago(10))
		run_reconciliation(self.fx.courier)
		run_reconciliation(self.fx.courier)
		self.assertEqual(len(self.fx.exceptions(exception_type="Missing settlement")), 1)

	def test_exception_resolves_when_the_settlement_arrives(self):
		late = self.fx.make_parcel("M9", delivered_date=days_ago(10))
		run_reconciliation(self.fx.courier)
		rem = self.fx.make_remittance("R9", [{"awb": late.awb, "cod_amount": 1000, "net_paid": NET_1KG}])
		reconcile_remittance(rem.name)
		self.assertEqual(self.fx.exceptions(exception_type="Missing settlement", status="Open"), [])


class TestDerivedStatuses(IntegrationTestCase):
	def test_delivery_status(self):
		self.assertEqual(delivery_status({"status": "Delivered", "awb": "X"}), "Delivered")
		self.assertEqual(delivery_status({"status": "In Transit", "awb": "X"}), "In transit")
		self.assertEqual(delivery_status({"status": "In Transit", "awb": "X", "last_event": "Out for Delivery"}), "Out for delivery")
		self.assertEqual(delivery_status({"order_status": "Fulfilled"}), "Fulfilled")
		self.assertEqual(delivery_status({"order_status": "Unfulfilled"}), "Unfulfilled")
		self.assertEqual(delivery_status({"status": "Cancelled"}), "Cancelled")
		self.assertEqual(delivery_status({"status": "RTO", "awb": "X", "last_event": "RTO initiated"}), "RTO initiated")
		self.assertEqual(delivery_status({"status": "RTO", "awb": "X", "last_event": "RTO delivered"}), "RTO delivered")

	def test_cod_status(self):
		self.assertEqual(cod_status({"payment_mode": "Prepaid"}), "Not applicable")
		self.assertEqual(cod_status({"payment_mode": "COD"}), "Awaiting shipment")
		self.assertEqual(cod_status({"awb": "X", "status": "In Transit"}), "Not collected")
		self.assertEqual(cod_status({"awb": "X", "status": "Delivered"}), "Collected")
		self.assertEqual(cod_status({"awb": "X", "status": "Delivered", "payout_status": "Paid"}), "Settled")
		self.assertEqual(cod_status({"awb": "X", "status": "Delivered", "payout_status": "Short-paid"}), "Settled")
		self.assertEqual(cod_status({"awb": "X", "payout_status": "Unknown"}), "Unknown")

	def test_reconciliation_status(self):
		self.assertIsNone(reconciliation_status({"payment_mode": "Prepaid"}))
		self.assertEqual(reconciliation_status({"payment_mode": "COD"}), "Pending")
		self.assertEqual(reconciliation_status({"payout_status": "Paid"}), "Reconciled")
		self.assertEqual(reconciliation_status({"payout_status": "Short-paid"}), "Mismatch")
		self.assertEqual(reconciliation_status({"payout_status": "Paid"}, ["Amount mismatch"]), "Mismatch")
		self.assertEqual(reconciliation_status({"payout_status": "Paid"}, ["Missing settlement"]), "Exception")
		self.assertEqual(reconciliation_status({"payout_status": "Short-paid"}, ["Unknown AWB", "Amount mismatch"]), "Exception")
