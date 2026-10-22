"""Frankfurter (ECB reference rates): free, no API key, about 30 currencies."""

import requests

from codsync.codsync.rate_providers.base import BaseRateProvider, ProviderError


class FrankfurterProvider(BaseRateProvider):
	name = "Frankfurter"
	default_url = "https://api.frankfurter.dev/v1/{date}"

	def get_rate(self, from_currency, to_currency, on_date):
		try:
			resp = requests.get(
				self.url.format(date=on_date),
				params={"base": from_currency, "symbols": to_currency},
				timeout=self.timeout,
			)
			resp.raise_for_status()
			rate = float(resp.json()["rates"][to_currency])
		except Exception as e:
			raise ProviderError(f"{self.name}: {e}") from e
		if rate <= 0:
			raise ProviderError(f"{self.name}: invalid rate for {from_currency}")
		return rate
