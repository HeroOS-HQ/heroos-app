"""Document templates and safe previews (M2-04C): a generic, deterministic preview engine.

The engine is generic and public; the templates it fills are not. JJ's letter
and email templates are proprietary content, so they never live in this
repository. They reach the API as a private, versioned, declarative **template
bundle** (JSON) that the backend loads once at startup from server-side
storage, pinned by its SHA-256 and checked against the installed rule bundle
(``bundle``). Without an installed bundle, previews are unavailable: nothing
is fabricated and everything else keeps working.

- ``bundle``: the template bundle schema, its strict validation, the loader and
  the cross-check against the rule bundle's stages.
- ``values``: validation of what an employer types into a template's fields.
- ``eligibility``: whether a template may be previewed in a Case now: only at a
  stage it is bound to, with the jurisdiction confirmed, nothing held and every
  precondition definitely met. It reads the progression evaluation and the
  answers, never an employer decision record.
- ``render``: fills a template into structured text blocks (no HTML, no
  template language, nothing executed); a missing value is a visible gap.

A preview is never stored, logged, sent, signed or issued, and never changes a
Case (docs/architecture/document-templates.md).
"""
