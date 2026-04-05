# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Anki add-on for English → Polish vocabulary card automation. Scrapes Cambridge Dictionary and calls Mistral AI to fill card fields. Lives in `%APPDATA%\Roaming\Anki2\addons21\anki_language_learning_assist\`.

## Development Setup

- No virtualenv — the add-on runs inside Anki's bundled Python (CPython 3.13).
- Third-party libraries are vendored in `vendor/`. Install with:
  ```bash
  uv pip install -r requirements.txt --target vendor
  ```
- To test changes: restart Anki, or use **Tools > Add-ons > Debug Console** (`Ctrl+Shift+;`) for light reloads (`aqt.mw.reset()`).
- Enable debug logging in the console: `import logging; logging.getLogger("anki_language_assist").setLevel(logging.DEBUG)`

## Architecture

Single-file add-on (`__init__.py`) divided into sections:

### AI (`_ai_complete`, `generate_examples`, `deduplicate_translations`)
Uses the OpenAI-compatible client pointed at `https://api.mistral.ai/v1`. All AI calls go through `_ai_complete()` which enforces structured JSON output via `json_schema` response format.

### Scraping (`extract_*` functions)
`curl_cffi` with `impersonate="chrome"` fetches Cambridge Dictionary pages. `selectolax` parses HTML. Three URLs are used:
- `dictionary/english-polish/{word}` — primary (translations, pronunciation, audio)
- `dictionary/english/{word}` — fallback if pronunciation missing
- `example/english/{word}` — separate static page for example sentences

### Word data (`fetch_word_data`, `_apply_data_to_note`)
`fetch_word_data(query)` returns a dict with all extracted/generated data. `_apply_data_to_note(note, data)` writes it to note fields — shared by both the editor flow and the card generator.

### Editor integration
`editor_did_load_note` captures the current editor reference. `editor_did_init_buttons` adds the **LA** button. On click, `fetch_dictionary(note, query)` runs in a daemon thread; field updates are marshalled back to the main thread via `mw.taskman.run_on_main`.

### Dialogs
- `CardGeneratorDialog` — batch creates notes from a word list into a selected deck/note type
- `CardExportDialog` — exports notes to a `.txt` file using a `{{FieldName}}` template; supports deck-wide or browser-selection scope, filterable by card type

### Key Anki APIs used
- `mw.addonManager.getConfig(__name__)` — config
- `mw.col.update_note` / `mw.col.add_note` / `mw.col.get_note` — note CRUD
- `mw.col.find_notes(query)` — search using Anki's search syntax
- `mw.taskman.run_on_main(fn)` — schedule work on the Qt main thread
- `gui_hooks.*` — all event wiring at the bottom of the file
