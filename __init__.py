import sys
import os
import logging
import threading

logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("anki_language_assist")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

from aqt import gui_hooks, mw
from aqt.qt import QAction

from .ai import MistralAIService
from .dialogs import CardExportDialog, CardGeneratorDialog, apply_data_to_note
from .enrichers import ExampleEnricher, TranslationDeduplicator
from .fetcher import WordDataFetcher
from .providers import CambridgeDictionaryProvider, DikiDictionaryProvider, ProviderChain

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

config = mw.addonManager.getConfig(__name__)
target_field_name: str = config.get("target_field_name", "Target")
translations_field_name: str = config.get("translations_field_name", "Translations")
pronunciation_field_name: str = config.get("pronunciation_field_name", "Pronunciation")
audio_url_field_name: str = config.get("audio_url_field_name", "AudioURL")
examples_field_name: str = config.get("examples_field_name", "Examples")

_FIELD_NAMES = {
    "target": target_field_name,
    "pronunciation_field": pronunciation_field_name,
    "audio_url_field": audio_url_field_name,
    "translations_field": translations_field_name,
    "examples_field": examples_field_name,
}

_DEFAULT_EXPORT_FORMAT = (
    f"{{{{{target_field_name}}}}} "
    f"{{{{{pronunciation_field_name}}}}} - "
    f"{{{{{translations_field_name}}}}}"
)

# ---------------------------------------------------------------------------
# Composition root — wire dependencies
# ---------------------------------------------------------------------------

_ai = MistralAIService(
    api_key=config.get("mistral_api_key", ""),
    model=config.get("mistral_model", "ministral-8b-latest"),
)

_fetcher = WordDataFetcher(
    provider=ProviderChain([CambridgeDictionaryProvider(), DikiDictionaryProvider()]),
    enrichers=[TranslationDeduplicator(_ai), ExampleEnricher(_ai)],
)

_current_editor = None

# ---------------------------------------------------------------------------
# Editor integration
# ---------------------------------------------------------------------------

def _fill_note(note, query: str) -> None:
    data = _fetcher.fetch(query)

    def update_note() -> None:
        apply_data_to_note(note, data, pronunciation_field_name,
                           audio_url_field_name, translations_field_name, examples_field_name)
        if note.id:
            mw.col.update_note(note)
        if _current_editor:
            _current_editor.loadNote()

    mw.taskman.run_on_main(update_note)


def _on_editor_button(editor) -> None:
    note = editor.note
    if target_field_name not in note.keys():
        return
    value = note[target_field_name].strip()
    if not value:
        return
    threading.Thread(target=_fill_note, args=(note, value), daemon=True).start()


def _add_editor_button(buttons, editor) -> None:
    buttons.append(editor.addButton(
        icon=None,
        cmd="language_assist",
        func=_on_editor_button,
        tip="Language Assist (Ctrl+Shift+L)",
        label="LA",
        keys="Ctrl+Shift+L",
        disables=False,
    ))


def _on_editor_load(editor) -> None:
    global _current_editor
    _current_editor = editor


# ---------------------------------------------------------------------------
# Menu & hooks
# ---------------------------------------------------------------------------

def _setup_menu() -> None:
    generate_action = QAction("Language Assist: Generate Cards", mw)
    generate_action.triggered.connect(
        lambda: CardGeneratorDialog(_fetcher, _FIELD_NAMES, mw).exec()
    )
    mw.form.menuTools.addAction(generate_action)

    export_action = QAction("Language Assist: Export Cards", mw)
    export_action.triggered.connect(
        lambda: CardExportDialog(_DEFAULT_EXPORT_FORMAT, parent=mw).exec()
    )
    mw.form.menuTools.addAction(export_action)


def _on_browser_context_menu(browser, menu) -> None:
    note_ids = list(dict.fromkeys(mw.col.get_card(cid).nid for cid in browser.selected_cards()))
    if not note_ids:
        return
    action = menu.addAction("Language Assist: Export Selected")
    action.triggered.connect(
        lambda: CardExportDialog(_DEFAULT_EXPORT_FORMAT, note_ids, mw).exec()
    )


gui_hooks.editor_did_load_note.append(_on_editor_load)
gui_hooks.editor_did_init_buttons.append(_add_editor_button)
gui_hooks.main_window_did_init.append(_setup_menu)
gui_hooks.browser_will_show_context_menu.append(_on_browser_context_menu)
