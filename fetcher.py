import random
import logging

from .ai import AIService
from .models import WordData
from .providers import DictionaryProvider

logger = logging.getLogger("anki_language_assist")

_MAX_EXAMPLES = 5


class WordDataFetcher:
    def __init__(self, provider: DictionaryProvider, ai_service: AIService) -> None:
        self._provider = provider
        self._ai_service = ai_service

    def fetch(self, word: str) -> WordData:
        data = self._provider.fetch(word)

        if data.translations:
            data.translations = self._ai_service.deduplicate_translations(data.translations)

        if not data.examples:
            data.examples = self._ai_service.generate_examples(word)
        elif len(data.examples) > _MAX_EXAMPLES:
            data.examples = random.sample(data.examples, _MAX_EXAMPLES)

        logger.debug("fetched: %s", data)
        return data
