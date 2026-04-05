import json
import logging
from typing import Protocol

from openai import OpenAI

logger = logging.getLogger("anki_language_assist")


class AIService(Protocol):
    def deduplicate_translations(self, translations: set[str]) -> list[str]: ...
    def generate_examples(self, word: str) -> list[str]: ...


class MistralAIService:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key, base_url="https://api.mistral.ai/v1")
        self._model = model

    def _complete(self, system: str, user: str, schema_properties: dict,
                  required: list, **kwargs) -> dict:
        response = self._client.chat.completions.create(
            model=self._model,
            top_p=1,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "response_schema",
                    "schema": {
                        "type": "object",
                        "properties": schema_properties,
                        "required": required,
                    },
                },
            },
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        return json.loads(response.choices[0].message.content)

    def deduplicate_translations(self, translations: set[str]) -> list[str]:
        result = self._complete(
            system=(
                "You are an assistant specialized in deduplicating Polish word translations. "
                "Given a set of Polish words or phrases, return a clean, unique list by applying these rules:\n"
                "1. If two entries have the same or equivalent meaning, keep only the most complete or idiomatic one.\n"
                "2. If an entry is a slash-combined form (e.g. 'kłócić/spierać się'), it covers all its individual parts — remove standalone entries that are already included in it.\n"
                "3. Remove compound entries that join multiple words with commas (e.g. 'omawiać,przedstawiać,dowodzić') when all parts are already listed individually.\n"
                "4. Remove malformed fragments — entries that are clearly parsing artifacts (e.g. lone punctuation, hanging parentheses like 'przeciw)').\n"
                "5. Do not modify the spelling or structure of any kept word — only keep or delete entries from the source."
            ),
            user=str(translations),
            schema_properties={
                "translations": {
                    "type": "array",
                    "description": "The list of unique words in polish language.",
                    "items": {"type": "string"},
                }
            },
            required=["translations"],
            temperature=0,
            max_tokens=256,
        )
        return result["translations"]

    def generate_examples(self, word: str) -> list[str]:
        result = self._complete(
            system=(
                "You are an English language teacher. Generate exactly 5 natural example sentences "
                "using the provided word at B2 level. Sentences should be clear, varied in structure, "
                "and demonstrate the word's meaning in context. "
                "Return plain text only — no markdown, no bold, no asterisks, no special formatting of any kind."
            ),
            user=word,
            schema_properties={
                "examples": {
                    "type": "array",
                    "description": "List of 5 example sentences.",
                    "items": {"type": "string"},
                }
            },
            required=["examples"],
            temperature=0.7,
            max_tokens=512,
        )
        return result if isinstance(result, list) else result["examples"]
