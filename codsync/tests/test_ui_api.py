"""ui_api endpoints: role gates, courier settings and connection test, exception actions, lists.

Role gates are checked by patching frappe.only_for to the caller's roles, so the tests need
neither real users nor a running Redis (role lookups are cached there).
"""

from unittest.mock import patch

import frappe
import requests
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from codsync.codsync import disputes, ui_api
from codsync.tests.helpers import NET_1KG, Fixture


def as_role(*roles):
	"""Make frappe.only_for behave as if the caller holds exactly `roles`."""

	def only_for(allowed, message=False):
		allowed = (allowed,) if isinstance(allowed, str) else allowed
		if not set(roles) & set(allowed):
			raise frappe.PermissionError

	return patch("codsync.codsync.ui_api.frappe.only_for", side_effect=only_for)


class UiApiCase(IntegrationTestCase):
	prefix = "UIA"

	def setUp(self):
		self.fx = Fixture(self.prefix)
		self.fx.default_settings()
		self.fx.make_courier()

	def tearDown(self):
		self.fx.cleanup()

	def make_exc(self, key="1", exc_type="Unexpected deduction", **kw):
		parcel = self.fx.make_parcel(key, expected_settlement=NET_1KG, actual_settlement=NET_1KG - 60)
		exc = frappe.get_doc(
			{
				"doctype": "COD Exception", "exception_type": exc_type, "cod_parcel": parcel.name,
				"awb": parcel.awb, "courier": self.fx.courier, "expected": NET_1KG, "actual": NET_1KG - 60,
				"impact": -60, "status": "Open", **kw,
			}
		).insert(ignore_permissions=True)
		return parcel, exc


class TestRoleGates(UiApiCase):
	prefix = "UIG"

	READ = (
		lambda s: ui_api.overview(),
		lambda s: ui_api.orders(),
		lambda s: ui_api.exceptions(),
		lambda s: ui_api.settlements(),
		lambda s: ui_api.settings(),
		lambda s: ui_api.sync_log(),
		lambda s: ui_api.reports_list(),
	)

	def test_callers_without_a_codsync_role_are_refused_everywhere(self):
		with as_role("Guest"):
			for call in self.READ:
				with self.assertRaises(frappe.PermissionError):
					call(self)
			for call in (
				lambda: ui_api.resolve_exception("x", "assign"),
				lambda: ui_api.save_courier(self.fx.courier, {}),
				lambda: ui_api.test_courier(self.fx.courier),
				lambda: ui_api.save_settings({}),
			):
				with self.assertRaises(frappe.PermissionError):
					call()

	def test_viewer_can_read_but_not_act(self):
		with as_role("CODSync Viewer"):
			for call in self.READ:
				call(self)
			for call in (
				lambda: ui_api.resolve_exception("x", "assign"),
				lambda: ui_api.send_claim(["x"]),
				lambda: ui_api.save_courier(self.fx.courier, {}),
				lambda: ui_api.save_settings({}),
			):
				with self.assertRaises(frappe.PermissionError):
					call()

	def test_operator_can_act_on_exceptions_but_not_change_settings(self):
		_p, exc = self.make_exc()
		with as_role("CODSync Operator"):
			self.assertEqual(ui_api.resolve_exception(exc.name, "assign", {"assignee": ""})["status"], "Open")
			for call in (
				lambda: ui_api.save_courier(self.fx.courier, {}),
				lambda: ui_api.test_courier(self.fx.courier),
				lambda: ui_api.save_settings({}),
				lambda: ui_api.test_connection(),
			):
				with self.assertRaises(frappe.PermissionError):
					call()

	def test_manager_can_change_courier_settings(self):
		with as_role("CODSync Manager"):
			self.assertEqual(ui_api.save_courier(self.fx.courier, {"payout_cycle_days": 9})["name"], self.fx.courier)


class TestCouriers(UiApiCase):
	prefix = "UIC"

	def card(self, name=None):
		return next(c for c in ui_api.couriers() if c["name"] == (name or self.fx.courier))

	def test_lists_couriers_and_filters_inactive(self):
		self.assertEqual(self.card()["api_key_saved"], False)
		frappe.db.set_value("Courier", self.fx.courier, "is_active", 0)
		self.assertNotIn(self.fx.courier, [c["name"] for c in ui_api.couriers(active_only=1)])
		self.assertIn(self.fx.courier, [c["name"] for c in ui_api.couriers()])

	def test_create_courier(self):
		name = f"{self.fx.courier}-NEW"
		card = ui_api.save_courier(None, {"courier_name": name, "cod_fee_percent": 2})
		self.assertEqual((card["name"], card["status"]), (name, "Not connected"))
		with self.assertRaises(frappe.ValidationError):
			ui_api.save_courier(None, {"courier_name": name})  # already exists
		with self.assertRaises(frappe.ValidationError):
			ui_api.save_courier(None, {"courier_name": "  "})  # name required

	def test_validation_of_rates_and_options(self):
		for bad in (
			{"cod_fee_percent": -1},
			{"payout_cycle_days": 0},
			{"tracking_provider": "Nonsense"},
			{"settlement_via": "Carrier pigeon"},
		):
			with self.assertRaises(frappe.ValidationError, msg=str(bad)):
				ui_api.save_courier(self.fx.courier, bad)

	def test_update_rate_card(self):
		ui_api.save_courier(self.fx.courier, {"base_freight": 65, "gst_percent": 12})
		self.assertEqual(frappe.db.get_value("Courier", self.fx.courier, ["base_freight", "gst_percent"]), (65, 12))

	def test_api_key_is_write_only_and_blank_keeps_the_saved_one(self):
		ui_api.save_courier(self.fx.courier, {}, api_key="secret-key")
		card = self.card()
		self.assertTrue(card["api_key_saved"])
		self.assertNotIn("secret-key", str(card))
		ui_api.save_courier(self.fx.courier, {}, api_key="  ")
		self.assertEqual(frappe.get_doc("Courier", self.fx.courier).get_password("api_key"), "secret-key")

	def test_new_key_resets_connection_status(self):
		frappe.db.set_value("Courier", self.fx.courier, "connection_status", "Connected")
		ui_api.save_courier(self.fx.courier, {}, api_key="another")
		self.assertEqual(self.card()["status"], "Not connected")


class TestTestCourier(UiApiCase):
	"""test_courier is what the Reconnect button calls."""

	prefix = "UIT"

	def status(self):
		return frappe.db.get_value("Courier", self.fx.courier, ["connection_status", "last_error"], as_dict=True)

	def use_ship24(self, key=None):
		frappe.db.set_value("Courier", self.fx.courier, "tracking_provider", "Ship24")
		if key:
			ui_api.save_courier(self.fx.courier, {}, api_key=key)

	def test_mock_provider_always_connects(self):
		res = ui_api.test_courier(self.fx.courier)
		self.assertEqual((res["ok"], res["status"], res["message"]), (True, "Connected", "Connection OK"))

	def test_ship24_without_a_key_needs_action(self):
		self.use_ship24()
		res = ui_api.test_courier(self.fx.courier)
		self.assertEqual((res["ok"], res["message"], res["status"]), (False, "No API key saved", "Action needed"))
		self.assertEqual(self.status(), {"connection_status": "Action needed", "last_error": "No API key saved"})

	def test_ship24_rejected_key_and_server_error(self):
		self.use_ship24("bad")
		for code, text in ((401, "rejected the API key"), (403, "rejected the API key"), (500, "HTTP 500")):
			with patch("requests.get", return_value=type("R", (), {"status_code": code, "ok": False})()):
				res = ui_api.test_courier(self.fx.courier)
			self.assertFalse(res["ok"])
			self.assertIn(text, res["message"])

	def test_ship24_unreachable_provider(self):
		self.use_ship24("key")
		with patch("requests.get", side_effect=requests.ConnectionError("down")):
			res = ui_api.test_courier(self.fx.courier)
		self.assertEqual((res["ok"], res["message"]), (False, "Could not reach the provider"))

	def test_reconnecting_with_a_good_key_clears_the_error(self):
		self.use_ship24()
		ui_api.test_courier(self.fx.courier)  # fails: no key
		ui_api.save_courier(self.fx.courier, {}, api_key="good")
		with patch("requests.get", return_value=type("R", (), {"status_code": 200, "ok": True})()):
			res = ui_api.test_courier(self.fx.courier)
		self.assertEqual((res["ok"], res["status"]), (True, "Connected"))
		self.assertEqual(self.status(), {"connection_status": "Connected", "last_error": None})

	def test_each_test_writes_a_sync_log(self):
		self.use_ship24()
		ui_api.test_courier(self.fx.courier)
		log = frappe.get_all("Sync Log", filters={"operation": "Test Connection", "reference_name": self.fx.courier}, fields=["status"])
		self.assertEqual([x.status for x in log], ["Failed"])

	def test_overview_banner_lists_couriers_needing_action(self):
		self.use_ship24()
		ui_api.test_courier(self.fx.courier)
		banner = {b["courier"]: b for b in ui_api.overview()["banner"]}
		self.assertEqual(banner[self.fx.courier]["last_error"], "No API key saved")
		self.assertIn("settlement_via", banner[self.fx.courier])
		ui_api.save_courier(self.fx.courier, {}, api_key="k")
		# a new key resets the status to Not connected, which drops it from the banner
		self.assertNotIn(self.fx.courier, [b["courier"] for b in ui_api.overview()["banner"]])


class TestExceptionActions(UiApiCase):
	prefix = "UIE"

	def test_exceptions_list_counts_and_filters(self):
		self.make_exc("1")
		self.make_exc("2", exc_type="Unknown AWB")
		out = ui_api.exceptions({"courier": self.fx.courier})
		self.assertEqual(out["total"], 2)
		self.assertEqual(out["counts"]["Open"], 2)
		only = ui_api.exceptions({"courier": self.fx.courier, "exception_type": "Unknown AWB"})
		self.assertEqual(only["total"], 1)
		self.assertEqual(ui_api.exceptions({"courier": self.fx.courier, "tab": "Resolved"})["total"], 0)
		self.assertEqual(ui_api.exceptions({"courier": self.fx.courier, "search": "UIEAWB1"})["total"], 1)

	def test_exception_detail_and_missing_exception(self):
		_p, exc = self.make_exc("3")
		self.assertEqual(ui_api.exception_detail(exc.name)["header"]["name"], exc.name)
		with self.assertRaises(frappe.DoesNotExistError):
			ui_api.exception_detail("EXC-NOPE")
		with self.assertRaises(frappe.DoesNotExistError):
			ui_api.resolve_exception("EXC-NOPE", "assign")

	def test_unknown_action_is_refused(self):
		_p, exc = self.make_exc("4")
		with self.assertRaises(frappe.ValidationError):
			ui_api.resolve_exception(exc.name, "explode")

	def test_raise_dispute_uses_the_impact_as_the_claim(self):
		_p, exc = self.make_exc("5")
		res = ui_api.resolve_exception(exc.name, "raise_dispute", {"note": "weight"})
		self.assertEqual((res["dispute_status"], res["claim_amount"], res["status"]), ("Raised with Courier", 60, "Open"))

	def test_raise_dispute_with_custom_claim_and_rules(self):
		_p, exc = self.make_exc("6")
		self.assertEqual(ui_api.resolve_exception(exc.name, "raise_dispute", {"claim_amount": 25})["claim_amount"], 25)
		with self.assertRaises(frappe.ValidationError):  # already raised
			ui_api.resolve_exception(exc.name, "raise_dispute")
		_p, unknown = self.make_exc("7", exc_type="Unknown AWB")
		with self.assertRaises(frappe.ValidationError):  # not a disputable type
			ui_api.resolve_exception(unknown.name, "raise_dispute")
		_p, zero = self.make_exc("8", impact=0)
		with self.assertRaises(frappe.ValidationError):  # nothing to claim
			ui_api.resolve_exception(zero.name, "raise_dispute")

	def test_accept_deduction_marks_the_order_paid_and_resolves(self):
		parcel, exc = self.make_exc("9")
		res = ui_api.resolve_exception(exc.name, "accept_deduction", {"note": "fair"})
		self.assertEqual((res["status"], res["resolution"]), ("Resolved", "Accept deduction"))
		parcel.reload()
		self.assertEqual((parcel.payout_status, parcel.difference, parcel.expected_settlement), ("Paid", 0, NET_1KG - 60))

	def test_accept_deduction_not_allowed_for_other_types(self):
		_p, exc = self.make_exc("10", exc_type="Missing settlement")
		with self.assertRaises(frappe.ValidationError):
			ui_api.resolve_exception(exc.name, "accept_deduction")

	def test_resolve_manually_needs_a_note(self):
		_p, exc = self.make_exc("11")
		with self.assertRaises(frappe.ValidationError):
			ui_api.resolve_exception(exc.name, "resolve_manually", {"note": "  "})
		res = ui_api.resolve_exception(exc.name, "resolve_manually", {"note": "called courier"})
		self.assertEqual((res["status"], res["resolution"]), ("Resolved", "Resolved manually"))

	def test_resolved_exception_cannot_be_acted_on_again(self):
		_p, exc = self.make_exc("12")
		ui_api.resolve_exception(exc.name, "resolve_manually", {"note": "done"})
		with self.assertRaises(frappe.ValidationError):
			ui_api.resolve_exception(exc.name, "assign", {"assignee": ""})

	def test_resolving_closes_an_active_dispute_with_the_chosen_outcome(self):
		_p, exc = self.make_exc("13")
		ui_api.resolve_exception(exc.name, "raise_dispute")
		res = ui_api.resolve_exception(exc.name, "resolve_manually", {"note": "courier refused", "dispute_outcome": "Rejected"})
		self.assertEqual((res["status"], res["dispute_status"]), ("Resolved", "Rejected"))

	def test_assign_checks_the_user(self):
		_p, exc = self.make_exc("14")
		self.assertEqual(ui_api.resolve_exception(exc.name, "assign", {"assignee": "Administrator"})["assignee"], "Administrator")
		self.assertIsNone(ui_api.resolve_exception(exc.name, "assign", {"assignee": ""})["assignee"])
		with self.assertRaises(frappe.ValidationError):
			ui_api.resolve_exception(exc.name, "assign", {"assignee": "nobody@nowhere.invalid"})

	def test_failed_action_leaves_the_exception_untouched(self):
		_p, exc = self.make_exc("15")
		with self.assertRaises(frappe.ValidationError):
			ui_api.resolve_exception(exc.name, "raise_dispute", {"claim_amount": -5})
		exc.reload()
		self.assertEqual((exc.status, exc.dispute_status), ("Open", "Not raised"))

	def test_set_dispute_stage_and_send_claim_checks(self):
		_p, exc = self.make_exc("16")
		ui_api.resolve_exception(exc.name, "raise_dispute")
		with patch("codsync.codsync.disputes.frappe.sendmail"), patch("codsync.codsync.disputes._require_outgoing_email"):
			frappe.db.set_value("Courier", self.fx.courier, "claims_email", "claims@example.com")
			res = ui_api.send_claim([exc.name])
		self.assertTrue(res)
		self.assertEqual(frappe.db.get_value("COD Exception", exc.name, "dispute_status"), "Sent to courier")


class TestSettingsAndLists(UiApiCase):
	prefix = "UIS"

	def test_settings_never_return_secrets(self):
		out = ui_api.settings()
		self.assertNotIn("api_secret", str(out).lower().replace("api_secret_saved", ""))

	def test_save_settings_validation(self):
		for bad in (
			{"platform": "Nonexistent"},
			{"tolerance": -1},
			{"default_payout_cycle_days": 0},
			{"default_courier": "NoSuchCourier"},
			{"courier_mapping": [{"source_name": "x", "courier": ""}]},
			{"courier_mapping": [{"source_name": "x", "courier": "NoSuchCourier"}]},
			{"enabled": 1, "store_url": ""},
		):
			with self.assertRaises(frappe.ValidationError, msg=str(bad)):
				ui_api.save_settings(bad)

	def test_save_settings_tolerance_and_duplicate_mapping(self):
		ui_api.save_settings({"tolerance": 2.5})
		self.assertEqual(frappe.db.get_single_value("Store Connection", "tolerance"), 2.5)
		dup = [{"source_name": "Same", "courier": self.fx.courier}, {"source_name": "same", "courier": self.fx.courier}]
		with self.assertRaises(frappe.ValidationError):
			ui_api.save_settings({"courier_mapping": dup})

	def test_orders_filters_search_and_pagination(self):
		for k in ("1", "2", "3"):
			self.fx.make_parcel(k)
		self.fx.make_parcel("P", payment_mode="Prepaid")
		out = ui_api.orders(courier=self.fx.courier, page_size=2)
		self.assertEqual((out["total"], len(out["rows"])), (4, 2))
		self.assertEqual(out["counts"]["Prepaid"], 1)
		self.assertEqual(ui_api.orders(courier=self.fx.courier, tab="Prepaid")["total"], 1)
		self.assertEqual(ui_api.orders(courier=self.fx.courier, search="uis-2")["total"], 1)
		self.assertEqual(ui_api.orders(courier=self.fx.courier, page=2, page_size=3)["total"], 4)

	def test_order_detail_missing_order(self):
		with self.assertRaises(frappe.DoesNotExistError):
			ui_api.order_detail("UIS-NOPE")

	def test_sync_log_hides_payloads_and_filters_by_status(self):
		ui_api.test_courier(self.fx.courier)
		out = ui_api.sync_log(status="Success", operation="Test Connection")
		self.assertTrue(all(r["status"] == "Success" for r in out["rows"]))
		for r in out["rows"]:
			self.assertNotIn("request_payload", r)
			self.assertNotIn("response_payload", r)

	def test_report_validation(self):
		with self.assertRaises(frappe.ValidationError):
			ui_api.run_report("No Such Report")
		dated = next(r for r in ui_api.reports_list() if {"from_date", "to_date"} <= set(r["filters"]))
		with self.assertRaises(frappe.ValidationError):
			ui_api.run_report(dated["name"], {"from_date": "2026-02-01", "to_date": "2026-01-01"})
		self.assertIn("rows", ui_api.run_report(dated["name"], {"courier": self.fx.courier}))
