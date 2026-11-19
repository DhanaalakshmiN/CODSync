"""Filter compatibility, sync-log metadata and background failure handling without a database."""

import inspect
import json
import unittest
from unittest.mock import MagicMock, patch

import frappe

from codsync.codsync import synclog, ui_api


class TestListFilters(unittest.TestCase):
	def test_orders_accept_grouped_and_existing_keywords(self):
		rows = [
			frappe._dict(
				name="P1",
				payment_mode="COD",
				delivery_status="Delivered",
				cod_status="Collected",
				reconciliation_status="Pending",
			)
		]
		filters = {
			"courier": "C1",
			"from_date": "2026-01-01",
			"delivery_status": "Delivered",
			"cod_status": "Collected",
			"reconciliation": "Pending",
		}
		orders = inspect.unwrap(ui_api.orders)
		with (
			patch.object(ui_api, "_read"),
			patch.object(ui_api, "_orders", return_value=rows) as get_orders,
			patch.object(ui_api, "_order_row", side_effect=lambda p: {"order_id": p.name}),
		):
			legacy = orders(tab="COD", **filters)
			for grouped in (filters, json.dumps(filters)):
				self.assertEqual(orders(tab="COD", filters=grouped), legacy)
			get_orders.assert_called_with("C1", since="2026-01-01", until=None)
			self.assertEqual(legacy["total"], 1)

	def test_explicit_keywords_override_grouped_filters(self):
		with patch.object(ui_api, "_read"), patch.object(ui_api, "_orders", return_value=[]) as get_orders:
			inspect.unwrap(ui_api.orders)(filters={"courier": "old"}, courier=None)
			get_orders.assert_called_once_with(None, since=None, until=None)

	def test_invalid_grouped_filters_are_rejected_before_querying(self):
		for endpoint in (ui_api.orders, ui_api.reconciliation):
			for value in ("invalid-json", "[]", [], 42):
				with (
					self.subTest(endpoint=endpoint.__name__, value=value),
					patch.object(ui_api, "_read"),
					patch.object(ui_api, "_orders") as get_orders,
					patch.object(ui_api.frappe, "throw", side_effect=frappe.ValidationError),
					patch.object(ui_api, "_", side_effect=lambda text: text),
				):
					with self.assertRaises(frappe.ValidationError):
						inspect.unwrap(endpoint)(filters=value)
					get_orders.assert_not_called()

	def test_reconciliation_accepts_grouped_and_existing_keywords(self):
		rows = [
			frappe._dict(
				name="P1",
				courier="C1",
				payment_mode="COD",
				delivery_status="Delivered",
				payout_status="Paid",
				settlement_batch="B1",
				difference=-2,
				cod_amount=100,
				expected_settlement=100,
				actual_settlement=98,
				reconciliation_status="Reconciled",
			)
		]
		filters = {"courier": "C1", "batch": "B1", "difference_not_zero": 1, "parcels": ["P1"]}
		reconciliation = inspect.unwrap(ui_api.reconciliation)
		with (
			patch.object(ui_api, "_read"),
			patch.object(ui_api, "_orders", return_value=rows),
			patch.object(ui_api, "_batch_info", return_value={}),
			patch.object(ui_api, "_tolerance", return_value=1),
			patch.object(ui_api, "_order_url", return_value=None),
		):
			legacy = reconciliation(**filters)
			self.assertEqual(reconciliation(filters=filters), legacy)
			self.assertEqual(reconciliation(filters=json.dumps(filters)), legacy)
			self.assertEqual(legacy["total"], 1)
			self.assertEqual(reconciliation(filters={**filters, "parcels": ["other"]})["total"], 0)

	def test_frappe_dispatch_retains_existing_filter_keywords(self):
		for endpoint, kwargs in (
			(ui_api.orders, {"courier": "C1", "delivery_status": "Delivered"}),
			(ui_api.reconciliation, {"batch": "B1", "difference_not_zero": 1}),
		):
			self.assertEqual(frappe.get_newargs(endpoint, kwargs), kwargs)


class TestSyncLogDetails(unittest.TestCase):
	def test_grouped_metadata_matches_existing_keywords(self):
		values = {
			"error_message": "x" * 600,
			"external_id": "y" * 150,
			"request_payload": {"count": 1},
			"response_payload": {"ok": True},
			"attempt": 2,
			"duration_ms": 123,
			"http_status": 502,
			"error_code": "upstream",
			"endpoint": "/orders",
			"reference_doctype": "Courier",
			"reference_name": "C1",
		}
		with patch.object(synclog.frappe, "get_doc") as get_doc:
			synclog.log_sync("Shopify", "Order Sync", "Failed", **values)
			legacy = get_doc.call_args.args[0]
			synclog.log_sync("Shopify", "Order Sync", "Failed", details=synclog.SyncLogDetails(**values))
			self.assertEqual(get_doc.call_args.args[0], legacy)
			self.assertEqual(len(legacy["error_message"]), 500)
			self.assertEqual(len(legacy["external_id"]), 140)
			self.assertEqual(json.loads(legacy["request_payload"]), {"count": 1})
			self.assertEqual(get_doc.return_value.insert.call_count, 2)

	def test_overrides_do_not_mutate_details(self):
		details = synclog.SyncLogDetails(attempt=2)
		with patch.object(synclog.frappe, "get_doc") as get_doc:
			synclog.log_sync("Shopify", "Order Sync", "Success", details=details, attempt=3)
			self.assertEqual(get_doc.call_args.args[0]["attempt"], 3)
		self.assertEqual(details.attempt, 2)

	def test_logging_failure_is_reported_without_raising(self):
		with (
			patch.object(synclog.frappe, "get_doc", side_effect=RuntimeError("unavailable")),
			patch.object(synclog.frappe, "get_traceback", return_value="trace"),
			patch.object(synclog.frappe, "log_error") as log_error,
		):
			synclog.log_sync("Shopify", "Order Sync", "Failed")
			log_error.assert_called_once_with("trace", "CODSync log_sync")


class TestFetchOrdersJob(unittest.TestCase):
	def test_failure_is_logged_and_cleanup_restores_user(self):
		with patch.object(ui_api, "frappe", MagicMock()) as mocked:
			mocked.session.user = "original"
			mocked.get_doc.return_value.fetch_orders.side_effect = RuntimeError("fetch failed")
			mocked.get_traceback.return_value = "trace"
			ui_api._fetch_orders_job("requester")
			mocked.log_error.assert_called_once_with("trace", "CODSync background order fetch")
			mocked.cache.return_value.delete_value.assert_called_once_with(ui_api.FETCH_FLAG)
			mocked.db.commit.assert_not_called()
			self.assertEqual(mocked.set_user.call_args_list[0].args, ("requester",))
			self.assertEqual(mocked.set_user.call_args_list[-1].args, ("original",))

	def test_cache_cleanup_failure_still_restores_user(self):
		with patch.object(ui_api, "frappe", MagicMock()) as mocked:
			mocked.session.user = "original"
			mocked.cache.return_value.delete_value.side_effect = RuntimeError("cache failed")
			with self.assertRaisesRegex(RuntimeError, "cache failed"):
				ui_api._fetch_orders_job("requester")
			mocked.set_user.assert_called_with("original")
			mocked.db.commit.assert_not_called()
