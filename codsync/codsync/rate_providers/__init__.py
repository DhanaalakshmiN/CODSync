"""Rate provider registry (same connector pattern as platforms/).

Adding a provider = one file here + its option on Store Connection.rate_provider.
"Manual" is not a provider: it means "use only Currency Rate rows".
"""

from codsync.codsync.rate_providers.base import BaseRateProvider, ProviderError
from codsync.codsync.rate_providers.frankfurter import FrankfurterProvider
from codsync.codsync.rate_providers.open_er_api import OpenErApiProvider

PROVIDERS = {cls.name: cls for cls in (FrankfurterProvider, OpenErApiProvider)}
MANUAL = "Manual"


def provider_chain(primary):
	"""Provider names to try in order: the chosen one first, then the others."""
	if primary == MANUAL:
		return []
	first = primary if primary in PROVIDERS else FrankfurterProvider.name
	return [first] + [n for n in PROVIDERS if n != first]


def get_provider(name, **kwargs):
	return PROVIDERS[name](**kwargs)
