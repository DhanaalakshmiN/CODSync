"""Shopify adapter: webhook HMAC verification and order payload mapping."""

import base64
import hashlib
import hmac
import time

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime
from frappe.utils.password import set_encrypted_password

from codsync.codsync.platforms.base import BasePlatform, get_creds
from codsync.codsync.currency import convert_to_base, get_base_currency
from codsync.codsync.synclog import log_sync


class ShopifyPlatform(BasePlatform):
	name = "Shopify"

	def verify_webhook(self, headers, raw_body, conn):
		domain = (headers.get("X-Shopify-Shop-Domain") or "").strip().lower()
		if not domain or domain != (conn.store_url or "").strip().lower():
			return False
		secret = get_creds(conn).get("webhook_secret") or ""
		if not secret:
			return False
		received = headers.get("X-Shopify-Hmac-Sha256") or ""
		digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
		return hmac.compare_digest(base64.b64encode(digest).decode("utf-8"), received)

	def parse_order(self, payload, conn):
		order_id = payload.get("name") or payload.get("order_number") or payload.get("id") or ""
		if not order_id:
			# surface what Shopify actually returned so the mapping can be fixed
			frappe.throw(
				_("Shopify order has no name / order_number / id. Fields returned: {0}").format(
					", ".join(sorted(payload)) or "(none)"
				)
			)
		gateways = payload.get("payment_gateway_names") or []
		tags = payload.get("tags") or ""
		cod_keyword = (conn.get("cod_keyword") or "cash on delivery").lower()
		cod_tag = conn.get("cod_tag") or "COD"
		is_cod = any(cod_keyword in (g or "").lower() for g in gateways)
		if not is_cod:
			is_cod = cod_tag.lower() in (tags or "").lower()

		fulfillments = payload.get("fulfillments") or []
		awb = tracking_company = None
		for f in fulfillments:
			number = (f.get("tracking_number") or "").strip()
			if number:
				awb = "".join(number.split()).upper()
				tracking_company = (f.get("tracking_company") or "").strip()
				break

		addr = payload.get("shipping_address") or {}
		customer = payload.get("customer") or {}
		original = flt(payload.get("total_price") or 0)
		base_currency = get_base_currency(conn)
		currency = (payload.get("currency") or base_currency).upper()
		created = payload.get("created_at")
		total, rate, rate_source = convert_to_base(
			original, currency, get_datetime(created).date() if created else None, base_currency
		)
		cancelled = bool(payload.get("cancelled_at"))
		fulfilled = payload.get("fulfillment_status") == "fulfilled" or bool(fulfillments)

		values = {
			"order_id": str(order_id),
			"platform": "Shopify",
			"external_id": str(payload.get("id") or ""),
			"customer_name": addr.get("name")
			or (f"{customer.get('first_name') or ''} {customer.get('last_name') or ''}".strip()),
			"phone": addr.get("phone") or customer.get("phone") or "",
			"email": payload.get("email") or customer.get("email") or "",
			"address": ", ".join(x for x in (addr.get("address1"), addr.get("address2")) if x),
			"city": addr.get("city") or "",
			"pincode": addr.get("zip") or "",
			"payment_mode": "COD" if is_cod else "Prepaid",
			"order_total": total,
			"order_currency": currency,
			"original_amount": original,
			"exchange_rate": rate,
			"rate_source": rate_source,
			"cod_amount": total if is_cod else 0,
			"order_status": "Cancelled" if cancelled else ("Fulfilled" if fulfilled else "Unfulfilled"),
			# helper keys applied by the caller, not COD Parcel fields
			"awb": awb,
			"tracking_company": tracking_company,
			"declared_weight": sum(
				flt(li.get("grams")) * (flt(li.get("quantity")) or 1)
				for li in (payload.get("line_items") or [])
			)
			/ 1000,
		}
		if payload.get("created_at"):
			values["order_date"] = get_datetime(payload["created_at"]).replace(tzinfo=None)
		return values

	def get_token(self, conn):
		"""Cached client-credentials access token; refreshed when expired."""
		expiry = conn.get("token_expiry")
		cached = conn.get_password("access_token", raise_exception=False)
		if cached and expiry and get_datetime(expiry) > add_to_date(now_datetime(), minutes=1):
			return cached
		creds = get_creds(conn)
		if not (conn.get("store_url") and creds.get("client_id") and creds.get("client_secret")):
			frappe.throw(_("Store URL, Client ID and Client Secret are required"))
		resp = requests.post(
			f"https://{conn.store_url.strip()}/admin/oauth/access_token",
			data={
				"grant_type": "client_credentials",
				"client_id": creds["client_id"],
				"client_secret": creds["client_secret"],
			},
			timeout=30,
		)
		resp.raise_for_status()
		data = resp.json()
		token = data.get("access_token")
		if not token:
			frappe.throw(_("Shopify did not return an access token"))
		expires_at = add_to_date(now_datetime(), seconds=cint(data.get("expires_in") or 86399))
		set_encrypted_password("Store Connection", "Store Connection", token, "access_token")
		frappe.db.set_single_value("Store Connection", "token_expiry", expires_at)
		return token

	def _get(self, conn, url, _retry=True):
		resp = requests.get(url, headers={"X-Shopify-Access-Token": self.get_token(conn)}, timeout=60)
		if resp.status_code in (401, 403) and _retry:
			# cached token may predate a scope change: drop it and retry once with a fresh one
			frappe.db.set_single_value("Store Connection", "token_expiry", None)
			conn.token_expiry = None
			return self._get(conn, url, _retry=False)
		if not resp.ok:
			detail = (resp.text or "")[:300]
			raise requests.HTTPError(f"{resp.status_code} from Shopify: {detail}", response=resp)
		return resp

	def test_connection(self, conn):
		started = time.time()
		endpoint = f"https://{(conn.get('store_url') or '').strip()}/admin/oauth/access_token"
		status = None
		try:
			self.get_token(conn)
			version = get_creds(conn)["api_version"]
			endpoint = f"https://{(conn.get('store_url') or '').strip()}/admin/api/{version}/shop.json"
			resp = self._get(conn, endpoint)
			shop = resp.json().get("shop") or {}
			ok, message, status = True, f"Connected to {shop.get('name') or conn.store_url}", resp.status_code
		except Exception as e:
			ok, message = False, str(e)
			status = getattr(getattr(e, "response", None), "status_code", None)
		frappe.db.set_single_value(
			"Store Connection",
			{"last_test_status": "Success" if ok else "Failed", "last_tested_on": now_datetime()},
		)
		log_sync(
			"Shopify",
			"Test Connection",
			"Success" if ok else "Failed",
			error_message=None if ok else message,
			http_status=status,
			endpoint=endpoint,
			duration_ms=int((time.time() - started) * 1000),
			response_payload={"message": message},
		)
		return ok, message

	def fetch_orders(self, conn):
		"""Pull all orders (Link-header pagination); upsert COD orders as COD Parcels."""
		from codsync.codsync.api import _upsert_order

		started = time.time()
		counts = {"fetched": 0, "cod": 0, "created": 0, "updated": 0, "skipped": 0, "failed": 0}
		version = get_creds(conn)["api_version"]
		url = f"https://{conn.store_url.strip()}/admin/api/{version}/orders.json?status=any&limit=250"
		endpoint, error, status = url, None, None
		try:
			while url:
				resp = self._get(conn, url)
				for order in resp.json().get("orders") or []:
					counts["fetched"] += 1
					try:
						values = self.parse_order(order, conn)
						if values.get("payment_mode") != "COD":
							counts["skipped"] += 1
							continue
						counts["cod"] += 1
						existing = frappe.db.get_value("COD Parcel", {"external_id": values["external_id"]})
						if existing:
							values["order_id"] = existing
						_upsert_order(values, conn)
						counts["updated" if existing else "created"] += 1
					except Exception as e:
						counts["failed"] += 1
						frappe.log_error(frappe.get_traceback(), "CODSync fetch_orders")
						# keys only, never order data, so the cause is visible without leaking PII
						log_sync(
							"Shopify",
							"Order Sync",
							"Failed",
							error_message="Order {}: {}".format(
								order.get("name") or order.get("order_number") or order.get("id") or "?", e
							),
							response_payload={"payload_keys": sorted(order)},
						)
				url = resp.links.get("next", {}).get("url")
		except Exception as e:
			error = str(e)
			status = getattr(getattr(e, "response", None), "status_code", None)
		frappe.db.set_single_value("Store Connection", "last_synced_on", now_datetime())
		log_sync(
			"Shopify",
			"Order Sync",
			"Failed" if error or counts["failed"] else "Success",
			error_message=error or (f"{counts['failed']} orders failed" if counts["failed"] else None),
			http_status=status,
			endpoint=endpoint,
			duration_ms=int((time.time() - started) * 1000),
			response_payload=counts,
		)
		if error:
			frappe.throw(error)
		return counts

	def order_url(self, external_id, conn):
		# canonical admin URL: admin.shopify.com/store/<handle>/orders/<numeric id>
		host = (conn.get("store_url") or "").strip().lower().removeprefix("https://").removeprefix("http://")
		handle = host.split("/")[0].removesuffix(".myshopify.com")
		if external_id and handle:
			return f"https://admin.shopify.com/store/{handle}/orders/{external_id}"
		return None
