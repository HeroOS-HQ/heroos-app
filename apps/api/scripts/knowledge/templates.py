"""The actual template files: their identity and what they say about themselves.

A document's identity comes from the file itself: the code in its filename
and the title its first paragraph states, which must agree (all significant
words of the filename title appear in the body title). Every other source's
reference to a document is checked against this identity, never the
reverse.

The instructions (the paragraphs before the letter itself) say when a
template is used and for which jurisdiction; they become the document's
``purpose`` segments. The letter body is never part of the runtime.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.docx_reader import read_docx

# Where a letter starts: the template's instructions are the paragraphs before it.
LETTER_STARTS: Final = ("Date:", "Subject:", "To:", "Dear ", "[Company Letterhead]")
_STOPWORDS: Final = frozenset(
    {"and", "of", "the", "to", "a", "with", "includes", "notice", "email", "&", "for", "right",
     "appeal"}
)  # fmt: skip
# Words that mean the same in a title ("No Suspension", "Without Suspension").
_SYNONYMS: Final = {"no": "without"}
_WORD: Final = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class Template:
    document_id: str
    filename_title: str
    title: str
    sha256: str
    instructions: tuple[str, ...]
    text: str
    flags: tuple[str, ...]


def significant(title: str) -> frozenset[str]:
    words = _WORD.findall(title.lower().replace("_", " "))
    return frozenset(_SYNONYMS.get(w, w) for w in words if w not in _STOPWORDS)


def same_document(a: str, b: str) -> bool:
    """Two titles name the same document: one's significant words all appear in the other."""
    sa, sb = significant(a), significant(b)
    return bool(sa) and bool(sb) and (sa <= sb or sb <= sa)


def parse_filename(filename: str, code: str) -> tuple[str, str] | None:
    """(document code, title) from "<code> - <title>.docx"; ``code`` is the mapping's pattern."""
    match = re.match(rf"^({code})\s*-\s*(.+?)\.docx$", filename)
    return None if match is None else (match.group(1), match.group(2))


def read_template(
    path: Path, code: str, letter_starts: tuple[str, ...] = LETTER_STARTS
) -> Template:
    parsed = parse_filename(path.name, code)
    if parsed is None:
        raise ValueError("template filename has no document code")
    document = read_docx(path)
    paragraphs = [p.text.strip() for p in document.paragraphs() if p.text.strip()]
    title = paragraphs[0] if paragraphs else ""
    instructions: list[str] = []
    for paragraph in paragraphs[1:]:
        if paragraph.startswith(letter_starts):
            break
        instructions.append(paragraph)
    return Template(
        document_id=parsed[0],
        filename_title=parsed[1],
        title=title,
        sha256=document.sha256,
        instructions=tuple(instructions),
        text="\n".join(paragraphs),
        flags=tuple(document.flags),
    )
