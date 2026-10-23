"""Dispute claims, stages, reminders and refund matching. Mail is mocked."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from codsync.codsync import disputes

SENDMAIL = "codsync.codsync.disputes.frappe.sendmail"
OUTGOING = "codsync.codsync.disputes._require_outgoing_email"


class TestDisputes(IntegrationTestCase):
	def setUp(self):
		self.courier = self.make_courier("DSP-COURIER", "claims@example.com")
		self.nomail = self.make_courier("DSP-NOMAIL", None)

	def make_courier(self, name, email):
		if frappe.db.exists("Courier", name):
			frappe.delete_doc("Courier", name, force=True)
		return frappe.get_doc(
			{"doctype": "Courier", "courier_name": name, "is_active": 1, "claims_email": email}
		).insert(ignore_permissions=True).name

	def make_parcel(self, order_id, courier, expected=1000, actual=900):
		return frappe.get_doc(
			{
				"doctype": "COD Parcel",
				"order_id": order_id,
				"courier": courier,
				"awb": f"AWB{order_id}",
				"payment_mode": "COD",
				"cod_amount": expected,
				"status": "Delivered",
				"delivered_date": nowdate(),
				"expected_settlement": expected,
				"actual_settlement": actual,
				"difference": actual - expected,
				"payout_status": "Short-paid",
			}
		).insert(ignore_permissions=True)

	def make_exc(self, parcel, courier, impact=-100):
		return frappe.get_doc(
			{
				"doctype": "COD Exception",
				"exception_type": "Unexpected deduction",
				"cod_parcel": parcel.name,
				"awb": parcel.awb,
				"courier": courier,
				"expected": parcel.expected_settlement,
				"actual": parcel.actual_settlement,
				"impact": impact,
				"status": "Open",
			}
		).insert(ignore_permissions=True)

	def test_send_claim_groups_by_courier_and_sets_stage(self):
		e1 = self.make_exc(self.make_parcel("DSP-1", self.courier), self.courier)
		e2 = self.make_exc(self.make_parcel("DSP-2", self.courier), self.courier)
		with patch(SENDMAIL) as mail, patch(OUTGOING):
			res = disputes.send_claim([e1.name, e2.name])
		self.assertEqual(mail.call_count, 1)  # one consolidated email
		self.assertEqual(res["sent"][0]["count"], 2)
		self.assertEqual(mail.call_args.kwargs["recipients"], ["claims@example.com"])
		e1.reload()
		self.assertEqual(e1.dispute_status, "Sent to courier")
		self.assertEqual(str(e1.next_follow_up), add_days(nowdate(), 7))
		self.assertEqual(e1.claim_amount, 100)
		self.assertEqual(e1.stage_log[-1].stage, "Sent to courier")

	def test_send_claim_refuses_courier_without_email(self):
		e = self.make_exc(self.make_parcel("DSP-3", self.nomail), self.nomail)
		with patch(SENDMAIL) as mail, patch(OUTGOING):
			with self.assertRaises(frappe.ValidationError):
				disputes.send_claim([e.name])
		mail.assert_not_called()

	def test_preview_sends_nothing(self):
		e = self.make_exc(self.make_parcel("DSP-4", self.courier), self.courier)
		with patch(SENDMAIL) as mail:
			out = disputes.preview_claim([e.name])
		mail.assert_not_called()
		self.assertEqual(out[0]["to"], "claims@example.com")

	def test_reminder_only_when_overdue(self):
		e = self.make_exc(self.make_parcel("DSP-5", self.courier), self.courier)
		with patch(SENDMAIL), patch(OUTGOING):
			disputes.send_claim([e.name])
		with patch(SENDMAIL) as mail, patch(OUTGOING):
			self.assertEqual(disputes.send_follow_ups(), {"reminded": 0})
			mail.assert_not_called()
			frappe.db.set_value("COD Exception", e.name, "next_follow_up", add_days(nowdate(), -1))
			self.assertEqual(disputes.send_follow_ups(), {"reminded": 1})
			mail.assert_called_once()
		e.reload()
		self.assertEqual(str(e.next_follow_up), add_days(nowdate(), 7))
		self.assertEqual(str(e.last_reminder_on), nowdate())

	def refund_line(self, net_paid):
		return frappe._dict(name=None, net_paid=net_paid, parent="REM-TEST")

	def test_full_refund_closes_dispute(self):
		parcel = self.make_parcel("DSP-6", self.courier)
		exc = self.make_exc(parcel, self.courier)
		with patch(SENDMAIL), patch(OUTGOING):
			disputes.send_claim([exc.name])
		exc.reload()
		with patch("codsync.codsync.disputes.frappe.db.set_value"):
			res = disputes.apply_refund(exc, self.refund_line(100), parcel)
		self.assertTrue(res["refunded"])
		exc.reload()
		self.assertEqual((exc.dispute_status, exc.status, exc.recovered_amount), ("Refunded", "Resolved", 100))

	def test_partial_refund_stays_open(self):
		parcel = self.make_parcel("DSP-7", self.courier, expected=1000, actual=500)
		exc = self.make_exc(parcel, self.courier, impact=-500)
		with patch(SENDMAIL), patch(OUTGOING):
			disputes.send_claim([exc.name])
		exc.reload()
		with patch("codsync.codsync.disputes.frappe.db.set_value"):
			res = disputes.apply_refund(exc, self.refund_line(200), parcel)
		self.assertFalse(res["refunded"])
		exc.reload()
		self.assertEqual((exc.dispute_status, exc.status, exc.recovered_amount), ("Partly accepted", "Open", 200))


class TestRefundIdempotent(IntegrationTestCase):
	"""Running matching twice on the same refund batch must not pay the dispute twice."""

	def test_rematching_a_refund_batch_applies_it_once(self):
		courier = "DSP-RERUN"
		if frappe.db.exists("Courier", courier):
			frappe.delete_doc("Courier", courier, force=True)
		frappe.get_doc({"doctype": "Courier", "courier_name": courier, "is_active": 1}).insert(ignore_permissions=True)
		parcel = frappe.get_doc(
			{
				"doctype": "COD Parcel", "order_id": "DSP-R1", "courier": courier, "awb": "AWBDSPR1",
				"payment_mode": "COD", "cod_amount": 1000, "status": "Delivered", "delivered_date": nowdate(),
			}
		).insert(ignore_permissions=True)

		def remit(rid, net, cod):
			doc = frappe.get_doc(
				{
					"doctype": "Courier Remittance", "courier": courier, "remittance_id": rid,
					"remittance_date": nowdate(), "source": "Excel",
					"lines": [{"awb": "AWBDSPR1", "cod_amount": cod, "net_paid": net}],
				}
			).insert(ignore_permissions=True)
			doc.submit()
			return doc.name

		first = remit("DSP-REM-A", 900, 1000)
		exc = frappe.get_doc(
			"COD Exception", {"cod_parcel": parcel.name, "status": "Open", "exception_type": "Amount mismatch"}
		)
		exc.claim_amount = 100
		disputes.set_stage(exc, "Sent to courier", "test")
		exc.save(ignore_permissions=True)

		refund = remit("DSP-REM-B", 40, 0)  # submit already runs matching once
		from codsync.codsync import engine

		engine.reconcile_remittance(refund)  # and once more, as the Run Matching button would
		exc.reload()
		self.assertEqual(exc.recovered_amount, 40)
		self.assertEqual(exc.dispute_status, "Partly accepted")
		self.assertEqual(
			frappe.db.count("COD Exception", {"cod_parcel": parcel.name, "status": "Open"}), 1
		)


class TestRefundDetection(IntegrationTestCase):
	"""Refund detection end to end, through matching. Own courier + rate card; cleaned up after."""

	def setUp(self):
		from codsync.tests.helpers import Fixture

		self.fx = Fixture("RFD")
		self.fx.default_settings()
		self.fx.make_courier()

	def tearDown(self):
		self.fx.cleanup()

	def settle(self, parcel, rid, net, cod=1000):
		rem = self.fx.make_remittance(rid, [{"awb": parcel.awb, "cod_amount": cod, "net_paid": net}])
		from codsync.codsync import engine

		return engine.reconcile_remittance(rem.name)

	def claim(self, exc, amount):
		exc.claim_amount = amount
		disputes.set_stage(exc, "Sent to courier", "test")
		exc.save(ignore_permissions=True)

	def open_exception(self, parcel, exc_type):
		return frappe.get_doc("COD Exception", {"cod_parcel": parcel.name, "status": "Open", "exception_type": exc_type})

	def test_partial_refund_then_remainder_completes_the_dispute(self):
		from codsync.tests.helpers import NET_1KG

		parcel = self.fx.make_parcel("D1")
		self.settle(parcel, "A", NET_1KG - 100)
		exc = self.open_exception(parcel, "Amount mismatch")
		self.claim(exc, 100)

		self.settle(parcel, "B", 40)  # part of the claim comes back
		exc.reload()
		self.assertEqual((exc.dispute_status, exc.status, exc.recovered_amount), ("Partly accepted", "Open", 40))

		self.settle(parcel, "C", 60)  # the rest
		exc.reload()
		self.assertEqual((exc.dispute_status, exc.status, exc.recovered_amount), ("Refunded", "Resolved", 100))
		self.assertEqual(frappe.db.get_value("COD Parcel", parcel.name, "payout_status"), "Paid")

	def test_late_payout_for_missing_settlement_dispute_is_refunded(self):
		from codsync.codsync import engine
		from codsync.tests.helpers import NET_1KG, days_ago

		parcel = self.fx.make_parcel("D2", delivered_date=days_ago(10))
		engine.run_reconciliation(self.fx.courier)
		exc = self.open_exception(parcel, "Missing settlement")
		self.claim(exc, NET_1KG)

		res = self.settle(parcel, "A", NET_1KG)
		self.assertEqual(res["counts"]["matched"], 1)
		exc.reload()
		self.assertEqual((exc.dispute_status, exc.status), ("Refunded", "Resolved"))
		self.assertEqual(exc.recovered_amount, NET_1KG)

	def test_later_payment_without_an_open_dispute_is_not_a_refund(self):
		from codsync.tests.helpers import NET_1KG

		parcel = self.fx.make_parcel("D3")
		self.settle(parcel, "A", NET_1KG)  # paid exactly, nothing to dispute
		res = self.settle(parcel, "B", 50)
		self.assertEqual((res["counts"]["matched"], res["counts"]["unknown"]), (0, 1))
		parcel.reload()
		self.assertEqual((parcel.actual_settlement, parcel.payout_status), (NET_1KG, "Paid"))
		self.assertEqual(frappe.db.count("COD Exception", {"cod_parcel": parcel.name, "dispute_status": "Refunded"}), 0)
		self.assertEqual(len(self.fx.exceptions(exception_type="Unknown AWB")), 1)

	def test_closed_dispute_does_not_absorb_a_second_payment(self):
		from codsync.tests.helpers import NET_1KG

		parcel = self.fx.make_parcel("D4")
		self.settle(parcel, "A", NET_1KG - 100)
		exc = self.open_exception(parcel, "Amount mismatch")
		self.claim(exc, 100)
		self.settle(parcel, "B", 100)  # full refund closes it
		res = self.settle(parcel, "C", 100)  # an extra payment: no active dispute left
		self.assertEqual(res["counts"]["unknown"], 1)
		exc.reload()
		self.assertEqual(exc.recovered_amount, 100)
