import sys
import os
import json
import logging
import random
import threading

logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("anki_language_assist")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

from curl_cffi import requests as cffi_requests
from selectolax.parser import HTMLParser
from openai import OpenAI
from aqt import gui_hooks, mw
from aqt.qt import (
    QAction, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QLineEdit, QComboBox, QPushButton,
    QProgressBar, QMessageBox, QFileDialog, QCheckBox,
)

config = mw.addonManager.getConfig(__name__)
target_field_name: str = config.get("target_field_name", "Target")
translations_field_name: str = config.get("translations_field_name", "Translations")
pronunciation_field_name: str = config.get("pronunciation_field_name", "Pronunciation")
audio_url_field_name: str = config.get("audio_url_field_name", "AudioURL")
examples_field_name: str = config.get("examples_field_name", "Examples")
mistral_api_key: str = config.get("mistral_api_key", "")
mistral_model: str = config.get("mistral_model", "ministral-8b-latest")

_BASE_URL = "https://dictionary.cambridge.org/dictionary/english-polish"
_FALLBACK_URL = "https://dictionary.cambridge.org/dictionary/english"
_EXAMPLES_URL = "https://dictionary.cambridge.org/example/english"

_ai_client = OpenAI(api_key=mistral_api_key, base_url="https://api.mistral.ai/v1")
_current_editor = None


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------

def _ai_complete(system: str, user: str, schema_properties: dict, required: list, **kwargs) -> dict:
    response = _ai_client.chat.completions.create(
        model=mistral_model,
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


def generate_examples(word: str) -> list[str]:
    result = _ai_complete(
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


def deduplicate_translations(translations: set[str]) -> list[str]:
    result = _ai_complete(
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


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def _get(url: str) -> str:
    return cffi_requests.get(url, impersonate="chrome").text


def extract_pronunciation(html: str) -> str | None:
    node = HTMLParser(html).css_first("span.pron.dpron > span")
    return node.text(strip=True) if node else None


def extract_audio_src(html: str) -> str | None:
    node = HTMLParser(html).css_first("#audio1 > source:nth-child(2)")
    src = node.attrs.get("src") if node else None
    return f"https://dictionary.cambridge.org{src}" if src else None


def extract_translations(html: str) -> set[str]:
    tree = HTMLParser(html)
    for node in tree.css("div.phrase-block"):
        node.decompose()
    nodes = tree.css("span.trans[lang='pl'], div.tc-bb.tb.lpb-25[lang='pl']")
    return {node.text(strip=True).rstrip("…") for node in nodes}


def extract_tags(html: str) -> set[str]:
    nodes = HTMLParser(html).css("div.posgram > span.pos")
    return {node.text(strip=True) for node in nodes}


def extract_examples(html: str) -> list[str]:
    nodes = HTMLParser(html).css("#entryContent > div.degs > div > div > span")
    return [node.text(strip=True) for node in nodes]


# ---------------------------------------------------------------------------
# Word data
# ---------------------------------------------------------------------------

def fetch_word_data(query: str) -> dict:
    logger.debug("fetching: %s", query)
    html = _get(f"{_BASE_URL}/{query}")
    pronunciation = extract_pronunciation(html)
    if pronunciation is None:
        html = _get(f"{_FALLBACK_URL}/{query}")
        pronunciation = extract_pronunciation(html)
    audio_src = extract_audio_src(html)
    raw_translations = extract_translations(html)
    translations = deduplicate_translations(raw_translations) if raw_translations else []
    tags = extract_tags(html)
    examples = extract_examples(_get(f"{_EXAMPLES_URL}/{query}"))
    if not examples:
        examples = generate_examples(query)
    elif len(examples) > 5:
        examples = random.sample(examples, 5)
    logger.debug("pronunciation: %s | audio: %s | translations: %s | tags: %s | examples: %s",
                 pronunciation, audio_src, translations, tags, examples)
    return {
        "pronunciation": pronunciation,
        "audio_src": audio_src,
        "translations": translations,
        "tags": tags,
        "examples": examples,
    }


def _set_note_field(note, field_name: str, value: str) -> None:
    if field_name in note.keys():
        note[field_name] = value


def _apply_data_to_note(note, data: dict) -> None:
    pronunciation = data["pronunciation"]
    examples_html = "<ul>" + "".join(f"<li>{e}</li>" for e in data["examples"]) + "</ul>"
    sanitized_tags = {t.replace(" ", "_") for t in data["tags"] if t}
    _set_note_field(note, pronunciation_field_name, f"/{pronunciation}/" if pronunciation else "")
    _set_note_field(note, audio_url_field_name, data["audio_src"] or "")
    _set_note_field(note, translations_field_name, ", ".join(data["translations"]))
    _set_note_field(note, examples_field_name, examples_html)
    note.tags = list(sanitized_tags)
    logger.debug("tags applied: %s", sanitized_tags)


# ---------------------------------------------------------------------------
# Editor integration
# ---------------------------------------------------------------------------

def fetch_dictionary(note, query: str) -> None:
    data = fetch_word_data(query)

    def update_note() -> None:
        _apply_data_to_note(note, data)
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
    threading.Thread(target=fetch_dictionary, args=(note, value), daemon=True).start()


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
# Card generator dialog
# ---------------------------------------------------------------------------

def _generate_cards(words: list[str], deck_name: str, notetype_name: str,
                    on_progress, on_done) -> None:
    notetype = mw.col.models.by_name(notetype_name)
    deck_id = mw.col.decks.id(deck_name)
    for i, word in enumerate(words, 1):
        mw.taskman.run_on_main(lambda w=word, idx=i: on_progress(idx, w))
        try:
            data = fetch_word_data(word)
            def add_note(w=word, d=data) -> None:
                note = mw.col.new_note(notetype)
                _set_note_field(note, target_field_name, w)
                _apply_data_to_note(note, d)
                mw.col.add_note(note, deck_id)
            mw.taskman.run_on_main(add_note)
        except Exception as e:
            logger.error("failed to generate card for '%s': %s", word, e)
    mw.taskman.run_on_main(on_done)


class CardGeneratorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Language Assist — Generate Cards")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Words (comma-separated):"))
        self._words_input = QTextEdit()
        self._words_input.setPlaceholderText("doom, thrive, resilience")
        self._words_input.setFixedHeight(80)
        layout.addWidget(self._words_input)

        deck_row = QHBoxLayout()
        deck_row.addWidget(QLabel("Deck:"))
        self._deck_combo = QComboBox()
        for deck in sorted(mw.col.decks.all_names_and_ids(), key=lambda d: d.name):
            self._deck_combo.addItem(deck.name)
        deck_row.addWidget(self._deck_combo)
        layout.addLayout(deck_row)

        notetype_row = QHBoxLayout()
        notetype_row.addWidget(QLabel("Note type:"))
        self._notetype_combo = QComboBox()
        for nt in sorted(mw.col.models.all_names_and_ids(), key=lambda m: m.name):
            self._notetype_combo.addItem(nt.name)
        notetype_row.addWidget(self._notetype_combo)
        layout.addLayout(notetype_row)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status = QLabel("")
        layout.addWidget(self._status)

        self._generate_btn = QPushButton("Generate")
        self._generate_btn.clicked.connect(self._on_generate)
        layout.addWidget(self._generate_btn)

    def _on_generate(self) -> None:
        words = [w.strip() for w in self._words_input.toPlainText().split(",") if w.strip()]
        if not words:
            return
        deck_name = self._deck_combo.currentText()
        notetype_name = self._notetype_combo.currentText()

        self._generate_btn.setEnabled(False)
        self._progress.setMaximum(len(words))
        self._progress.setValue(0)
        self._progress.setVisible(True)

        def on_progress(idx: int, word: str) -> None:
            self._progress.setValue(idx)
            self._status.setText(f"Processing: {word} ({idx}/{len(words)})")

        def on_done() -> None:
            self.accept()
            QMessageBox.information(mw, "Language Assist",
                                    f"Successfully added {len(words)} card(s) to '{deck_name}'.")

        threading.Thread(
            target=_generate_cards,
            args=(words, deck_name, notetype_name, on_progress, on_done),
            daemon=True,
        ).start()


# ---------------------------------------------------------------------------
# Card export dialog
# ---------------------------------------------------------------------------

_DEFAULT_EXPORT_FORMAT = (
    f"{{{{{target_field_name}}}}} "
    f"{{{{{pronunciation_field_name}}}}} - "
    f"{{{{{translations_field_name}}}}}"
)


def _format_note(note, template: str) -> str:
    result = template
    for key in note.keys():
        value = HTMLParser(note[key]).text(strip=True) if note[key] else ""
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def _export_notes(notes, template: str, path: str) -> int:
    lines = [_format_note(n, template) for n in notes if _format_note(n, template).strip()]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(lines))
    return len(lines)


class CardExportDialog(QDialog):
    def __init__(self, selected_note_ids: list[int] | None = None, parent=None):
        super().__init__(parent)
        self._selected_note_ids = selected_note_ids or []
        self.setWindowTitle("Language Assist — Export Cards")
        self.setMinimumWidth(480)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        if self._selected_note_ids:
            self._scope_check = QCheckBox(f"Export selected ({len(self._selected_note_ids)}) cards only")
            self._scope_check.setChecked(True)
            layout.addWidget(self._scope_check)
        else:
            self._scope_check = None

        deck_row = QHBoxLayout()
        deck_row.addWidget(QLabel("Deck:"))
        self._deck_combo = QComboBox()
        for deck in sorted(mw.col.decks.all_names_and_ids(), key=lambda d: d.name):
            self._deck_combo.addItem(deck.name)
        deck_row.addWidget(self._deck_combo)
        layout.addLayout(deck_row)

        card_type_row = QHBoxLayout()
        card_type_row.addWidget(QLabel("Card type:"))
        self._card_type_combo = QComboBox()
        self._card_type_combo.addItem("(all)")
        for name in sorted({tmpl["name"] for model in mw.col.models.all() for tmpl in model["tmpls"]}):
            self._card_type_combo.addItem(name)
        card_type_row.addWidget(self._card_type_combo)
        layout.addLayout(card_type_row)

        layout.addWidget(QLabel("Format:"))
        self._format_input = QLineEdit(_DEFAULT_EXPORT_FORMAT)
        layout.addWidget(self._format_input)

        hint = QLabel("Use {{FieldName}} placeholders. One card per line.")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        self._export_btn = QPushButton("Export…")
        self._export_btn.clicked.connect(self._on_export)
        layout.addWidget(self._export_btn)

    def _resolve_notes(self) -> list:
        card_type = self._card_type_combo.currentText()
        card_filter = f' card:"{card_type}"' if card_type != "(all)" else ""
        use_selected = self._scope_check is not None and self._scope_check.isChecked()

        if use_selected:
            note_ids = self._selected_note_ids
            notes = [mw.col.get_note(nid) for nid in note_ids]
            if card_type != "(all)":
                valid_ids = set(mw.col.find_notes(f'card:"{card_type}"'))
                notes = [n for n in notes if n.id in valid_ids]
        else:
            deck_name = self._deck_combo.currentText()
            note_ids = mw.col.find_notes(f'deck:"{deck_name}"{card_filter}')
            notes = [mw.col.get_note(nid) for nid in note_ids]
        return notes

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save export", "", "Text files (*.txt);;All files (*)")
        if not path:
            return
        notes = self._resolve_notes()
        count = _export_notes(notes, self._format_input.text(), path)
        self.accept()
        QMessageBox.information(mw, "Language Assist", f"Exported {count} card(s) to:\n{path}")


# ---------------------------------------------------------------------------
# Menu & hooks
# ---------------------------------------------------------------------------

def _setup_menu() -> None:
    generate_action = QAction("Language Assist: Generate Cards", mw)
    generate_action.triggered.connect(lambda: CardGeneratorDialog(mw).exec())
    mw.form.menuTools.addAction(generate_action)

    export_action = QAction("Language Assist: Export Cards", mw)
    export_action.triggered.connect(lambda: CardExportDialog(parent=mw).exec())
    mw.form.menuTools.addAction(export_action)


def _on_browser_context_menu(browser, menu) -> None:
    note_ids = list(dict.fromkeys(mw.col.get_card(cid).nid for cid in browser.selected_cards()))
    if not note_ids:
        return
    action = menu.addAction("Language Assist: Export Selected")
    action.triggered.connect(lambda: CardExportDialog(note_ids, mw).exec())


gui_hooks.editor_did_load_note.append(_on_editor_load)
gui_hooks.editor_did_init_buttons.append(_add_editor_button)
gui_hooks.main_window_did_init.append(_setup_menu)
gui_hooks.browser_will_show_context_menu.append(_on_browser_context_menu)
