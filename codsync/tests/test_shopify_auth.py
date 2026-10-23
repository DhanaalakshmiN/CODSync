"""Shopify embedded auth: session tokens, the auth hook, install (token exchange), webhooks and privacy."""

import base64
import hashlib
import hmac
import time
from unittest.mock import MagicMock, patch

import frappe
import jwt
import requests
from frappe.tests import IntegrationTestCase
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from codsync import shopify_auth as sa
from codsync.tests.helpers import Fixture

CLIENT_ID, SECRET = "test-client-id", "test-client-secret"
SHOP = "uni-test-shop.myshopify.com"
CONF = {"shopify_client_id": CLIENT_ID, "shopify_client_secret": SECRET}
COMMIT = "frappe.database.database.Database.commit"


def make_token(shop=SHOP, secret=SECRET, aud=CLIENT_ID, exp=60, **override):
	now = int(time.time())
	claims = {
		"iss": f"https://{shop}/admin", "dest": f"https://{shop}", "aud": aud,
		"sub": "1", "exp": None if exp is None else now + exp, "nbf": now - 5, "iat": now, "jti": "x", "sid": "s",
	}
	claims.update(override)
	return jwt.encode({k: v for k, v in claims.items() if v is not None}, secret, algorithm="HS256")


def sign(body, secret=SECRET):
	return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


class ShopifyCase(IntegrationTestCase):
	"""Pins the app credentials and puts the Store Connection and shop user back afterwards."""

	FIELDS = (
		"platform", "enabled", "store_url", "shopify_client_id", "token_expiry", "webhook_secret",
	)

	def setUp(self):
		self.conf = patch.dict(frappe.conf, CONF)
		self.conf.start()
		self.saved = {f: frappe.db.get_single_value("Store Connection", f) for f in self.FIELDS}
		self.saved_token = get_decrypted_password(
			"Store Connection", "Store Connection", "access_token", raise_exception=False
		)
		self.commit = patch(COMMIT)
		self.commit.start()
		# User / File inserts queue a global-search update in Redis; the test bench may not have it running
		self.search = patch("frappe.utils.global_search.sync_value_in_queue")
		self.search.start()

	def tearDown(self):
		frappe.set_user("Administrator")
		for f, v in self.saved.items():
			frappe.db.set_single_value("Store Connection", f, v)
		set_encrypted_password("Store Connection", "Store Connection", self.saved_token or "", "access_token")
		# direct deletes: User.on_trash queues work in Redis, which the test bench may not have
		emails = frappe.get_all("User", filters={"name": ["like", f"%@{sa.USER_DOMAIN}"]}, pluck="name")
		if emails:
			for dt, field in (("Has Role", "parent"), ("Notification Settings", "name"), ("User", "name")):
				frappe.db.delete(dt, {field: ["in", emails]})
		frappe.db.delete("COD Parcel", {"order_id": ["like", "SHP-%"]})
		self.search.stop()
		self.commit.stop()
		self.conf.stop()
		frappe.clear_document_cache("Store Connection", "Store Connection")


class TestSessionToken(ShopifyCase):
	def test_valid_token_returns_the_shop(self):
		shop, payload = sa.decode_session_token(make_token())
		self.assertEqual(shop, SHOP)
		self.assertEqual(payload["aud"], CLIENT_ID)

	def test_rejects_bad_tokens(self):
		bad = {
			"expired": make_token(exp=-120),
			"wrong secret": make_token(secret="other"),
			"wrong audience": make_token(aud="someone-else"),
			"not a store": make_token(dest="https://evil.example.com"),
			"issuer for another shop": make_token(iss="https://other.myshopify.com/admin"),
			"no expiry": make_token(exp=None),
			"garbage": "not.a.jwt",
		}
		for name, token in bad.items():
			with self.assertRaises(frappe.AuthenticationError, msg=name):
				sa.decode_session_token(token)

	def test_rejects_an_unsigned_token(self):
		token = jwt.encode({"aud": CLIENT_ID, "exp": int(time.time()) + 60}, None, algorithm="none")
		with self.assertRaises(frappe.AuthenticationError):
			sa.decode_session_token(token)

	def test_site_without_app_credentials_refuses_everything(self):
		with patch.dict(frappe.conf, {"shopify_client_id": "", "shopify_client_secret": ""}):
			with self.assertRaises(frappe.AuthenticationError):
				sa.decode_session_token(make_token())

	def test_token_is_read_from_the_request_header(self):
		with patch("frappe.get_request_header", return_value="Bearer abc"):
			self.assertEqual(sa._request_token(), "abc")
		with patch("frappe.get_request_header", return_value=None):
			self.assertIsNone(sa._request_token())

	def test_verify_session_token_needs_the_header(self):
		with patch("frappe.get_request_header", return_value=None):
			with self.assertRaises(frappe.AuthenticationError):
				sa.verify_session_token()
		with patch("frappe.get_request_header", return_value=make_token()):
			self.assertEqual(sa.verify_session_token(), SHOP)


class TestShopUser(ShopifyCase):
	def test_email_is_derived_from_the_shop(self):
		self.assertEqual(sa.shop_user(SHOP), f"uni-test-shop@{sa.USER_DOMAIN}")

	def test_creates_one_manager_user_per_shop_and_is_idempotent(self):
		email = sa.ensure_shop_user(SHOP)
		self.assertEqual(sa.ensure_shop_user(SHOP), email)
		self.assertEqual(frappe.db.count("User", {"name": email}), 1)
		roles = frappe.get_all("Has Role", filters={"parent": email}, pluck="role")
		self.assertIn(sa.SHOP_ROLE, roles)
		self.assertNotIn("System Manager", roles)

	def test_disabled_user_is_re_enabled(self):
		email = sa.ensure_shop_user(SHOP)
		frappe.db.set_value("User", email, "enabled", 0)
		sa.ensure_shop_user(SHOP)
		self.assertEqual(frappe.db.get_value("User", email, "enabled"), 1)


class TestAuthHook(ShopifyCase):
	def setUp(self):
		super().setUp()
		# the real site may be connected to its own dev store; start from "no store connected"
		frappe.db.set_single_value("Store Connection", {"enabled": 0, "store_url": ""}, None)
		frappe.clear_document_cache("Store Connection", "Store Connection")

	def run_hook(self, token):
		with patch("frappe.get_request_header", return_value=token), patch("frappe.set_user") as set_user:
			sa.authenticate()
		return set_user

	def test_no_header_leaves_the_session_alone(self):
		self.run_hook(None).assert_not_called()

	def test_valid_token_acts_as_the_shop_user(self):
		email = sa.ensure_shop_user(SHOP)
		self.run_hook(make_token()).assert_called_once_with(email)

	def test_first_valid_token_creates_the_shop_user_so_connect_can_run(self):
		# App Bridge sends a bearer header on the very first call; Frappe refuses a Guest bearer request
		shop = "first-open.myshopify.com"
		frappe.db.set_single_value("Store Connection", {"enabled": 0, "store_url": ""}, None)
		frappe.clear_document_cache("Store Connection", "Store Connection")
		self.assertFalse(frappe.db.exists("User", sa.shop_user(shop)))
		self.run_hook(make_token(shop=shop)).assert_called_once_with(sa.shop_user(shop))
		self.assertTrue(frappe.db.exists("User", sa.shop_user(shop)))

	def test_a_different_shop_than_the_connected_one_is_refused_by_the_hook(self):
		frappe.db.set_single_value("Store Connection", {"enabled": 1, "store_url": SHOP}, None)
		frappe.clear_document_cache("Store Connection", "Store Connection")
		with self.assertRaises(frappe.PermissionError):
			self.run_hook(make_token(shop="intruder.myshopify.com"))
		self.assertFalse(frappe.db.exists("User", sa.shop_user("intruder.myshopify.com")))

	def test_reopening_after_reinstall_re_enables_the_user(self):
		email = sa.ensure_shop_user(SHOP)
		frappe.db.set_value("User", email, "enabled", 0)  # as the uninstall webhook does
		frappe.db.set_single_value("Store Connection", {"enabled": 0, "store_url": ""}, None)
		frappe.clear_document_cache("Store Connection", "Store Connection")
		self.run_hook(make_token()).assert_called_once_with(email)
		self.assertEqual(frappe.db.get_value("User", email, "enabled"), 1)

	def test_bad_token_is_an_error_not_a_silent_guest(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.run_hook(make_token(secret="other"))


class TestConnect(ShopifyCase):
	def connect(self, token=None, exchange="shpat_new"):
		with patch("frappe.get_request_header", return_value=token or make_token()), patch.object(
			sa, "exchange_token", return_value=exchange
		) as ex, patch.object(sa, "register_webhooks", return_value={"orders/create": "ok"}) as reg, patch.object(
			sa, "_base_url", return_value="https://app.example.com"
		):
			out = sa.connect()
		return out, ex, reg

	def reset_connection(self):
		frappe.db.set_single_value("Store Connection", {"enabled": 0, "store_url": ""}, None)
		set_encrypted_password("Store Connection", "Store Connection", "", "access_token")
		frappe.clear_document_cache("Store Connection", "Store Connection")

	def test_first_open_connects_the_shop(self):
		self.reset_connection()
		out, ex, reg = self.connect()
		self.assertEqual(out, {"shop": SHOP, "user": sa.shop_user(SHOP), "connected": True})
		conn = frappe.get_single("Store Connection")
		self.assertEqual((conn.platform, conn.store_url, conn.enabled), ("Shopify", SHOP, 1))
		self.assertEqual(conn.get_password("access_token"), "shpat_new")
		self.assertEqual(conn.get_password("webhook_secret"), SECRET)
		self.assertGreater(frappe.utils.get_datetime(conn.token_expiry).year, frappe.utils.now_datetime().year + 5)
		reg.assert_called_once()
		self.assertEqual(reg.call_args.args[:3], (SHOP, "shpat_new", "https://app.example.com"))
		self.assertTrue(frappe.db.exists("User", sa.shop_user(SHOP)))

	def test_reopening_does_not_exchange_again(self):
		self.reset_connection()
		self.connect()
		_out, ex, reg = self.connect()
		ex.assert_not_called()
		reg.assert_not_called()

	def test_old_short_lived_token_is_replaced_on_first_open(self):
		self.reset_connection()
		self.connect()
		frappe.db.set_single_value("Store Connection", "token_expiry", frappe.utils.add_to_date(None, hours=5))
		frappe.clear_document_cache("Store Connection", "Store Connection")
		_out, ex, reg = self.connect(exchange="shpat_offline")
		ex.assert_called_once()
		reg.assert_called_once()
		self.assertEqual(frappe.get_single("Store Connection").get_password("access_token"), "shpat_offline")

	def test_a_second_different_shop_is_refused(self):
		self.reset_connection()
		self.connect()
		with self.assertRaises(frappe.PermissionError):
			self.connect(token=make_token(shop="another-shop.myshopify.com"))
		self.assertFalse(frappe.db.exists("User", sa.shop_user("another-shop.myshopify.com")))

	def test_bad_token_cannot_connect(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.connect(token=make_token(secret="other"))

	def test_missing_token_cannot_connect(self):
		with patch("frappe.get_request_header", return_value=None):
			with self.assertRaises(frappe.AuthenticationError):
				sa.connect()

	def test_failed_exchange_connects_nothing(self):
		self.reset_connection()
		with patch("frappe.get_request_header", return_value=make_token()), patch.object(
			sa, "exchange_token", side_effect=requests.HTTPError("401")
		):
			with self.assertRaises(requests.HTTPError):
				sa.connect()
		self.assertFalse(frappe.db.exists("User", sa.shop_user(SHOP)))


class TestTokenExchangeAndWebhooks(ShopifyCase):
	def test_exchange_sends_the_token_exchange_grant(self):
		resp = MagicMock(ok=True)
		resp.json.return_value = {"access_token": "shpat_x"}
		with patch("requests.post", return_value=resp) as post:
			self.assertEqual(sa.exchange_token(SHOP, "SESSION"), "shpat_x")
		self.assertEqual(post.call_args.args[0], f"https://{SHOP}/admin/oauth/access_token")
		body = post.call_args.kwargs["json"]
		self.assertEqual(body["subject_token"], "SESSION")
		self.assertEqual(body["client_id"], CLIENT_ID)
		self.assertIn("token-exchange", body["grant_type"])
		self.assertIn("offline-access-token", body["requested_token_type"])

	def test_exchange_without_a_token_in_the_answer_fails(self):
		resp = MagicMock(ok=True)
		resp.json.return_value = {}
		with patch("requests.post", return_value=resp):
			with self.assertRaises(frappe.ValidationError):
				sa.exchange_token(SHOP, "SESSION")

	def test_register_webhooks_reports_each_topic(self):
		answers = [MagicMock(ok=True, status_code=201), MagicMock(ok=False, status_code=422)]
		with patch("requests.post", side_effect=answers) as post:
			out = sa.register_webhooks(SHOP, "tok", "https://app.example.com", "2026-07")
		self.assertEqual(out, {"orders/create": "ok", "app/uninstalled": "ok"})  # 422 = already registered
		sent = {c.kwargs["json"]["webhook"]["topic"]: c.kwargs["json"]["webhook"]["address"] for c in post.call_args_list}
		self.assertTrue(sent["orders/create"].endswith("codsync.codsync.api.webhook"))
		self.assertTrue(sent["app/uninstalled"].endswith("codsync.shopify_auth.webhook"))
		with patch("requests.post", side_effect=[MagicMock(ok=False, status_code=500), requests.ConnectionError("down")]):
			out = sa.register_webhooks(SHOP, "tok", "https://app.example.com", "2026-07")
		self.assertEqual(out["orders/create"], "HTTP 500")
		self.assertIn("down", out["app/uninstalled"])

	def test_hmac_check(self):
		body = b'{"a": 1}'
		self.assertTrue(sa.valid_hmac(body, sign(body)))
		self.assertFalse(sa.valid_hmac(body, sign(body, "other-secret")))
		self.assertFalse(sa.valid_hmac(b'{"a": 2}', sign(body)))
		self.assertFalse(sa.valid_hmac(body, ""))
		self.assertFalse(sa.valid_hmac(body, None))


class TestLifecycleAndPrivacy(ShopifyCase):
	def setUp(self):
		super().setUp()
		self.fx = Fixture("SHP")
		self.fx.make_courier()
		frappe.db.set_single_value("Store Connection", {"enabled": 1, "store_url": SHOP}, None)
		set_encrypted_password("Store Connection", "Store Connection", "shpat_live", "access_token")
		self.email = sa.ensure_shop_user(SHOP)

	def tearDown(self):
		self.fx.cleanup()
		super().tearDown()

	def parcel(self, key, external_id):
		return self.fx.make_parcel(
			key, order_id=f"SHP-{key}", external_id=external_id, customer_name="Asha", phone="9840000000",
			email="asha@example.com", address="1 Main St", city="Chennai", pincode="600001",
		)

	def pii(self, parcel):
		return [frappe.db.get_value("COD Parcel", parcel.name, f) for f in sa.PII_FIELDS]

	def test_uninstall_revokes_access(self):
		self.assertEqual(sa.handle_topic("app/uninstalled", SHOP, {}), "uninstalled")
		conn = frappe.get_single("Store Connection")
		self.assertEqual(conn.enabled, 0)
		self.assertFalse(conn.get_password("access_token", raise_exception=False))
		self.assertEqual(frappe.db.get_value("User", self.email, "enabled"), 0)

	def test_uninstall_of_another_shop_does_not_touch_this_connection(self):
		sa.handle_topic("app/uninstalled", "someone-else.myshopify.com", {})
		self.assertEqual(frappe.get_single("Store Connection").enabled, 1)

	def test_customer_redact_blanks_only_the_listed_orders(self):
		mine, other = self.parcel("1", "111"), self.parcel("2", "222")
		out = sa.handle_topic("customers/redact", SHOP, {"orders_to_redact": [111]})
		self.assertEqual(out, "redacted 1 order(s)")
		self.assertEqual(self.pii(mine), [None] * len(sa.PII_FIELDS))
		self.assertEqual(self.pii(other)[0], "Asha")
		# the money fields survive
		self.assertEqual(frappe.db.get_value("COD Parcel", mine.name, "cod_amount"), 1000)

	def test_customer_redact_with_no_orders_changes_nothing(self):
		p = self.parcel("3", "333")
		self.assertEqual(sa.handle_topic("customers/redact", SHOP, {}), "redacted 0 order(s)")
		self.assertEqual(self.pii(p)[0], "Asha")

	def test_shop_redact_anonymises_everything_and_revokes(self):
		a, b = self.parcel("4", "444"), self.parcel("5", "555")
		sa.handle_topic("shop/redact", SHOP, {})
		self.assertEqual(self.pii(a), [None] * len(sa.PII_FIELDS))
		self.assertEqual(self.pii(b), [None] * len(sa.PII_FIELDS))
		self.assertEqual(frappe.get_single("Store Connection").enabled, 0)

	def test_data_request_and_unknown_topics_change_nothing(self):
		p = self.parcel("6", "666")
		self.assertEqual(sa.handle_topic("customers/data_request", SHOP, {}), "data request logged")
		self.assertEqual(sa.handle_topic("orders/paid", SHOP, {}), "ignored")
		self.assertEqual(self.pii(p)[0], "Asha")
		self.assertEqual(frappe.get_single("Store Connection").enabled, 1)
