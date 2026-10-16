"""Workflow progression (M2-03): a generic, deterministic stage engine.

The engine is generic and public; what it runs is not. JJ's disciplinary
methodology (stage prerequisites, rule definitions, customer wording, source
mappings) is proprietary content, so it is never part of this repository. It
reaches the API as a private, versioned, declarative **rule bundle** (JSON)
that the backend loads at startup from server-side storage, pinned by its
SHA-256 (``bundle``). Without an installed bundle, progression is unavailable:
nothing is fabricated and the intake keeps working.

- ``predicates``: typed, three-valued conditions over case facts and stage
  state (no ``eval``, nothing executed from text).
- ``bundle``: the bundle schema, its strict validation and the loader.
- ``engine``: the state machine. Pure: the same bundle, intake evaluation,
  facts and progress events always give the same result.

Nothing here classifies an incident, assesses an employee, selects a penalty or
decides anything for the employer. The employer selects the pathway and asks
for every transition; the backend decides only whether the transition is
allowed by the installed rules, and records the outcome
(docs/architecture/workflow-progression.md).
"""
