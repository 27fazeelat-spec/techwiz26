"""Format-independent representation of a parsed document."""
import re
from dataclasses import dataclass, field

ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")


def normalise_text(text):
    """Text used for matching and generation: zero-width characters removed, whitespace collapsed."""
    text = ZERO_WIDTH.sub("", text or "")
    text = text.replace(" ", " ").replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Block:
    """One unit of document content in reading order.

    kind: letterhead | title | heading | paragraph | list_item | table_row | footer
    """
    kind: str
    text: str
    level: int = 0                      # heading level (1, 2, ...)
    page: int | None = None             # PDF page number (1-based)
    paragraph_index: int | None = None  # DOCX body paragraph index (0-based)
    cells: list = field(default_factory=list)
    hidden: bool = False                # contains text a reader cannot see
    hidden_text: str = ""
    style: str = ""

    @property
    def clean(self):
        return normalise_text(self.text)

    def location(self):
        if self.kind == "footer":
            return {"footer": True, "page": self.page}
        if self.page is not None:
            return {"page": self.page}
        return {"paragraph": self.paragraph_index}


@dataclass
class ParsedDocument:
    format: str                                  # pdf | docx
    blocks: list
    pages: int | None = None
    properties: dict = field(default_factory=dict)   # file-level metadata (title, subject, author)
    warnings: list = field(default_factory=list)
    watermark: str = ""

    @property
    def body_blocks(self):
        return [b for b in self.blocks if b.kind not in ("letterhead", "footer")]

    def word_count(self):
        return sum(len(b.clean.split()) for b in self.body_blocks)

    @property
    def has_hidden_content(self):
        return any(b.hidden for b in self.blocks)
