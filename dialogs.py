import logging
import threading
from collections.abc import Callable

from aqt import mw
from aqt.qt import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QTextEdit, QVBoxLayout,
)
from selectolax.parser import HTMLParser

from .fetcher import WordDataFetcher
from .models import WordData

logger = logging.getLogger("anki_language_assist")


# ---------------------------------------------------------------------------
# Note helpers
# ---------------------------------------------------------------------------

def set_note_field(note, field_name: str, value: str) -> None:
    if field_name in note.keys():
        note[field_name] = value


def apply_data_to_note(note, data: WordData, pronunciation_field: str,
                       audio_url_field: str, translations_field: str,
                       examples_field: str) -> None:
    examples_html = "<ul>" + "".join(f"<li>{e}</li>" for e in data.examples) + "</ul>"
    sanitized_tags = {t.replace(" ", "_") for t in data.tags if t}
    set_note_field(note, pronunciation_field, f"/{data.pronunciation}/" if data.pronunciation else "")
    set_note_field(note, audio_url_field, data.audio_url or "")
    set_note_field(note, translations_field, ", ".join(data.translations))
    set_note_field(note, examples_field, examples_html)
    note.tags = list(sanitized_tags)
    logger.debug("tags applied: %s", sanitized_tags)


# ---------------------------------------------------------------------------
# Card generator dialog
# ---------------------------------------------------------------------------

def _generate_cards(fetcher: WordDataFetcher, words: list[str], deck_name: str,
                    notetype_name: str, field_names: dict,
                    on_progress: Callable, on_done: Callable) -> None:
    notetype = mw.col.models.by_name(notetype_name)
    deck_id = mw.col.decks.id(deck_name)
    for i, word in enumerate(words, 1):
        mw.taskman.run_on_main(lambda w=word, idx=i: on_progress(idx, w))
        try:
            data = fetcher.fetch(word)
            def add_note(w=word, d=data) -> None:
                note = mw.col.new_note(notetype)
                set_note_field(note, field_names["target"], w)
                apply_data_to_note(note, d, **{k: v for k, v in field_names.items() if k != "target"})
                mw.col.add_note(note, deck_id)
            mw.taskman.run_on_main(add_note)
        except Exception as e:
            logger.error("failed to generate card for '%s': %s", word, e)
    mw.taskman.run_on_main(on_done)


class CardGeneratorDialog(QDialog):
    def __init__(self, fetcher: WordDataFetcher, field_names: dict, parent=None) -> None:
        super().__init__(parent)
        self._fetcher = fetcher
        self._field_names = field_names
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
            args=(self._fetcher, words, deck_name, notetype_name,
                  self._field_names, on_progress, on_done),
            daemon=True,
        ).start()


# ---------------------------------------------------------------------------
# Card export dialog
# ---------------------------------------------------------------------------

def _format_note(note, template: str) -> str:
    result = template
    for key in note.keys():
        value = HTMLParser(note[key]).text(strip=True) if note[key] else ""
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def _export_notes(notes, template: str, path: str) -> int:
    lines = [line for n in notes if (line := _format_note(n, template)).strip()]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(lines))
    return len(lines)


class CardExportDialog(QDialog):
    def __init__(self, default_format: str, selected_note_ids: list[int] | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._default_format = default_format
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
        self._format_input = QLineEdit(self._default_format)
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
            notes = [mw.col.get_note(nid) for nid in self._selected_note_ids]
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
        count = _export_notes(self._resolve_notes(), self._format_input.text(), path)
        self.accept()
        QMessageBox.information(mw, "Language Assist", f"Exported {count} card(s) to:\n{path}")
