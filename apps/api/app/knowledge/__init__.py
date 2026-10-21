"""The Approved Knowledge Runtime (M2-NEW-04): HeroOS methodology as structured data.

The knowledge runtime holds what HeroOS's approved sources say: the
Playbook's methodology in small, traceable units, the Conditions Library's
metadata, the Implementation Rules as structured guards, the document
catalog, the supported options and the reference data the runtime needs. It
is proprietary content, so it is never part of this public repository: an
offline compiler (``scripts.knowledge``) reads the authoritative sources and
writes a private, pinned **knowledge bundle**, which the API loads once at
startup from server-side storage, exactly like the rule and template bundles.

- ``bundle``: the bundle schema, its strict validation, the two digests and
  the safety invariants every bundle must satisfy to load at all.
- ``context``: the server-side query service. ``get_knowledge_context``
  returns a focused, deterministic ``KnowledgeContext`` for a workflow,
  jurisdiction, pathway, stage, topics, Conditions or documents, and an
  explicit status when the approved sources don't support the request.

What this package is not:

- **Not the Conditions engine.** Whether a Condition fired, whether a
  transition is allowed and what a Case's state is stay with
  ``app.workflows`` (intake rules and the progression engine). The runtime
  only describes Conditions; it never evaluates one.
- **Not an AI.** Nothing here calls a model, writes a prompt or phrases
  anything. The future AI gateway (M2-NEW-05) composes a user message, the
  ``CompanyBlueprintContext``, authorized case facts and a ``KnowledgeContext``.
- **Not an authority on its own.** No approved source, no answer: an
  unsupported workflow or topic, an unresolved jurisdiction, a quarantined
  route or a missing bundle each return an explicit status, never a fallback
  (docs/architecture/knowledge-runtime.md).
"""
