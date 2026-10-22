"""open.er-api.com: free, no API key, about 160 currencies.

Only publishes the latest rates, so for a past date it returns today's rate.
"""

import requests

from codsync.codsync.rate_providers.base import BaseRateProvider, ProviderError


class OpenErApiProvider(BaseRateProvider):
	name = "Open ER API"
	default_url = "https://open.er-api.com/v6/latest/{base}"
	supports_history = False

	def get_rate(self, from_currency, to_currency, on_date):
		try:
			resp = requests.get(self.url.format(base=from_currency), timeout=self.timeout)
			resp.raise_for_status()
			data = resp.json()
			if data.get("result") not in (None, "success"):
				raise ValueError(data.get("error-type") or "request failed")
			rate = float(data["rates"][to_currency])
		except Exception as e:
			raise ProviderError(f"{self.name}: {e}") from e
		if rate <= 0:
			raise ProviderError(f"{self.name}: invalid rate for {from_currency}")
		return rate
