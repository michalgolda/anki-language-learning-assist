from dataclasses import dataclass, field


@dataclass
class WordData:
    word: str
    pronunciation: str | None = None
    audio_url: str | None = None
    translations: list[str] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)
    examples: list[str] = field(default_factory=list)
