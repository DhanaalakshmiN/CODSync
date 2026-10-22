"""Dynamic currency conversion for CODSync (order currency -> base currency).

Everything configurable lives on Store Connection (Currency section): base
currency, rate provider, URLs, cache TTL, timeout, max rate age and the
reconciliation tolerance. Nothing is hardcoded here.

get_rate flow (first hit wins):
  1. Redis cache
  2. Currency Rate row for the exact date (a Manual row always wins)
  3. live providers: the chosen one, then the others (every success is saved
     as a Currency Rate row with source API)
  4. most recent Currency Rate row within "max rate age" -> source Fallback,
     with a Sync Log warning
  5. otherwise throw (only that order fails)
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, today

from codsync.codsync.rate_providers import PROVIDERS, get_provider, provider_chain

# Used only when the Store Connection fields are still empty (before first save).
DEFAULTS = {
	"rate_provider": "Frankfurter",
	"rate_cache_seconds": 24 * 60 * 60,
	"rate_timeout_seconds": 15,
	"max_rate_age_days": 7,
	"fx_tolerance_amount": 1.0,
	"fx_tolerance_percent": 0.5,
}
FALLBACK_CACHE_SECONDS = 300  # a fallback is re-tried against the live API every 5 minutes

logger = frappe.logger("codsync_currency", allow_site=True)


def default_base_currency():
	return frappe.defaults.get_global_default("currency") or "INR"


def get_settings(conn=None):
	"""Currency settings from Store Connection, with defaults for empty fields."""
	conn = conn or frappe.get_cached_doc("Store Connection")

	def num(field, cast=cint):
		v = conn.get(field)
		return cast(v) if v not in (None, "") else DEFAULTS[field]

	from codsync.codsync.platforms.base import get_creds

	api_key = get_creds(conn).get("rate_api_key")
	return frappe._dict(
		platform=conn.get("platform"),
		base_currency=(conn.get("base_currency") or default_base_currency()).upper(),
		rate_provider=conn.get("rate_provider") or DEFAULTS["rate_provider"],
		rate_provider_url=conn.get("rate_provider_url"),
		fallback_provider_url=conn.get("fallback_rate_provider_url"),
		api_key=api_key,
		cache_seconds=num("rate_cache_seconds"),
		timeout=num("rate_timeout_seconds"),
		max_age_days=num("max_rate_age_days"),
		tolerance_amount=num("fx_tolerance_amount", flt),
		tolerance_percent=num("fx_tolerance_percent", flt),
	)


def get_base_currency(conn=None):
	return get_settings(conn).base_currency


def get_currency_precision():
	return cint(frappe.get_system_settings("currency_precision")) or 2


def is_foreign(order_currency, base_currency=None):
	"""True when the order was placed in a currency other than the base."""
	base = (base_currency or get_base_currency()).upper()
	return bool(order_currency) and order_currency.upper() != base


def fx_tolerance(expected, settings=None):
	"""Tolerance for a foreign-currency parcel: max(absolute, percent of expected)."""
	s = settings or get_settings()
	return max(flt(s.tolerance_amount), abs(flt(expected)) * flt(s.tolerance_percent) / 100)


def cache_key(from_currency, to_currency, on_date):
	return f"codsync_fx:{from_currency}:{to_currency}:{getdate(on_date)}"


def get_rate(from_currency, on_date=None, base_currency=None):
	"""Return how many base currency 1 unit of from_currency is worth on on_date."""
	return get_rate_with_source(from_currency, on_date, base_currency)[0]


def get_rate_with_source(from_currency, on_date=None, base_currency=None, settings=None):
	"""(rate, source). source is "" for the base currency, else API / Manual / Fallback."""
	s = settings or get_settings()
	to_currency = (base_currency or s.base_currency).upper()
	from_currency = (from_currency or to_currency).upper()
	if from_currency == to_currency:
		logger.debug("rate %s->%s: same currency", from_currency, to_currency)
		return 1.0, ""

	on_date = getdate(on_date or today())
	key = cache_key(from_currency, to_currency, on_date)

	cached = frappe.cache.get_value(key)
	if cached:
		logger.debug("rate %s->%s %s: cache", from_currency, to_currency, on_date)
		return flt(cached["rate"]), cached["source"]

	row = frappe.db.get_value(
		"Currency Rate",
		{"from_currency": from_currency, "to_currency": to_currency, "rate_date": on_date},
		["rate", "source"],
		as_dict=True,
	)
	if row and row.source != "Fallback":
		logger.debug("rate %s->%s %s: database (%s)", from_currency, to_currency, on_date, row.source)
		_cache(key, row.rate, row.source, s.cache_seconds)
		return flt(row.rate), row.source

	rate = _from_providers(from_currency, to_currency, on_date, s)
	if rate:
		_save_rate(from_currency, to_currency, on_date, rate)
		_cache(key, rate, "API", s.cache_seconds)
		return rate, "API"

	fb = _fallback_row(from_currency, to_currency, on_date, s.max_age_days)
	if fb:
		logger.debug("rate %s->%s %s: fallback row of %s", from_currency, to_currency, on_date, fb.rate_date)
		_warn_fallback(s, from_currency, to_currency, on_date, fb)
		_cache(key, fb.rate, "Fallback", min(FALLBACK_CACHE_SECONDS, s.cache_seconds))
		return flt(fb.rate), "Fallback"

	frappe.throw(
		_(
			"No usable {0} to {1} exchange rate for {2}: providers failed and there is no stored rate "
			"from the last {3} days. Add a Manual Currency Rate or try again later."
		).format(from_currency, to_currency, on_date, s.max_age_days),
		title=_("Exchange rate unavailable"),
	)


def convert_to_base(amount, from_currency, on_date=None, base_currency=None):
	"""(amount_in_base, rate, source), rounded to the currency precision."""
	s = get_settings()
	rate, source = get_rate_with_source(from_currency, on_date, base_currency, s)
	return flt(flt(amount) * rate, get_currency_precision()), rate, source


def convert_to_inr(amount, from_currency, on_date=None, base_currency=None):
	"""Backward-compatible (amount, rate); the target is the base currency."""
	total, rate, _source = convert_to_base(amount, from_currency, on_date, base_currency)
	return total, rate


# --------------------------------------------------------------------------- helpers


def _cache(key, rate, source, seconds):
	frappe.cache.set_value(key, {"rate": flt(rate), "source": source}, expires_in_sec=seconds)


def _from_providers(from_currency, to_currency, on_date, s):
	for i, name in enumerate(provider_chain(s.rate_provider)):
		url = s.rate_provider_url if i == 0 else s.fallback_provider_url
		provider = get_provider(name, url=url, timeout=s.timeout, api_key=s.api_key)
		try:
			rate = flt(provider.get_rate(from_currency, to_currency, str(on_date)))
		except Exception as e:
			logger.debug("rate %s->%s %s: %s failed (%s)", from_currency, to_currency, on_date, name, e)
			continue
		if rate > 0:
			logger.debug("rate %s->%s %s: %s", from_currency, to_currency, on_date, name)
			return rate
	return None


def _save_rate(from_currency, to_currency, on_date, rate):
	"""Store an API result. A failed save (duplicate, unknown Currency) never fails the lookup."""
	try:
		frappe.get_doc(
			{
				"doctype": "Currency Rate",
				"from_currency": from_currency,
				"to_currency": to_currency,
				"rate_date": on_date,
				"rate": rate,
				"source": "API",
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "CODSync save Currency Rate")


def _fallback_row(from_currency, to_currency, on_date, max_age_days):
	rows = frappe.get_all(
		"Currency Rate",
		filters={
			"from_currency": from_currency,
			"to_currency": to_currency,
			"rate_date": ["between", [add_days(on_date, -cint(max_age_days)), on_date]],
		},
		fields=["rate", "rate_date", "source"],
		order_by="rate_date desc, source desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _warn_fallback(s, from_currency, to_currency, on_date, row):
	from codsync.codsync.synclog import log_sync

	if not s.platform:
		return
	log_sync(
		s.platform,
		"Currency Rate",
		"Warning",
		error_message=(
			f"Rate providers unavailable for {from_currency} to {to_currency} on {on_date}; "
			f"used stored rate from {row.rate_date}"
		),
	)
