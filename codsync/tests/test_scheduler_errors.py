"""Scheduled job failures are logged without hiding failed jobs or breaking courier isolation."""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import frappe

from codsync.codsync import disputes, engine, tasks


class TestSchedulerErrors(unittest.TestCase):
	def test_daily_order_sync_restores_user_and_defers_commit_to_worker(self):
		for failure in (None, RuntimeError("fetch failed")):
			with self.subTest(failure=failure), patch.object(tasks, "frappe", MagicMock()) as mocked:
				mocked.session.user = "original"
				mocked.get_doc.return_value.enabled = True
				mocked.get_doc.return_value.fetch_orders.side_effect = failure
				tasks.run_daily_order_sync()
				mocked.set_user.assert_called_with("original")
				mocked.db.commit.assert_not_called()
				self.assertEqual(mocked.log_error.call_count, int(failure is not None))

	def test_query_failures_are_logged_and_reraised(self):
		jobs = (
			(disputes, "send_follow_ups", "CODSync dispute follow-ups"),
			(engine, "run_hourly_settlement_sync", "CODSync hourly settlement sync"),
			(tasks, "run_hourly_failure_alert", "CODSync hourly failure alert"),
			(tasks, "run_daily_mark_missing", "CODSync daily mark missing"),
		)
		for module, name, title in jobs:
			with (
				self.subTest(job=name),
				patch.object(module, "frappe", MagicMock()) as mocked,
				patch("frappe.utils.now_datetime", return_value=datetime(2026, 11, 19, 12)),
				patch.object(disputes, "nowdate", return_value="2026-11-19"),
			):
				failure = RuntimeError("query failed")
				mocked.get_all.side_effect = failure
				mocked.get_traceback.return_value = "trace"
				with self.assertRaises(RuntimeError) as raised:
					getattr(module, name)()
				self.assertIs(raised.exception, failure)
				mocked.log_error.assert_called_once_with("trace", title)

	def test_mark_missing_continues_after_one_courier_fails(self):
		with (
			patch.object(tasks, "frappe", MagicMock()) as mocked,
			patch.object(tasks, "mark_missing") as mark,
		):
			mocked.get_all.return_value = ["first", "second"]
			mark.side_effect = [RuntimeError("courier failed"), None]
			tasks.run_daily_mark_missing()
			self.assertEqual(mark.call_args_list, [call("first"), call("second")])
			self.assertEqual(mocked.log_error.call_count, 1)

	def test_settlement_sync_keeps_due_time_rules(self):
		now = datetime(2026, 11, 19, 12)
		rows = [
			frappe._dict(name="due", settlement_sync_time="09:00:00", last_settlement_sync=None),
			frappe._dict(name="later", settlement_sync_time="15:00:00", last_settlement_sync=None),
			frappe._dict(name="done", settlement_sync_time="09:00:00", last_settlement_sync=now),
		]
		with (
			patch.object(engine, "frappe", MagicMock()) as mocked,
			patch.object(engine, "sync_settlements") as sync,
		):
			mocked.get_all.return_value = rows
			mocked.utils.now_datetime.return_value = now
			mocked.utils.get_datetime.side_effect = datetime.fromisoformat
			engine.run_hourly_settlement_sync()
			sync.assert_called_once_with("due")
			mocked.log_error.assert_not_called()

	def test_follow_ups_with_no_due_claims_keep_zero_result(self):
		with (
			patch.object(disputes, "frappe", MagicMock()) as mocked,
			patch.object(disputes, "nowdate", return_value="2026-11-19"),
		):
			mocked.get_all.return_value = []
			self.assertEqual(disputes.send_follow_ups(), {"reminded": 0})
			mocked.log_error.assert_not_called()

	def test_mail_failure_is_logged_and_reraised(self):
		with (
			patch.object(tasks, "frappe", MagicMock()) as mocked,
			patch("frappe.utils.now_datetime", return_value=datetime(2026, 11, 19, 12)),
		):
			mocked.get_all.return_value = [
				frappe._dict(creation="now", platform="Shopify", operation="Order Sync")
			]
			mocked.utils.escape_html.return_value = "alert"
			mocked.sendmail.side_effect = RuntimeError("mail failed")
			with self.assertRaisesRegex(RuntimeError, "mail failed"):
				tasks.run_hourly_failure_alert()
			self.assertEqual(mocked.log_error.call_args.args[1], "CODSync hourly failure alert")
