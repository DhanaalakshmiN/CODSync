"""Rate provider contract.

A provider answers one question: how many `to_currency` is 1 `from_currency`
worth on a date. Providers never touch the database or cache (currency.py
does); they raise ProviderError when they cannot answer, so the caller can
try the next provider.
"""


class ProviderError(Exception):
	"""The provider failed or does not support the requested currency."""


class BaseRateProvider:
	name = None
	default_url = None
	supports_history = True

	def __init__(self, url=None, timeout=15, api_key=None):
		self.url = (url or self.default_url or "").strip()
		self.timeout = timeout
		self.api_key = api_key

	def get_rate(self, from_currency, to_currency, on_date):
		raise NotImplementedError
