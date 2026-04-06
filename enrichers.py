import random
import logging
from typing import Protocol

from .ai import AIService
from .models import WordData

logger = logging.getLogger("anki_language_assist")

_MAX_EXAMPLES = 5


class WordDataEnricher(Protocol):
    def enrich(self, data: WordData) -> WordData: ...


class TranslationDeduplicator:
    def __init__(self, ai_service: AIService) -> None:
        self._ai_service = ai_service

    def enrich(self, data: WordData) -> WordData:
        if data.translations:
            data.translations = self._ai_service.deduplicate_translations(data.translations)
        return data


class ExampleEnricher:
    def __init__(self, ai_service: AIService) -> None:
        self._ai_service = ai_service

    def enrich(self, data: WordData) -> WordData:
        if not data.examples:
            data.examples = self._ai_service.generate_examples(data.word)
        elif len(data.examples) > _MAX_EXAMPLES:
            data.examples = random.sample(data.examples, _MAX_EXAMPLES)
        return data
