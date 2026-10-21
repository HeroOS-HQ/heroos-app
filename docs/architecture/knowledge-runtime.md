# Approved Knowledge Runtime (M2-NEW-04)

**Status:** Implemented: the compiler, the runtime and the query service. No
knowledge bundle is installed in any environment, so the runtime answers
"bundle unavailable" everywhere until an installation is authorized. No
migration (the schema contract is unchanged). Nothing calls the runtime yet:
M2-NEW-05 will.\
**Owner:** Technical Lead\
**Milestone:** [M2 — Reliable AI HR Workflow Platform](../milestones/m2-reliable-ai-hr-workflow-platform.md)
(pillar 2, "Controlled intelligence")\
**Related:** [Workflow Progression](workflow-progression.md) and
[Document Templates](document-templates.md) (the private-bundle pattern this
follows), [Disciplinary Intake](disciplinary-intake.md) (the deterministic
rules), [Company Blueprint](company-blueprint.md) (`CompanyBlueprintContext`)

## 1. What it is

HeroOS's approved sources are a Playbook, a set of Implementation Rules, a
Conditions workbook and the document templates. The knowledge runtime is
those sources compiled into small, structured, traceable pieces that a
server-side service can select precisely:

```
SOURCES (read-only)  ->  offline compiler  ->  private knowledge bundle  ->  API (startup, pinned)
                                         \->  validation report (private)        |
                                                                    get_knowledge_context(query)
```

> **The AI does not become the Conditions engine.** The runtime *describes*
> Conditions; the deterministic engine (`app.workflows`) evaluates them,
> decides transitions and holds the Case's state. The runtime never decides
> whether a Condition fired, never authorizes anything and never chooses an
> outcome. The employer makes every employment decision.

It is **not** a conversation, a prompt, a questionnaire, a search engine or a
CMS. There are no embeddings, no vector store, no web retrieval and no model
call anywhere in it. Retrieval is deterministic: the same bundle and the same
query always give the same result, in the same order.

## 2. Sources, roles and immutability

The authoritative source package lives in a read-only directory on the
engineering server (its location is recorded in the private validation report,
never in this repository). The compiler:

- lists every file in sorted relative-path order (never filesystem order),
  hashes its exact bytes and refuses a symbolic link;
- matches each file to the compile mapping by exact filename; a **missing**
  source is `FATAL` (nothing is reconstructed from anywhere else), an
  **unexpected** file is reported and not used;
- refuses a source whose bytes changed since the mapping was reviewed
  against it (`SOURCE_CHANGED`);
- never writes into the source directory or into this repository, and writes
  its outputs owner-only (mode 600).

**Source files are never repaired.** Every normalization happens in the
compiled runtime and is recorded as a finding; the source keeps its own
wording, and the bundle keeps the raw source values for audit.

Each source, and each workbook sheet, has a **runtime role**:

| Role | Meaning | Example |
| --- | --- | --- |
| `operational` | Compiled into the runtime | The Conditions rows; reference data an active rule needs |
| `validation` | Cross-checked, never served | The workbook's document list, field list and legend |
| `audit_only` | Counted and reported, never advice | Structural findings, coverage checks |
| `test_only` | Fixtures for tests | An example company |
| `deferred` | A future capability, kept inactive | Document upload and temporary processing |
| `quarantined` | Withheld from automatic use | A route whose sources conflict |

The **manifest** in every bundle records each source's id, type, title,
filename, SHA-256, size, version, workflow, jurisdiction scope and role.

## 3. The compiler (`scripts/knowledge`)

```
uv run python -m scripts.knowledge inventory SOURCE_DIR
uv run python -m scripts.knowledge compile SOURCE_DIR MAPPING --out DIR
uv run python -m scripts.knowledge validate BUNDLE [--production]
```

Pipeline: inventory and checksums, manifest, parsing (`scripts.docx_reader`,
which now reads nested tables for knowledge, and `scripts.xlsx_reader`, both
standard-library only, refusing macros, embedded or external content and any
DTD; a formula is never evaluated), validation, normalization, conflict
classification, the operational slice, canonical serialization, both digests,
the report, and finally **the API's own loader** on the result: a bundle the
API would refuse is never written. Two runs over unchanged sources produce
byte-identical bundles and reports. The command line prints identities,
counts and finding codes, never source wording.

**The compile mapping** (`heroos.knowledge-mapping/1`, private) is the
reviewed engineering input that says how the package is organized: which file
is which source, where each Playbook unit starts and stops (anchors that must
match exactly one paragraph), which passages speak for which jurisdiction,
how each Implementation Rule becomes a guard, the facts, the options, and the
owner's decisions. A mapping that no longer fits the sources is refused, and
every Playbook paragraph and every rule must be accounted for (a unit, an
excluded span with its reason, or a guard of any status).

## 4. The two digests

| Digest | Identifies | Changes when |
| --- | --- | --- |
| `source_package_digest` | The exact source files (id, name, size, SHA-256, in id order) | Any source byte changes, including audit-only sheets |
| `runtime_bundle_digest` | The normalized operational knowledge (the bundle's `runtime` section, canonical JSON) | Any operational content changes |

Source references point at the exact text an item came from
(`content_sha256`), not at the whole file, so a reworded diagnostic or a new
audit note changes the source digest but not the runtime digest. The
loader recomputes both; a mismatch refuses the bundle. Both are logged at
startup and returned with every `KnowledgeContext`, so a future AI exchange
can record exactly which knowledge it used.

## 5. What the bundle holds

Schema `heroos.knowledge-bundle/1` (`app/knowledge/bundle.py`):

- **Workflow** definitions: pathways and stages (Disciplinary only), and the
  coverage limits the sources record per jurisdiction.
- **Playbook units**: small pieces of methodology, each with its workflow,
  pathway, stage, topics, scope, kind (orientation, methodology, legal
  reference, safeguard), source text split into jurisdiction **segments**,
  required facts, related Conditions, guards, documents and options, and a
  source reference. The Playbook is never one prompt string.
- **Conditions**: id, workflow, scope, type, title, guidance segments,
  trigger *description* (never an expression), `enforcement_status`,
  `citation_status`, `action_policy`, required facts, topics, stages, the
  source reference and every raw cell (audit only).
- **Implementation guards**: the cross-cutting rules as structured behavior:
  kind, scope, the topics and options that trigger them, `required` and
  `prohibited` behaviors from a closed vocabulary, escalation, explicit
  supersessions and status.
- **Documents**: the catalog built from the actual templates (§8).
- **Options**: the possible employer decisions the content covers, per
  jurisdiction (§9).
- **Reference data** an active runtime Condition needs, with its own scope
  and review status; nothing else from the workbook.
- **Facts**: what the methodology needs to know, and where HeroOS may already
  hold it (§10).
- **Quarantine** entries and the **engine links** (§7).

### 5.1 Conditions: actions, review status, enforcement

The workbook's action column is not a clean enum. Each value is matched
against fixed shapes, never executed:

| Source value shape | `action_policy` |
| --- | --- |
| `warn` / `block` / `escalate` | `{initial}` |
| `blocking` (a type value written as an action) | `{initial: block}`, reported `MALFORMED_ACTION` WARNING |
| `warn (first pass); block if the employer insists …` | `{initial: warn, follow_up: {block, employer_insists}}` |
| `warn; escalate if …` | `{initial: warn, follow_up: {escalate, condition_specific, clause}}` |
| anything else | `MALFORMED_ACTION` FATAL |

Three things stay separate: **enforcement status**, **citation (review)
status** and **action**.

- `needs_legal_review` never disables a row. An active row keeps its
  configured, conservative action (warn, block or escalate). Its legal basis
  is never presented as confirmed: `legal_basis_confirmed` is false,
  `presentation` is `provisional_not_legal_advice`, and every query that
  returns it carries a `legal_basis_not_confirmed` limitation. Nothing ever
  promotes a row to confirmed.
- `not_enforced` rows stay in the bundle for traceability and reporting, but
  never take part: they are never returned as safeguards, never linked to a
  deterministic rule (the loader refuses that), and an explicit request for
  one returns a `condition_not_enforced` limitation.
- **Precedence stays with the engine.** `ESCALATE > BLOCK > WARN > ALLOW` lives
  in `app.workflows.progression.engine`; the runtime doesn't restate it.

Only the **runtime slice** is published: Disciplinary rows, the global
routing prerequisite and shared rows. Rows of other workflows (Probation,
Recruitment, Performance) are counted and reported, never published, because
those workflows' sources aren't in the package.

### 5.2 Guards and explicit supersession

There is no "the Implementation Rules always win". A rule supersedes other
content **only where the rule itself says so** ("superseded by", "this rule
overrides"). The compiler reads those statements from the rule text and:

- requires a rule that states it is superseded to be mapped `superseded`, and
  listed under its successor;
- allows the mapping to withhold Playbook text or a Condition's guidance
  (`guidance_status: withheld`) only under a guard whose rule explicitly
  overrides; anything else is an implicit precedence and `FATAL`;
- reports every disagreement that no rule settles as `SOURCE_CONFLICT`, and
  keeps the conflicting text out of the runtime rather than choosing a side.

Guards whose capability isn't built are `deferred`: their prohibitions still
apply (a consumer must not offer a document upload or promise deletion of
uploaded material), and a query names them as `deferred_capability`
limitations. Rules about authoring or status are `audit_only`.

## 6. Safety boundaries the runtime enforces

These hold for every bundle, whatever its content says: the loader refuses a
bundle that breaks one (`_check_invariants`), and the golden tests check each
through the query service.

| Boundary | How |
| --- | --- |
| Serious misconduct opens an investigation; it never authorizes dismissal | A dismissal without notice is never `supported` in any jurisdiction, requires a completed investigation and the employee's response, and must be guarded by an operational investigation-first guard |
| Completing every stage doesn't make a dismissal lawful | Even with every fact established, the option stays `review_required`; `treat_stage_completion_as_lawful_dismissal` is prohibited |
| Federal termination-without-notice grounds identify potentially serious misconduct only | The ground-specific requirements, the investigation, the evidence and the employee's response are the option's required facts; the escalation the Conditions configure stays in force |
| DIFC dismissal without notice needs a human expert | `review_required` behind an operational expert-review guard; no document is eligible before documented expert clearance (`prohibited_when` on the outcome notice) |
| Salary deductions and damage recovery go to a human expert | `review_required` in every jurisdiction behind an expert-review guard; no document serves it; calculating, recommending an amount, issuing a notice and instructing payroll are prohibited. The narrow documented-loan exception at exit is a separate, deferred route of another workflow and is never generalized |
| Investigative suspension is not disciplinary suspension | Separate options, never the same document; investigative is never a penalty; the Federal limits of each are separate units, and never applied to DIFC |
| DIFC unpaid disciplinary suspension needs a human expert | `review_required` behind an expert-review guard; the notice is never generated for DIFC |
| The employer decides | Every option is `decided_by: employer` (the schema has no other value); there is no field for a selected option; choosing a sanction or deciding misconduct is proven are always prohibited |
| No promise HeroOS can't keep | Expert Review isn't operational yet: every review route carries `expert_review_not_operational`, and promising an expert's response is prohibited |

## 7. Jurisdiction isolation

Scopes: `shared` (practical methodology usable in every supported
jurisdiction), `uae_federal`, `difc`, and `global` (a cross-cutting
prerequisite). Text is split into **segments** where the jurisdiction changes,
never reworded: by the source's own labels ("UAE Federal:", "DIFC:"), by
mapped regions and by mapped paragraph or sentence rules. A query for
jurisdiction J returns only `shared`, `global` and J items, and only the
segments of those scopes.

The loader's **leakage check** refuses, sentence by sentence:

- `shared`/`global` text that names any article number, or a named legal
  authority of either regime (unless it only says it doesn't apply);
- `difc` text that states UAE Federal authority, and `uae_federal` text that
  states DIFC authority, except to say it doesn't apply.

System-rule text (guards) may compare the two regimes in one sentence; a
consumer receives it as a rule, never as customer guidance.

**Unknown jurisdiction.** No jurisdiction, an unsupported one, a Company whose
jurisdiction isn't confirmed, or a query that conflicts with the Company
Blueprint returns `jurisdiction_unresolved`: only units explicitly marked safe
without a jurisdiction (orientation, never a legal reference), the global
routing Condition and the cross-cutting guards. No options, no documents and
never another jurisdiction's content.

**Engine links.** Each deterministic intake rule that implements a Condition
is linked to it. The loader checks the link against `app.workflows.conditions`:
same action, enforced and active, review status matching `provisional`, and
the same jurisdiction. A link to a not-enforced row is refused.

## 8. Document catalog

- **Identity comes from the actual template files**: the code in the filename
  and the title in the document's first paragraph, which must agree.
- Every other source's reference to a document (the Playbook's pointers, the
  workbook's document list, codes in Condition text, a rule's mention) is
  checked against that identity and kept on the document as a `reference`
  with its resolution: `consistent`, `title_variant`,
  `source_mismatch_resolved` (an owner decision covers it), `source_mismatch`
  or `stale`.
- **Owner-approved normalization**: where the owner has decided the actual
  files are right for a pair of reversed codes, the runtime text uses the
  actual codes, every occurrence is a `SOURCE_MISMATCH` finding naming the
  decision, and the compiler verifies the decision against the files on
  every run (`OWNER_DECISION`; a contradiction is `FATAL`).
- **Copied mappings**: two documents carrying the same set of related
  Conditions, where the Conditions are unrelated to one of them, is a
  `BROKEN_MAPPING`: that document's related Conditions are dropped and its
  automatic route is quarantined. No rule is invented to replace them.
- **Stale notes** are verified against the file (`document_checks`): a
  workbook note about a template is `STALE_METADATA` when the file no longer
  says what the note claims.
- A document's existence never makes it eligible. Per jurisdiction it is
  `eligible_with_gates` (every gate must still hold), `review_required`,
  `expert_review_required`, `not_available` or `quarantined`; a template
  written for one regime is never offered in another; a document is never
  more available than any option it serves.

## 9. Options and next steps

An option is a possible employer decision the approved content covers:
`no_action`, `informal_resolution`, `workplace_reminder`, `written_warning`,
`final_written_warning`, `disciplinary_suspension_unpaid`, `salary_deduction`,
`delay_increase_or_promotion`, `ordinary_termination`,
`investigative_suspension`, `disciplinary_penalty_notice`,
`dismissal_without_notice`. Per jurisdiction: `supported` (the content covers
explaining it and its prerequisites: **not** a recommendation),
`review_required` or `not_available`, with the reason, documents, Conditions,
guards and required facts. Less serious discipline is not a ladder: options
are alternatives the employer may choose between, and improvement can end
the matter.

## 10. Facts, not questions; the Company Blueprint

The runtime never compiles a questionnaire. Each unit, Condition, option and
document names the **facts** it needs, and each fact says where HeroOS may
already hold it:

- a `CompanyBlueprintContext` field (validated against the dataclass at
  load), e.g. the employee count or the confirmed employment jurisdiction;
- a question of the current workflow definition (validated, with its
  sensitivity);
- or neither: it must come from the conversation.

A query with `company` (the canonical `CompanyBlueprintContext` from
M2-NEW-03; no second company model exists) and `known_facts` reports each
required fact as `from_blueprint`, `from_case`, `needs_confirmation` or
`missing`. The jurisdiction fact is `from_case` once the deterministic routing
resolved it. The workbook's own field list is dependency metadata only: no
Blueprint column was added for it.

## 11. The query service (`app/knowledge/context.py`)

```python
get_knowledge_context(
    bundle,                       # app.state.knowledge_bundle (None when not installed)
    KnowledgeQuery(
        workflow="disciplinary",
        jurisdiction="uae_federal",  # resolved by app.workflows routing, or None
        pathway=None, stage=None, topics=(), condition_ids=(), document_ids=(),
        known_facts=frozenset(), company=None,   # CompanyBlueprintContext
    ),
) -> KnowledgeContext
```

`KnowledgeContext`: `status`, both digests, the bundle version and
provenance, the query's dimensions, `playbook_units`, `condition_metadata`,
`implementation_guards`, `document_metadata`, `reference_data`,
`required_facts`, `missing_facts`, `safeguards`, `supported_next_steps`,
`required_behaviors`, `prohibited_behaviors`, `limitations`, `source_refs`
and `decided_by: employer`.

Selection is narrow: a stage returns that stage's units; a pathway its
overview; topics the units carrying them; nothing but a workflow and a
jurisdiction returns general orientation, never the whole Playbook.
Conditions, guards, documents and reference data come from what the selected
units and options reference, plus the global prerequisite and the
cross-cutting guards.

Statuses (about knowledge, never about the Case), the first that applies:

| Status | When |
| --- | --- |
| `bundle_unavailable` | No bundle installed |
| `unsupported` | The workflow, pathway, stage, topic, Condition or document isn't in the approved sources: nothing is returned |
| `jurisdiction_unresolved` | §7 |
| `source_conflict` | The request targets a route quarantined for conflicting or broken sources |
| `review_required` | The sources route the request to specialist review |
| `needs_more_context` | Covered, but required facts are still missing |
| `supported` | Covered |

## 12. Fail closed

The runtime refuses or returns an explicit status, and never falls back to
another jurisdiction, older sources, open-web or general model knowledge, a
stale bundle or an unvalidated template, when: no bundle is installed; the
file doesn't match its pin; a digest fails; a source is missing or changed; a
route is quarantined; the jurisdiction is unsupported or unresolved; sources
conflict on the requested route; content isn't approved for that use; a
document mapping is unsafe; or the bundle breaks an invariant. Production
additionally refuses synthetic and `development` content (every bundle
compiled today is `development`: approved development content, not
production-approved).

## 13. Security and privacy

| Concern | Control | Evidence |
| --- | --- | --- |
| Confidential sources in this public repository | Sources, mappings, bundles and reports are never tracked; git ignores their names, Word documents and workbooks; the compiler refuses to write inside the repository; the fictional test package is generated at test time | `tests/knowledge/test_configuration.py` (repository scan, ignore rules, Dockerfile), `test_compiler.py` |
| Knowledge reaching a browser or an unauthenticated client | Server-side only: no route serves it, no API module imports it, the web app never references it | `test_configuration.py`, `test_import_boundaries.py` |
| Knowledge in logs | Startup logs the bundle id, version, provenance, approval and digests only; the compiler prints counts and codes | `test_configuration.py`, `test_compiler.py` |
| Tampered or swapped bundle | SHA-256 pin, both digests recomputed, strict schema, invariants | `test_bundle.py` |
| The runtime acting on its own | It reads no database, calls no model, opens no connection, parses no document and has no `eval` | `test_import_boundaries.py` |
| Source files sent elsewhere | The compiler runs on the server that holds them; nothing is sent to any provider | (no network code in `scripts/knowledge`) |

## 14. Operating it

- **Compile** on the server that holds the sources, to an owner-only
  directory outside the repository. The report (`validation-report.json`,
  `.md`) lists the source checksums, every count, finding and quarantine,
  and both digests.
- **Validate** a bundle before installation:
  `uv run python -m scripts.knowledge validate BUNDLE [--production]`.
- **Install** (separately authorized, like any private bundle): place the
  file in server-side storage only the API can read, set
  `HEROOS_KNOWLEDGE_BUNDLE_PATH` and `HEROOS_KNOWLEDGE_BUNDLE_SHA256`, restart
  the API. A refusal stops startup; remove both variables to run without it.
- **Local real-source check**:
  `KNOWLEDGE_SOURCE_DIR=… KNOWLEDGE_MAPPING=… uv run pytest tests/knowledge/test_real_sources.py`
  (skipped in CI: the sources are never there).

## 15. The M2-NEW-05 contract (and M2-NEW-06)

M2-NEW-06 ([conversation-evaluation.md](conversation-evaluation.md)) executes
Conditions only through explicit bindings an execution profile approves
against this runtime's exact digest; the engine links here are reused, never
restated, and `not_enforced` or quarantined Conditions are never bound.


Implemented by Ask HeroOS's controlled AI gateway
([ai-gateway.md](ai-gateway.md)); case facts and history join it with
M2-NEW-06/07. The AI gateway composes, server-side: the user's message, the
`CompanyBlueprintContext`, authorized case facts and history, and one or more
`KnowledgeContext` results. It must:

- classify the founder's situation against the bundle's workflows and
  topics, and treat `unsupported` as "outside the approved playbooks"
  (explain and offer specialist help; never improvise);
- ask only for `missing_facts`, in its own words, reusing what the Blueprint
  and the Case already hold;
- keep every `required_behavior` and never adopt a `prohibited_behavior`;
- present a Condition's legal basis as confirmed only when
  `legal_basis_confirmed` is true;
- leave every deterministic outcome to `app.workflows` and every employment
  decision to the employer;
- record the `runtime_bundle_digest` with what it produced.

## 16. Tests

- `tests/knowledge/test_readers.py`: the XLSX reader and nested DOCX tables.
- `tests/knowledge/test_compiler.py`: manifest, digests and determinism, counts,
  action normalization, identity and owner decisions, broken mappings, stale
  metadata, explicit supersession, conflicts, scoping, coverage, the CLI.
- `tests/knowledge/test_bundle.py`: pin, schema, digests, every invariant,
  leakage, engine links, facts.
- `tests/knowledge/test_context.py`: the golden safety tests (serious
  misconduct, stage completion, isolation, unknown jurisdiction, expert review,
  suspensions, deductions, the employer's decision, not-enforced,
  needs-legal-review, document identity, quarantine, unsupported, determinism,
  facts and the Blueprint).
- `tests/knowledge/test_configuration.py`: settings, startup, logs, exposure and
  repository hygiene.
- `tests/knowledge/test_real_sources.py`: the real package (local only).
- `tests/fixtures/knowledge/synthetic.py`: the fictional package and mapping.
