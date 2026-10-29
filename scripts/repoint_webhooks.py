#!/usr/bin/env python3
"""Point Shopify webhooks + site host_name at a (new) public URL.

Use after restarting a temporary tunnel (trycloudflare gives a new URL each run):
    cloudflared tunnel --url http://localhost:8000        # terminal 1
    ../env/bin/python scripts/repoint_webhooks.py https://<new-host>.trycloudflare.com

Checks the URL answers /api/method/ping before switching anything.
Idempotent: safe to run repeatedly.
"""

import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[3]  # .../frappe-bench
SITE = sys.argv[2] if len(sys.argv) > 2 else "codsync.localhost"
ORDER_PATH = "/api/method/codsync.codsync.api.webhook"
LIFE_PATH = "/api/method/codsync.shopify_auth.webhook"
TOPICS = {
	"orders/create": ORDER_PATH,
	"orders/updated": ORDER_PATH,
	"orders/cancelled": ORDER_PATH,
	"app/uninstalled": LIFE_PATH,
}


def main():
	if len(sys.argv) < 2 or not sys.argv[1].startswith("https://"):
		sys.exit(f"usage: {sys.argv[0]} https://<public-host> [site]")
	base = sys.argv[1].rstrip("/")

	import requests

	try:
		r = requests.get(base + "/api/method/ping", timeout=20)
		if r.status_code != 200:
			raise RuntimeError(f"HTTP {r.status_code}")
	except Exception as e:
		sys.exit(f"{base} did not answer /api/method/ping ({e}) - not switching webhooks to a dead URL")

	sys.path.insert(0, str(BENCH / "apps" / "codsync"))
	sys.path.insert(0, str(BENCH / "apps" / "frappe"))
	import os

	os.chdir(str(BENCH / "sites"))  # frappe.init resolves the site dir relative to cwd/. 
	import frappe
	import requests as rq
	from frappe.utils.password import get_decrypted_password

	frappe.init(site=SITE, sites_path=".")
	frappe.connect()
	from frappe.installer import update_site_config

	update_site_config("host_name", base)

	shop = frappe.db.get_single_value("Store Connection", "store_url")
	version = frappe.db.get_single_value("Store Connection", "shopify_api_version") or "2026-10"
	token = get_decrypted_password("Store Connection", "Store Connection", "access_token")
	if not (shop and token):
		sys.exit("Store Connection has no shop/access token - connect the store first")
	headers = {"X-Shopify-Access-Token": token}

	resp = rq.get(f"https://{shop}/admin/api/{version}/webhooks.json?limit=50", headers=headers, timeout=30)
	resp.raise_for_status()
	existing = {w["topic"]: w["id"] for w in (resp.json().get("webhooks") or [])}

	for topic, path in TOPICS.items():
		address = base + path
		if topic in existing:
			r = rq.put(
				f"https://{shop}/admin/api/{version}/webhooks/{existing[topic]}.json",
				headers=headers,
				json={"webhook": {"id": existing[topic], "address": address}},
				timeout=30,
			)
			print(f"{topic}: {'updated -> ' + address if r.ok else 'FAILED ' + str(r.status_code)}")
		else:
			r = rq.post(
				f"https://{shop}/admin/api/{version}/webhooks.json",
				headers=headers,
				json={"webhook": {"topic": topic, "format": "json", "address": address}},
				timeout=30,
			)
			print(f"{topic}: {'created -> ' + address if r.ok else 'FAILED ' + str(r.status_code)}")
	frappe.destroy()
	print(f"host_name set to {base}. Done.")
	# reminder: the embedded app URL in Shopify Partner Dashboard (App setup) must be
	# {base}/shopify_app - that one cannot be changed programmatically.


if __name__ == "__main__":
	main()
