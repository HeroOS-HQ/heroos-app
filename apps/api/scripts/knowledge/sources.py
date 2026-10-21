"""The source package: inventory, checksums, the manifest and shared text helpers.

The authoritative directory is read-only input. Files are listed in sorted
relative-path order (never filesystem order), hashed from their bytes, and
matched to the mapping's expected sources by exact filename. Nothing is ever
written into the source directory, and a symbolic link is refused rather
than followed.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.knowledge.findings import Findings

_SPACE: Final = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class SourceFile:
    relative: str
    path: Path
    sha256: str
    size: int


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def normalize(text: str) -> str:
    """Whitespace-collapsed, for anchor matching only (stored text stays verbatim)."""
    return _SPACE.sub(" ", text).strip()


def inventory(source_dir: Path) -> list[SourceFile]:
    """Every regular file under ``source_dir``, sorted by relative path, with its SHA-256."""
    root = source_dir.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(source_dir))
    files: list[SourceFile] = []
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError(f"symbolic link in source package: {path.relative_to(root)}")
        if not path.is_file():
            continue
        data = path.read_bytes()
        files.append(
            SourceFile(
                relative=path.relative_to(root).as_posix(),
                path=path,
                sha256=hashlib.sha256(data).hexdigest(),
                size=len(data),
            )
        )
    return files


def match_sources(
    expected: list[dict[str, object]], files: list[SourceFile], findings: Findings
) -> dict[str, SourceFile]:
    """source_id -> file, by exact filename; missing and unexpected files are findings."""
    by_name = {f.relative: f for f in files}
    found: dict[str, SourceFile] = {}
    for entry in expected:
        source_id, filename = str(entry["source_id"]), str(entry["filename"])
        file = by_name.get(filename)
        if file is None:
            # Never reconstructed from anywhere else: the bundle is invalid.
            findings.add(
                "MISSING_SOURCE", "FATAL", "source", source_id, "present",
                f"expected source file is missing: {filename}",
            )  # fmt: skip
            continue
        reviewed = entry.get("reviewed_sha256")
        if reviewed is not None and reviewed != file.sha256:
            findings.add(
                "SOURCE_CHANGED", "FATAL", "source", source_id, "reviewed_sha256",
                "the source changed since the compile mapping was reviewed against it",
            )  # fmt: skip
        found[source_id] = file
    named = {str(e["filename"]) for e in expected}
    for file in files:
        if file.relative not in named:
            findings.add(
                "UNEXPECTED_SOURCE", "WARNING", "file", file.relative, "unmapped",
                "file present in the source directory but not in the mapping; not used",
            )  # fmt: skip
    return found


def manifest_entry(entry: dict[str, object], file: SourceFile) -> dict[str, object]:
    return {
        "source_id": entry["source_id"],
        "source_type": entry["source_type"],
        "title": entry["title"],
        "filename": file.relative,
        "sha256": file.sha256,
        "size": file.size,
        "source_version": entry["source_version"],
        "workflow": entry["workflow"],
        "jurisdiction_scope": entry["jurisdiction_scope"],
        "runtime_role": entry["runtime_role"],
    }


def check_outside(path: Path, forbidden: Path, what: str) -> None:
    """Refuse to write ``what`` inside ``forbidden`` (the repository or the sources)."""
    resolved, root = path.resolve(), forbidden.resolve()
    if resolved == root or root in resolved.parents:
        raise ValueError(f"refusing to write {what} inside {root}")
