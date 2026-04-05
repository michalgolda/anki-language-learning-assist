# Anki Language Learning Assist

An Anki add-on that automatically fills card fields with data fetched from the Cambridge Dictionary and an AI model (Mistral). Designed for English → Polish vocabulary cards.

## Features

- **Editor button (LA / `Ctrl+Shift+L`)** — fetches data for the word in the Target field and fills all other fields automatically
- **Card Generator** — batch-create cards from a comma-separated word list (`Tools > Language Assist: Generate Cards`)
- **Card Export** — export cards to a plain text file with a custom format template (`Tools > Language Assist: Export Cards` or right-click selection in the Browser)

### What gets filled per word

| Field | Source |
|---|---|
| Pronunciation | Cambridge Dictionary (UK, IPA) |
| AudioURL | Cambridge Dictionary (MP3 URL) |
| Translations | Cambridge Dictionary → deduplicated via Mistral AI |
| Examples | Cambridge Dictionary examples page (AI-generated fallback at B2 level) |
| Tags | Part-of-speech tags from Cambridge Dictionary |

## Requirements

- Anki 2.1.50+ (tested on 25.x)
- A [Mistral AI](https://console.mistral.ai/) API key

## Installation

1. Clone or download this repository into your Anki add-ons folder:
   ```
   %APPDATA%\Roaming\Anki2\addons21\anki_language_learning_assist\   # Windows
   ~/Library/Application Support/Anki2/addons21/anki_language_learning_assist/  # macOS
   ~/.local/share/Anki2/addons21/anki_language_learning_assist/       # Linux
   ```

2. Install dependencies into the `vendor` folder:
   ```bash
   uv pip install -r requirements.txt --target vendor
   # or
   pip install -r requirements.txt --target vendor
   ```

3. Restart Anki.

## Configuration

Open **Tools > Add-ons**, select this add-on, and click **Config**. Available options:

| Key | Default | Description |
|---|---|---|
| `target_field_name` | `Target` | Field containing the English word to look up |
| `translations_field_name` | `Translations` | Field to fill with Polish translations |
| `pronunciation_field_name` | `Pronunciation` | Field to fill with IPA pronunciation |
| `audio_url_field_name` | `AudioURL` | Field to fill with the audio file URL |
| `examples_field_name` | `Examples` | Field to fill with example sentences (HTML list) |
| `mistral_api_key` | _(empty)_ | Your Mistral AI API key |
| `mistral_model` | `ministral-8b-latest` | Mistral model to use |

## Export format

The export dialog accepts a template string with `{{FieldName}}` placeholders, e.g.:

```
{{Target}} {{Pronunciation}} - {{Translations}}
```

Cards are separated by a blank line. HTML is stripped from field values automatically.
