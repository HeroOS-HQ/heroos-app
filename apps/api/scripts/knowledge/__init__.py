"""The offline knowledge compiler (M2-NEW-04).

Engineering runs it on the server that holds the authoritative source
package; the API never does (``scripts/`` isn't in its image). It reads the
source files, never writes them, and produces a private knowledge bundle
plus a validation report, both outside the repository::

    uv run python -m scripts.knowledge inventory SOURCE_DIR
    uv run python -m scripts.knowledge compile SOURCE_DIR MAPPING --out DIR
    uv run python -m scripts.knowledge validate BUNDLE [--production]

Pipeline (``compiler.compile_package``): inventory and checksums, source
manifest, DOCX/XLSX parsing, validation, normalization, conflict
classification, the disciplinary operational slice, canonical serialization,
the two digests, the validation report and the bundle, which is then loaded
with the API's own loader (``app.knowledge.bundle``) so a bundle the API would
refuse is never written. Two runs over unchanged sources give byte-identical
outputs.

The **compile mapping** (``heroos.knowledge-mapping/1``) is the reviewed,
private engineering input that says how the source package is organized:
which file is which source, where each methodology unit starts and ends,
which jurisdiction each passage speaks for, how each Implementation Rule
becomes a guard, and the owner's decisions. The compiler verifies every
anchor against the sources and refuses a mapping that no longer fits them.
"""
