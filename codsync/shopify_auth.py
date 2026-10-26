"""Shopify embedded-app authentication and lifecycle.

Flow (no cookies are needed inside the Shopify iframe):
  1. App Bridge gives the page a short-lived session token (a JWT signed with the app secret).
  2. The page calls `connect` once. We verify the token, exchange it for an offline Admin API
     token (Shopify token exchange), create the shop's own Frappe user and register webhooks.
  3. Every later request carries the session token in `X-Shopify-Session-Token`; the
     `authenticate` auth hook verifies it and acts as that shop's user.

Currently one store per site: `connect` refuses a second, different shop.
"""

import base64
import hashlib
import hmac
import re
import time
from urllib.parse import urlparse

import frappe
import jwt
import requests
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime
from frappe.utils.password import set_encrypted_password

HEADER = "X-Shopify-Session-Token"
SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*\.myshopify\.com$")
SHOP_ROLE = "CODSync Manager"
USER_DOMAIN = "shops.codsync.local"
# Shopify offline tokens do not expire; the adapter treats a far-future expiry as "keep using it"
OFFLINE_TOKEN_YEARS = 10
# NOTE: Shopify spells this topic "orders/cancelled" (two L's); anything else is rejected with 422
WEBHOOK_TOPICS = ("orders/create", "orders/updated", "orders/cancelled", "app/uninstalled")
COMPLIANCE_TOPICS = ("customers/data_request", "customers/redact", "shop/redact")


# --------------------------------------------------------------------------- session token


def _app_credentials():
	client_id = frappe.conf.get("shopify_client_id")
	client_secret = frappe.conf.get("shopify_client_secret")
	if not (client_id and client_secret):
		frappe.throw(_("Shopify app credentials are not configured on this site"), frappe.AuthenticationError)
	return client_id, client_secret


def _host(url):
	return re.sub(r"^https?://", "", url or "").split("/")[0].lower()


def _log_rejection(token, client_id, error):
	"""Say why a token was refused (claim values only, never the token or secret) in logs/codsync_shopify.log."""
	try:
		claims = jwt.decode(token, options={"verify_signature": False})
	except Exception:
		claims = {}
	frappe.logger("codsync_shopify", allow_site=False, file_count=3).warning(
		"session token rejected: %s: %s | token aud=%s (site client id=%s) dest=%s iss=%s exp=%s now=%s",
		type(error).__name__, error, claims.get("aud"), client_id, claims.get("dest"), claims.get("iss"),
		claims.get("exp"), int(time.time()),
	)


def decode_session_token(token):
	"""Verify an App Bridge session token and return (shop domain, payload). Raises AuthenticationError."""
	client_id, client_secret = _app_credentials()
	try:
		payload = jwt.decode(
			token,
			client_secret,
			algorithms=["HS256"],
			audience=client_id,
			leeway=10,
			options={"require": ["exp", "aud", "dest", "iss"]},
		)
	except Exception as e:
		_log_rejection(token, client_id, e)
		frappe.throw(_("Invalid Shopify session token: {0}").format(e), frappe.AuthenticationError)
	shop = _host(payload.get("dest"))
	if not SHOP_RE.match(shop):
		frappe.throw(_("Session token is not for a Shopify store"), frappe.AuthenticationError)
	iss = urlparse(payload.get("iss") or "")
	if (iss.netloc.lower(), iss.path.rstrip("/")) != (shop, "/admin"):
		frappe.throw(_("Session token issuer does not match the store"), frappe.AuthenticationError)
	return shop, payload


def _request_token():
	"""The session token on this request, or None. Never raises."""
	try:
		value = frappe.get_request_header(HEADER) or ""
	except Exception:
		return None
	return value.replace("Bearer ", "").strip() or None


def verify_session_token():
	"""Shop domain of the verified session token on the current request."""
	token = _request_token()
	if not token:
		frappe.throw(_("Missing Shopify session token"), frappe.AuthenticationError)
	return decode_session_token(token)[0]


# --------------------------------------------------------------------------- shop user


def shop_user(shop):
	"""Email of the Frappe user that represents this shop."""
	return f"{shop.removesuffix('.myshopify.com')}@{USER_DOMAIN}"


def ensure_shop_user(shop):
	"""Create (or re-enable) the shop's own user with the CODSync Manager role. Returns the email."""
	email = shop_user(shop)
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
		if not user.enabled:
			user.enabled = 1
			user.save(ignore_permissions=True)
		return email
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": shop.removesuffix(".myshopify.com"),
			"user_type": "System User",
			"enabled": 1,
			"send_welcome_email": 0,
			"roles": [{"role": SHOP_ROLE}],
		}
	).insert(ignore_permissions=True)
	return email


def authenticate():
	"""auth_hooks entry: act as the shop's user when a valid session token accompanies the request.

	Requests without the header are untouched (normal cookie login). A bad token is an error, not a
	silent Guest, so a broken embed is visible.

	App Bridge also puts the token in an `Authorization: Bearer` header on every request, and Frappe
	rejects a bearer request that is still Guest. So the shop's user must exist by the time this hook
	finishes, even on the very first call (`connect`): a validly signed token proves Shopify issued it
	for this shop, and the single-store rule still applies.
	"""
	token = _request_token()
	if not token:
		return
	shop, _payload = decode_session_token(token)
	_single_store_check(shop)
	email = ensure_shop_user(shop)
	# frappe.set_user() resets the request parameters; without this every API call loses its arguments
	form_dict = frappe.local.form_dict
	frappe.set_user(email)
	frappe.local.form_dict = form_dict


# --------------------------------------------------------------------------- connect


def _single_store_check(shop):
	conn = frappe.get_single("Store Connection")
	current = _host(conn.store_url)
	if conn.enabled and current and current != shop:
		frappe.throw(
			_("This CODSync site is already connected to {0}. Multiple stores are not supported yet.").format(
				current
			),
			frappe.PermissionError,
		)
	return conn


def exchange_token(shop, session_token):
	"""Swap the session token for an offline Admin API access token (Shopify token exchange)."""
	client_id, client_secret = _app_credentials()
	resp = requests.post(
		f"https://{shop}/admin/oauth/access_token",
		json={
			"client_id": client_id,
			"client_secret": client_secret,
			"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
			"subject_token": session_token,
			"subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
			"requested_token_type": "urn:shopify:params:oauth:token-type:offline-access-token",
		},
		timeout=30,
	)
	resp.raise_for_status()
	token = (resp.json() or {}).get("access_token")
	if not token:
		frappe.throw(_("Shopify did not return an access token"))
	return token


def register_webhooks(shop, access_token, base_url, api_version):
	"""Register the order and uninstall webhooks; returns {topic: "ok" | error text}."""
	out = {}
	address = f"{base_url}/api/method/codsync.shopify_auth.webhook"
	order_address = f"{base_url}/api/method/codsync.codsync.api.webhook"
	for topic in WEBHOOK_TOPICS:
		try:
			r = requests.post(
				f"https://{shop}/admin/api/{api_version}/webhooks.json",
				headers={"X-Shopify-Access-Token": access_token},
				json={
					"webhook": {
						"topic": topic,
						"format": "json",
						"address": address if topic == "app/uninstalled" else order_address,
					}
				},
				timeout=30,
			)
			# 422 "address already taken" means it is registered already
			out[topic] = "ok" if (r.ok or r.status_code == 422) else f"HTTP {r.status_code}"
		except requests.RequestException as e:
			out[topic] = str(e)
	return out


def _base_url():
	host = frappe.conf.get("host_name") or (frappe.request.host if frappe.request else "")
	host = host.removeprefix("http://").removeprefix("https://")
	return f"https://{host}"


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep: public by design, verified by session token
def connect():
	"""First open of the embedded app: connect this shop. Safe to call on every open."""
	token = _request_token()
	if not token:
		frappe.throw(_("Missing Shopify session token"), frappe.AuthenticationError)
	shop, _payload = decode_session_token(token)
	conn = _single_store_check(shop)

	has_token = bool(conn.get_password("access_token", raise_exception=False))
	# a short-lived token from the old client-credentials setup does not count: swap it for an offline one
	offline = bool(conn.token_expiry) and get_datetime(conn.token_expiry) > add_to_date(
		now_datetime(), years=1
	)
	already = _host(conn.store_url) == shop and conn.enabled and has_token and offline
	if not already:
		access_token = exchange_token(shop, token)
		client_id, client_secret = _app_credentials()
		# write only the fields the install owns: saving the whole record would also store zeros for
		# settings it never touched (which broke the currency cache)
		frappe.db.set_single_value(
			"Store Connection",
			{
				"platform": "Shopify",
				"store_url": shop,
				"enabled": 1,
				"shopify_client_id": client_id,
				"token_expiry": add_to_date(now_datetime(), years=OFFLINE_TOKEN_YEARS),
			},
			None,
		)
		for field, value in (
			("shopify_client_secret", client_secret),
			("webhook_secret", client_secret),  # app webhooks are signed with the app secret
			("access_token", access_token),
		):
			set_encrypted_password("Store Connection", "Store Connection", value, field)
		frappe.clear_document_cache("Store Connection", "Store Connection")
		frappe.db.commit()  # nosemgrep: the install must persist even if the page request later fails
		results = register_webhooks(
			shop, access_token, _base_url(), conn.shopify_api_version or "2026-07"
		)
		_log("Success", f"Installed on {shop}", response_payload={"webhooks": results})
	email = ensure_shop_user(shop)
	return {"shop": shop, "user": email, "connected": True}


# --------------------------------------------------------------------------- webhooks


def valid_hmac(raw_body, received):
	"""True if `received` (base64) is the HMAC-SHA256 of the body under the app secret."""
	_client_id, secret = _app_credentials()
	digest = hmac.new(secret.encode("utf-8"), raw_body or b"", hashlib.sha256).digest()
	return hmac.compare_digest(base64.b64encode(digest).decode("utf-8"), received or "")


def _log(status, message, **kw):
	from codsync.codsync.synclog import log_sync

	log_sync("Shopify", "Other", status, error_message=message, **kw)


PII_FIELDS = ("customer_name", "phone", "email", "address", "city", "pincode")


def anonymise_orders(external_ids=None):
	"""Blank customer details on parcels (the given Shopify order ids, or all). Returns the number changed."""
	filters = {"external_id": ["in", list(external_ids)]} if external_ids is not None else {}
	names = frappe.get_all("COD Parcel", filters=filters, pluck="name")
	for name in names:
		frappe.db.set_value("COD Parcel", name, {f: None for f in PII_FIELDS}, update_modified=False)
	return len(names)


def revoke_shop(shop):
	"""The shop uninstalled: drop the token, stop syncing and disable its user."""
	conn = frappe.get_single("Store Connection")
	if _host(conn.store_url) == shop:
		frappe.db.set_single_value("Store Connection", {"enabled": 0, "token_expiry": None}, None)
		set_encrypted_password("Store Connection", "Store Connection", "", "access_token")
	email = shop_user(shop)
	if frappe.db.exists("User", email):
		frappe.db.set_value("User", email, "enabled", 0)


def handle_topic(topic, shop, payload):
	"""Act on a verified webhook. Returns a short result string for the log."""
	if topic == "app/uninstalled":
		revoke_shop(shop)
		return "uninstalled"
	if topic == "customers/redact":
		ids = [str(o) for o in (payload.get("orders_to_redact") or [])]
		return f"redacted {anonymise_orders(ids) if ids else 0} order(s)"
	if topic == "shop/redact":
		revoke_shop(shop)
		return f"shop data redacted ({anonymise_orders()} order(s) anonymised)"
	if topic == "customers/data_request":
		return "data request logged"
	return "ignored"


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep: public by design, verified by HMAC
def webhook():
	"""app/uninstalled and the three mandatory privacy topics. Shopify signs them with the app secret."""
	raw = frappe.request.get_data()
	if not valid_hmac(raw, frappe.get_request_header("X-Shopify-Hmac-Sha256")):
		frappe.local.response["http_status_code"] = 401
		return {"error": "Invalid signature"}
	topic = (frappe.get_request_header("X-Shopify-Topic") or "").lower()
	shop = (frappe.get_request_header("X-Shopify-Shop-Domain") or "").lower()
	if not SHOP_RE.match(shop):
		frappe.local.response["http_status_code"] = 400
		return {"error": "Bad shop"}
	try:
		payload = frappe.parse_json(raw) or {}
	except Exception:
		payload = {}
	result = handle_topic(topic, shop, payload)
	_log("Success", f"{topic} for {shop}: {result}")
	frappe.db.commit()  # nosemgrep: webhook requests are POSTs but must persist the revoke
	return {"status": "ok"}


@frappe.whitelist(allow_guest=True)  # nosemgrep: verified by session token
def whoami():
	return {"shop": verify_session_token()}
