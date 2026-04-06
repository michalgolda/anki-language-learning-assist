import logging

from .enrichers import WordDataEnricher
from .models import WordData
from .providers import DictionaryProvider

logger = logging.getLogger("anki_language_assist")


class WordDataFetcher:
    def __init__(self, provider: DictionaryProvider, enrichers: list[WordDataEnricher]) -> None:
        self._provider = provider
        self._enrichers = enrichers

    def fetch(self, word: str) -> WordData:
        data = self._provider.fetch(word)
        for enricher in self._enrichers:
            data = enricher.enrich(data)
        logger.debug("fetched: %s", data)
        return data
