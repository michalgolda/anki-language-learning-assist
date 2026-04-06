import logging
from typing import Protocol

from curl_cffi import requests as cffi_requests
from selectolax.parser import HTMLParser

from .models import WordData

logger = logging.getLogger("anki_language_assist")


def _http_get(url: str) -> str:
    return cffi_requests.get(url, impersonate="chrome").text


class DictionaryProvider(Protocol):
    def fetch(self, word: str) -> WordData: ...


class NoProviderAvailableError(Exception):
    pass


class ProviderChain:
    def __init__(self, providers: list[DictionaryProvider]) -> None:
        if not providers:
            raise ValueError("ProviderChain requires at least one provider")
        self._providers = providers

    def fetch(self, word: str) -> WordData:
        errors: list[Exception] = []
        for provider in self._providers:
            try:
                return provider.fetch(word)
            except Exception as e:
                logger.warning("%s failed for '%s': %s", type(provider).__name__, word, e)
                errors.append(e)
        raise NoProviderAvailableError(
            f"All providers failed for '{word}': {[str(e) for e in errors]}"
        )


class CambridgeDictionaryProvider:
    _BASE_URL = "https://dictionary.cambridge.org/dictionary/english-polish"
    _FALLBACK_URL = "https://dictionary.cambridge.org/dictionary/english"
    _EXAMPLES_URL = "https://dictionary.cambridge.org/example/english"
    _HOST = "https://dictionary.cambridge.org"

    def _extract_pronunciation(self, html: str) -> str | None:
        node = HTMLParser(html).css_first("span.pron.dpron > span")
        return node.text(strip=True) if node else None

    def _extract_audio_url(self, html: str) -> str | None:
        node = HTMLParser(html).css_first("#audio1 > source:nth-child(2)")
        src = node.attrs.get("src") if node else None
        return f"{self._HOST}{src}" if src else None

    def _extract_translations(self, html: str) -> list[str]:
        tree = HTMLParser(html)
        for node in tree.css("div.phrase-block"):
            node.decompose()
        nodes = tree.css("span.trans[lang='pl'], div.tc-bb.tb.lpb-25[lang='pl']")
        return [node.text(strip=True).rstrip("…") for node in nodes]

    def _extract_tags(self, html: str) -> set[str]:
        nodes = HTMLParser(html).css("div.posgram > span.pos")
        return {node.text(strip=True) for node in nodes}

    def _extract_examples(self, html: str) -> list[str]:
        nodes = HTMLParser(html).css("#entryContent > div.degs > div > div > span")
        return [node.text(strip=True) for node in nodes]

    def fetch(self, word: str) -> WordData:
        logger.debug("CambridgeDictionaryProvider fetching: %s", word)
        html = _http_get(f"{self._BASE_URL}/{word}")
        pronunciation = self._extract_pronunciation(html)
        if pronunciation is None:
            html = _http_get(f"{self._FALLBACK_URL}/{word}")
            pronunciation = self._extract_pronunciation(html)
        return WordData(
            word=word,
            pronunciation=pronunciation,
            audio_url=self._extract_audio_url(html),
            translations=self._extract_translations(html),
            tags=self._extract_tags(html),
            examples=self._extract_examples(_http_get(f"{self._EXAMPLES_URL}/{word}")),
        )


class DikiDictionaryProvider:
    _BASE_URL = "https://www.diki.pl/slownik-angielskiego"

    def fetch(self, word: str) -> WordData:
        logger.debug("DikiDictionaryProvider fetching: %s", word)
        html = _http_get(f"{self._BASE_URL}?q={word}")
        nodes = HTMLParser(html).css("ol.foreignToNativeMeanings > li > span")
        translations = [node.text(strip=True) for node in nodes if node.text(strip=True)]
        return WordData(word=word, translations=translations)
