"""Explicit commits roll back failures and gate subsequent success actions."""

import inspect
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from codsync import shopify_auth as auth
from codsync.codsync import importer


class TestTransactionBoundaries(unittest.TestCase):
	def test_background_import_rolls_back_processing_and_commit_failures(self):
		for import_type, method in (("Parcels", "import_parcels"), ("Remittance", "import_remittance")):
			for failure_at in (None, "process", "commit"):
				with (
					self.subTest(import_type=import_type, failure_at=failure_at),
					patch.object(importer, "frappe", MagicMock()) as mocked,
					patch.object(importer, method, return_value={"created": 1}) as process,
				):
					failure = RuntimeError("transaction failed")
					if failure_at == "process":
						process.side_effect = failure
					elif failure_at == "commit":
						mocked.db.commit.side_effect = failure
					if failure_at:
						with self.assertRaises(RuntimeError) as raised:
							importer._run_background(import_type, "file.csv", "C1", None, "requester")
						self.assertIs(raised.exception, failure)
						mocked.db.rollback.assert_called_once_with()
						mocked.publish_realtime.assert_not_called()
					else:
						importer._run_background(import_type, "file.csv", "C1", None, "requester")
						mocked.db.commit.assert_called_once_with()
						mocked.db.rollback.assert_not_called()
						mocked.publish_realtime.assert_called_once_with(
							"codsync_import_done", {"created": 1}, user="requester"
						)

	def test_shopify_install_rolls_back_writes_and_commit_failures(self):
		for failure_at in (None, "write", "password", "commit"):
			with (
				self.subTest(failure_at=failure_at),
				patch.object(auth, "frappe", MagicMock()) as mocked,
				patch.object(auth, "_request_token", return_value="session-token"),
				patch.object(auth, "decode_session_token", return_value=("example.myshopify.com", {})),
				patch.object(
					auth,
					"_single_store_check",
					return_value=MagicMock(token_expiry=None, store_url="", enabled=False),
				),
				patch.object(auth, "exchange_token", return_value="test-token"),
				patch.object(auth, "_app_credentials", return_value=("test-id", "test-secret")),
				patch.object(auth, "set_encrypted_password") as password,
				patch.object(auth, "now_datetime", return_value=datetime(2026, 11, 19)),
				patch.object(auth, "_base_url", return_value="https://example.invalid"),
				patch.object(auth, "register_webhooks", return_value={}) as register,
				patch.object(auth, "_log"),
				patch.object(auth, "ensure_shop_user", return_value="shop-user") as ensure,
			):
				failure = RuntimeError("transaction failed")
				if failure_at == "write":
					mocked.db.set_single_value.side_effect = failure
				elif failure_at == "password":
					password.side_effect = failure
				elif failure_at == "commit":
					mocked.db.commit.side_effect = failure
				if failure_at:
					with self.assertRaises(RuntimeError) as raised:
						inspect.unwrap(auth.connect)()
					self.assertIs(raised.exception, failure)
					mocked.db.rollback.assert_called_once_with()
					register.assert_not_called()
					ensure.assert_not_called()
				else:
					self.assertTrue(inspect.unwrap(auth.connect)()["connected"])
					mocked.db.commit.assert_called_once_with()
					mocked.db.rollback.assert_not_called()
					register.assert_called_once()

	def test_shopify_webhook_rolls_back_handler_and_commit_failures(self):
		for failure_at in (None, "process", "commit"):
			with (
				self.subTest(failure_at=failure_at),
				patch.object(auth, "frappe", MagicMock()) as mocked,
				patch.object(auth, "valid_hmac", return_value=True),
				patch.object(auth, "handle_topic", return_value="uninstalled") as process,
				patch.object(auth, "_log"),
			):
				mocked.get_request_header.side_effect = lambda key: {
					"X-Shopify-Topic": "app/uninstalled",
					"X-Shopify-Shop-Domain": "example.myshopify.com",
				}.get(key, "signature")
				mocked.parse_json.return_value = {}
				failure = RuntimeError("transaction failed")
				if failure_at == "process":
					process.side_effect = failure
				elif failure_at == "commit":
					mocked.db.commit.side_effect = failure
				if failure_at:
					with self.assertRaises(RuntimeError) as raised:
						inspect.unwrap(auth.webhook)()
					self.assertIs(raised.exception, failure)
					mocked.db.rollback.assert_called_once_with()
				else:
					self.assertEqual(inspect.unwrap(auth.webhook)(), {"status": "ok"})
					mocked.db.commit.assert_called_once_with()
					mocked.db.rollback.assert_not_called()
