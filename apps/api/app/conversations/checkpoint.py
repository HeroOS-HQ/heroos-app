"""The conversation checkpoint (``heroos.assistant-checkpoint/1``): where the next turn starts.

A persisted conversation keeps server-side what M2-NEW-06's encrypted
continuation carries for a browser: what HeroOS asked last, the ENGINE_TRUSTED
facts, the founder's answer about this employee's jurisdiction, each
two-state caution's state, whether trusted state was lost, and the decisions
the last turn evaluated. It also keeps which decisions currently need Expert
Review (``Reviews``). Bounded canonical codes only: never a founder message, a
name, a narrative, model output or knowledge text.

It is a projection, never a source of truth:

- once the conversation has a Case, the Case's facts are the authoritative
  business facts. The checkpoint keeps only trusted facts the Case doesn't
  hold (conversation-control facts with no Case question, or one that can't be
  saved to the Case yet), and every turn reads the Case-backed ones from
  ``case_facts``;
- a Case fact the founder's newest statement contradicted stays out of the
  evaluation (``voided``) until the founder confirms a value or the Case
  records a newer one, so a conversation is never looser than M2-NEW-06's;
- the founder's answer about the employee's jurisdiction is bound to the
  Company jurisdiction it was given under; the Case's own confirmation counts
  when it is stricter or newer;
- a checkpoint that is missing, of an unknown schema, malformed, written under
  other knowledge, another execution profile or another Company jurisdiction,
  or for another workflow than the conversation's, is never trusted. What can
  be rebuilt safely (the workflow, the Case's facts and jurisdiction answer) is
  rebuilt; everything else is confirmed again (``reconfirm``). Active reviews
  are history, not runtime state: they are kept whenever the checkpoint is
  readable, and rebuilt from the turn records otherwise (``Reviews.replay``).
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final

from app.assistant.gateway.memory import (
    CERTAINTIES,
    MAX_REMEMBERED,
    MAX_TURNS,
    OUTCOMES,
    UNKNOWN_WORDS,
    AskRecord,
    ConversationMemory,
    Reading,
)
from app.assistant.gateway.service import snapshot_versions
from app.db.models.assistant import MAX_CHECKPOINT_BYTES
from app.evaluation.continuation import (
    MAX_ACTIONS,
    MAX_ASKED,
    MAX_FACTS,
    MAX_TWO_STATE,
    ContinuationState,
    ReadResult,
)
from app.evaluation.facts import Asked, AskedKind
from app.evaluation.model import ConversationEvaluation, TwoState, Value
from app.evaluation.snapshot import ExecutionSnapshot, WorkflowExecution
from app.workflows.conditions import Tri
from app.workflows.definition import CASE_JURISDICTION_KEY

SCHEMA: Final = "heroos.assistant-checkpoint/1"
MAX_VOIDED: Final = MAX_FACTS
MAX_REVIEWS: Final = 12
MAX_KEY_CHARS: Final = 120
_ASKED_KINDS: Final[tuple[AskedKind, ...]] = ("fact", "confirm", "insistence", "jurisdiction")
_JURISDICTION_ANSWERS: Final = ("confirmed", "different", "not_sure")
# The Case's intake jurisdiction status (app.workflows.intake) as the conversation's answer about
# this employee. A confirmation made under another Company jurisdiction must be confirmed again.
CASE_JURISDICTION_ANSWERS: Final[Mapping[str, str]] = {
    "resolved": "confirmed",
    "case_different": "different",
    "case_not_sure": "not_sure",
    "case_confirmation_outdated": "not_sure",
}


@dataclass(frozen=True, slots=True)
class Reviews:
    """What needs Expert Review now: decisions (option ids) and the matter as a whole.

    History stays in each turn's evaluation record. A decision's review ends only
    when a later evaluation of that decision no longer requires one, or when the
    founder explicitly withdraws it; a turn about something else changes nothing,
    and neither does a decision asked about only hypothetically (M2-NEW-08): a
    "what if" is never the employer's intention.
    """

    actions: tuple[str, ...] = ()
    matter: bool = False

    def advance(
        self,
        *,
        matter: str,
        evaluated: Iterable[tuple[str, bool]],
        matter_review: bool,
        withdrawn: Iterable[str] = (),
    ) -> "Reviews":
        """After one turn: ``evaluated`` = (decision, review required) as that turn evaluated it."""
        gone = set(withdrawn)
        active = [a for a in self.actions if a not in gone]
        for action, required in evaluated:
            if required and action not in active:
                active.append(action)
            elif not required and action in active:
                active.remove(action)
        # Only a turn about an HR matter says what the matter is now; anything else keeps it.
        current = matter_review if matter in ("supported", "unsupported_hr") else self.matter
        return Reviews(tuple(active[-MAX_REVIEWS:]), current)

    def after(self, evaluation: ConversationEvaluation, withdrawn: Sequence[str]) -> "Reviews":
        return self.advance(
            matter=evaluation.matter,
            evaluated=[
                (a.action, a.review is not None and a.review.required)
                for a in evaluation.actions
                if not a.hypothetical
            ],
            matter_review=any(r.required and r.scope == "matter" for r in evaluation.reviews),
            withdrawn=withdrawn,
        )

    @staticmethod
    def replay(turns: Iterable[tuple[Mapping[str, object], Sequence[str]]]) -> "Reviews":
        """Rebuilt from the stored records (each turn's ``record`` and withdrawn decisions)."""
        reviews = Reviews()
        for record, withdrawn in turns:
            actions = record.get("actions")
            matter_reviews = record.get("reviews")
            reviews = reviews.advance(
                matter=str(record.get("matter")),
                evaluated=[
                    (str(a["action"]), bool(a.get("review")))
                    for a in (actions if isinstance(actions, list) else [])
                    if isinstance(a, dict) and "action" in a and not a.get("hypothetical")
                ],
                matter_review=any(
                    isinstance(r, dict) and r.get("scope") == "matter"
                    for r in (matter_reviews if isinstance(matter_reviews, list) else [])
                ),
                withdrawn=withdrawn,
            )
        return reviews


@dataclass(frozen=True, slots=True)
class Checkpoint:
    # The knowledge and execution profile it was written under (``snapshot_versions``).
    versions: str
    state: ContinuationState = field(default_factory=ContinuationState)
    # Case-backed fact keys the founder's newest statement voided (until confirmed again).
    voided: tuple[str, ...] = ()
    # The Case's instance revision when it was written (a fact saved later is newer).
    case_revision: int | None = None
    # The Company Blueprint's confirmed employment jurisdiction it was written under.
    company_jurisdiction: str | None = None
    reviews: Reviews = field(default_factory=Reviews)
    # Chat-first Case: what the founder said that the Case could hold (Case question key ->
    # the server's canonical reading), shown for the employer to save to the Case with one
    # explicit action. A reading, never a trusted fact: nothing is saved until they do.
    noted: Mapping[str, Value] = field(default_factory=dict)
    # What the conversation covered (``app.assistant.gateway.memory``): for the next turn's
    # questions and wording only, never trusted.
    memory: ConversationMemory = field(default_factory=ConversationMemory)


def encode(checkpoint: Checkpoint) -> dict[str, object]:
    """Plain, bounded data for the ``checkpoint`` column."""
    state = checkpoint.state
    data: dict[str, object] = {
        "schema": SCHEMA,
        "versions": checkpoint.versions,
        "workflow": state.workflow,
        "asked": [
            [a.kind, a.key, *([a.candidate] if a.candidate is not None else [])]
            for a in state.asked[:MAX_ASKED]
        ],
        "engine": dict(sorted(state.engine.items())[:MAX_FACTS]),
        "jurisdiction": state.jurisdiction,
        "two_state": {
            t.rule: [t.shown, t.acknowledged, t.insists.value]
            for t in list(state.two_state.values())[:MAX_TWO_STATE]
        },
        "reconfirm": state.reconfirm,
        "actions": list(state.actions[:MAX_ACTIONS]),
        "voided": sorted(checkpoint.voided)[:MAX_VOIDED],
        "case_revision": checkpoint.case_revision,
        "company_jurisdiction": checkpoint.company_jurisdiction,
        "reviews": {
            "actions": list(checkpoint.reviews.actions[-MAX_REVIEWS:]),
            "matter": checkpoint.reviews.matter,
        },
    }
    if checkpoint.noted:
        data["noted"] = dict(sorted(checkpoint.noted.items())[:MAX_FACTS])
    memory = checkpoint.memory
    if memory.said or memory.asked or memory.turns or memory.told:
        data["memory"] = {
            "said": {
                # A reading that only covers its question keeps how ("implied", "uncertain" or
                # "rough").
                k: [r.value, r.turn, r.words, *([] if r.certainty == "stated" else [r.certainty])]
                for k, r in list(memory.said.items())[-MAX_REMEMBERED:]
            },
            "asked": {
                k: [r.times, r.last] for k, r in list(memory.asked.items())[-MAX_REMEMBERED:]
            },
            "turns": memory.turns,
            "told": list(memory.told[-MAX_REMEMBERED:]),
        }
    if len(_json(data)) > MAX_CHECKPOINT_BYTES:  # pragma: no cover - bounded by the limits above
        raise ValueError("checkpoint exceeds its bound")
    return data


def _json(data: Mapping[str, object]) -> bytes:
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode()


def _value(value: object) -> bool:
    """A canonical value's shape (as the continuation's): a short code or a bounded number."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= 1_000_000
    return isinstance(value, str) and 0 < len(value) <= 40 and value.replace("-", "_").replace(
        "_", ""
    ).isalnum()  # fmt: skip


def _key(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_KEY_CHARS


def _reviews(data: object) -> Reviews | None:
    if not isinstance(data, dict) or set(data) != {"actions", "matter"}:
        return None
    actions, matter = data["actions"], data["matter"]
    if (
        not isinstance(actions, list)
        or len(actions) > MAX_REVIEWS
        or not all(_value(a) for a in actions)
        or not isinstance(matter, bool)
    ):
        return None
    return Reviews(tuple(actions), matter)


def _count(value: object, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _reading(entry: object, *, sourced: bool) -> Reading | None:
    """One remembered reading: [value, message, words], and how it covers its question when it
    only covers it ([..., "implied"]); before readings had a source, the value alone (its message
    and words unknown)."""
    if not sourced:
        return Reading(entry, 0) if isinstance(entry, (str, int)) and _value(entry) else None
    if (
        not isinstance(entry, list)
        or len(entry) not in (3, 4)
        or not _value(entry[0])
        or not _count(entry[1], 0, MAX_TURNS)
        or not _count(entry[2], UNKNOWN_WORDS, MAX_FACTS)
        or (len(entry) == 4 and entry[3] not in CERTAINTIES[1:])
    ):
        return None
    return Reading(entry[0], entry[1], entry[2], *entry[3:])


def _memory(data: object) -> ConversationMemory | None:
    """The stored memory, or None for anything malformed (an absent one is empty)."""
    if data is None:
        return ConversationMemory()
    if not isinstance(data, dict) or set(data) not in (
        {"said", "asked"},
        {"said", "asked", "turns"},
        {"said", "asked", "turns", "told"},
    ):
        return None
    said, asked, turns = data["said"], data["asked"], data.get("turns", 0)
    told = data.get("told", [])
    if (
        not isinstance(said, dict)
        or len(said) > MAX_REMEMBERED
        or not isinstance(asked, dict)
        or len(asked) > MAX_REMEMBERED
        or not _count(turns, 0, MAX_TURNS)
        or not isinstance(told, list)
        or len(told) > MAX_REMEMBERED
        or not all(_key(t) for t in told)
    ):
        return None
    readings: dict[str, Reading] = {}
    for key, entry in said.items():
        reading = _reading(entry, sourced="turns" in data)
        if not _key(key) or reading is None:
            return None
        readings[key] = reading
    records: dict[str, AskRecord] = {}
    for key, entry in asked.items():
        if (
            not _key(key)
            or not isinstance(entry, list)
            or len(entry) != 2
            or not _count(entry[0], 1, 1000)
            or entry[1] not in OUTCOMES
        ):
            return None
        records[key] = AskRecord(entry[0], entry[1])
    return ConversationMemory(said=readings, asked=records, turns=turns, told=tuple(told))


def decode(data: object) -> Checkpoint | None:
    """The stored checkpoint, or None for anything it can't vouch for (never raises)."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    versions, workflow, jurisdiction = data.get("versions"), data.get("workflow"), data.get(
        "jurisdiction"
    )  # fmt: skip
    asked, engine, two_state = data.get("asked"), data.get("engine"), data.get("two_state")
    actions, voided, revision = data.get("actions"), data.get("voided"), data.get("case_revision")
    company, reviews = data.get("company_jurisdiction"), _reviews(data.get("reviews"))
    noted = data.get("noted", {})
    memory = _memory(data.get("memory"))
    if (
        memory is None
        or not isinstance(versions, str)
        or (workflow is not None and not _key(workflow))
        or (jurisdiction is not None and jurisdiction not in _JURISDICTION_ANSWERS)
        or (company is not None and not _value(company))
        or reviews is None
        or not isinstance(data.get("reconfirm"), bool)
        or not isinstance(asked, list)
        or len(asked) > MAX_ASKED
        or not isinstance(engine, dict)
        or len(engine) > MAX_FACTS
        or not all(_key(k) and _value(v) for k, v in engine.items())
        or not isinstance(two_state, dict)
        or len(two_state) > MAX_TWO_STATE
        or not isinstance(actions, list)
        or len(actions) > MAX_ACTIONS
        or not all(_value(a) for a in actions)
        or not isinstance(voided, list)
        or len(voided) > MAX_VOIDED
        or not all(_key(k) for k in voided)
        or (revision is not None and (not isinstance(revision, int) or isinstance(revision, bool)))
        or not isinstance(noted, dict)
        or len(noted) > MAX_FACTS
        or not all(_key(k) and _value(v) for k, v in noted.items())
    ):
        return None
    questions: list[Asked] = []
    for item in asked:
        if not isinstance(item, list) or not 2 <= len(item) <= 3:
            return None
        kind, key = item[0], item[1]
        candidate = item[2] if len(item) == 3 else None
        if kind not in _ASKED_KINDS or not _key(key):
            return None
        if candidate is not None and not _value(candidate):
            return None
        questions.append(Asked(kind, key, candidate))
    states: dict[str, TwoState] = {}
    for rule, entry in two_state.items():
        if (
            not _key(rule)
            or not isinstance(entry, list)
            or len(entry) != 3
            or not all(isinstance(e, bool) for e in entry[:2])
            or entry[2] not in {t.value for t in Tri}
        ):
            return None
        states[rule] = TwoState(rule, entry[0], entry[1], Tri(entry[2]))
    return Checkpoint(
        versions=versions,
        state=ContinuationState(
            workflow=workflow,
            asked=tuple(questions),
            engine=dict(engine),
            jurisdiction=jurisdiction,
            two_state=states,
            reconfirm=data["reconfirm"],
            actions=tuple(actions),
        ),
        voided=tuple(voided),
        case_revision=revision,
        company_jurisdiction=company,
        reviews=reviews,
        noted=dict(noted),
        memory=memory,
    )


@dataclass(frozen=True, slots=True)
class CaseView:
    """The attached Case as a turn reads it (latest answers, their revisions, its jurisdiction)."""

    answers: Mapping[str, object]
    # Per question key, the instance revision that last wrote it.
    revisions: Mapping[str, int]
    # The Case's intake jurisdiction status (app.workflows.intake).
    jurisdiction: str | None = None


@dataclass(frozen=True, slots=True)
class Resumed:
    """The state a turn starts from, and where its Case-backed facts came from."""

    read: ReadResult
    # Knowledge fact keys whose trusted value was read from the Case's facts.
    from_case: frozenset[str] = frozenset()
    # Case-backed keys still voided (kept out of the evaluation).
    voided: frozenset[str] = frozenset()
    # The checkpoint couldn't be trusted: rebuilt from the records, the rest re-confirmed.
    rebuilt: bool = False
    # The active reviews before this turn; None when they must be rebuilt from the records.
    reviews: Reviews | None = field(default_factory=Reviews)


def case_backed(execution: WorkflowExecution) -> Mapping[str, str]:
    """Knowledge fact key -> the Case question that holds it (canonical, collectable facts)."""
    return {
        key: schema.question
        for key, schema in execution.schemas.items()
        if schema.question is not None and schema.kind != "blueprint"
    }


def resume(
    snapshot: ExecutionSnapshot,
    *,
    stored: object | None,
    workflow: str | None,
    case: CaseView | None,
    company_jurisdiction: str | None,
) -> Resumed:
    """A persisted conversation's trusted state for this turn's snapshot.

    ``stored``: the conversation's raw checkpoint (None: a new conversation);
    ``workflow``: the conversation's established workflow; ``case``: its Case,
    if any; ``company_jurisdiction``: the Blueprint's confirmed employment
    jurisdiction now (None while unconfirmed).
    """
    if stored is None:
        return Resumed(ReadResult(None, "missing", True))
    checkpoint = decode(stored)
    trusted = (
        checkpoint is not None
        and checkpoint.versions == snapshot_versions(snapshot)
        and checkpoint.company_jurisdiction == company_jurisdiction
        and (workflow is None or checkpoint.state.workflow in (None, workflow))
    )
    execution = None if workflow is None else snapshot.execution(workflow)
    from_case: dict[str, Value] = {}
    voided: set[str] = set()
    written = None if checkpoint is None else checkpoint.case_revision
    if execution is not None and case is not None:
        # A voiding is kept even from a checkpoint that is otherwise rebuilt (stricter only).
        earlier = set() if checkpoint is None else set(checkpoint.voided)
        for key, question in case_backed(execution).items():
            value = case.answers.get(question)
            schema = execution.schemas[key]
            if value is None or not schema.valid(value):
                continue  # incompatible with the current runtime: history only, never used
            if key in earlier and (written is None or case.revisions.get(question, 0) <= written):
                voided.add(key)  # contradicted since, and the Case holds nothing newer
                continue
            from_case[key] = value  # type: ignore[assignment]  # schema.valid: a canonical value
    from_case_jurisdiction = (
        None if case is None or case.jurisdiction is None
        else CASE_JURISDICTION_ANSWERS.get(case.jurisdiction)
    )  # fmt: skip
    reviews = None if checkpoint is None else checkpoint.reviews
    if trusted and checkpoint is not None:
        state = checkpoint.state
        engine = {k: v for k, v in state.engine.items() if k not in voided}
        # The Case's facts are authoritative over anything the checkpoint kept.
        engine.update(from_case)
        jurisdiction = state.jurisdiction
        newer = case is not None and case.revisions.get(CASE_JURISDICTION_KEY, 0) > (written or 0)
        if from_case_jurisdiction is not None and (
            jurisdiction is None or newer or from_case_jurisdiction == "different"
        ):
            # The Case's own answer counts when the conversation has none, when it is newer,
            # or when it says another jurisdiction applies (stricter).
            jurisdiction = from_case_jurisdiction
        return Resumed(
            ReadResult(replace(state, engine=engine, jurisdiction=jurisdiction), None, True),
            frozenset(from_case),
            frozenset(voided),
            reviews=reviews,
        )
    rebuilt = ContinuationState(
        workflow=workflow, engine=from_case, jurisdiction=from_case_jurisdiction, reconfirm=True
    )
    return Resumed(
        ReadResult(rebuilt, None, True),
        frozenset(from_case),
        frozenset(voided),
        rebuilt=True,
        reviews=reviews,
    )


def next_checkpoint(
    snapshot: ExecutionSnapshot,
    state: ContinuationState,
    *,
    resumed: Resumed,
    workflow: str | None,
    case_answers: Mapping[str, object] | None,
    case_revision: int | None,
    company_jurisdiction: str | None,
    reviews: Reviews,
) -> Checkpoint:
    """The checkpoint after a turn: its next state, minus what the Case now holds.

    ``state``: the gateway's next trusted state; ``case_answers``: the Case's
    answers after this turn's changes (None: no Case); ``reviews``: the active
    reviews after this turn.
    """
    execution = None if workflow is None else snapshot.execution(workflow)
    answers = {} if case_answers is None else case_answers
    backed = {} if execution is None or case_answers is None else case_backed(execution)
    # Held by the Case with this very value: the Case is the record, not the checkpoint.
    engine = {
        key: value
        for key, value in state.engine.items()
        if not (key in backed and answers.get(backed[key]) == value)
    }
    # A Case fact the founder contradicted (and didn't confirm again) stays voided.
    earlier = resumed.from_case | resumed.voided
    voided = tuple(sorted(k for k in earlier if k in backed and k not in state.engine))
    return Checkpoint(
        versions=snapshot_versions(snapshot),
        state=replace(state, engine=engine),
        voided=voided,
        case_revision=case_revision,
        company_jurisdiction=company_jurisdiction,
        reviews=reviews,
    )
