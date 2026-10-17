"""Typed progression conditions with three-valued (Kleene) logic.

A predicate is data, parsed from a rule bundle into these classes and evaluated
by ``evaluate``. Nothing is executed from text. An unanswered question and
"Not sure" are UNKNOWN, never FALSE; ``Not`` keeps UNKNOWN unknown. Stage
state is always known (a stage was completed in this Case, or it wasn't).

JSON forms (``parse``):

- ``{"answer": "<fact key>", "in": ["yes"]}``: the current answer is one of the
  values. Optional ``"unknown": [...]`` lists answers that count as UNKNOWN
  (default ``["not_sure"]``).
- ``{"all": [...]}``, ``{"any": [...]}``: conjunction and disjunction.
- ``{"not": {...}}``: negation.
- ``{"stage_completed": "<stage key>"}``: the stage was completed in this Case.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.workflows.conditions import Tri
from app.workflows.definition import NOT_SURE

# Bounds on what a bundle may contain: limits on input, not product rules.
MAX_DEPTH: Final = 8
MAX_TERMS: Final = 32
MAX_VALUES: Final = 16


class PredicateError(ValueError):
    """A predicate in a rule bundle is malformed (message: a location, never content)."""


@dataclass(frozen=True, slots=True)
class Answer:
    key: str
    values: tuple[str, ...]
    unknown: tuple[str, ...] = (NOT_SURE,)


@dataclass(frozen=True, slots=True)
class AllOf:
    terms: tuple["Predicate", ...]


@dataclass(frozen=True, slots=True)
class AnyOf:
    terms: tuple["Predicate", ...]


@dataclass(frozen=True, slots=True)
class Not:
    term: "Predicate"


@dataclass(frozen=True, slots=True)
class StageCompleted:
    stage: str


Predicate = Answer | AllOf | AnyOf | Not | StageCompleted


@dataclass(frozen=True, slots=True)
class Context:
    """What a predicate may read: the current answers and the completed stages."""

    answers: Mapping[str, object]
    completed: frozenset[str]


def evaluate(predicate: Predicate, context: Context) -> Tri:
    """Evaluate a predicate (pure, total, no ``eval``)."""
    if isinstance(predicate, Answer):
        value = context.answers.get(predicate.key)
        if value is None or value in predicate.unknown:
            return Tri.UNKNOWN
        return Tri.TRUE if value in predicate.values else Tri.FALSE
    if isinstance(predicate, StageCompleted):
        return Tri.TRUE if predicate.stage in context.completed else Tri.FALSE
    if isinstance(predicate, Not):
        inner = evaluate(predicate.term, context)
        if inner is Tri.UNKNOWN:
            return Tri.UNKNOWN
        return Tri.FALSE if inner is Tri.TRUE else Tri.TRUE
    results = [evaluate(term, context) for term in predicate.terms]
    if isinstance(predicate, AllOf):
        if Tri.FALSE in results:
            return Tri.FALSE
        return Tri.TRUE if all(r is Tri.TRUE for r in results) else Tri.UNKNOWN
    if Tri.TRUE in results:
        return Tri.TRUE
    return Tri.FALSE if all(r is Tri.FALSE for r in results) else Tri.UNKNOWN


def fact_keys(predicate: Predicate) -> tuple[str, ...]:
    """The answer keys a predicate reads, in order, without repeats."""
    if isinstance(predicate, Answer):
        return (predicate.key,)
    if isinstance(predicate, StageCompleted):
        return ()
    terms = (predicate.term,) if isinstance(predicate, Not) else predicate.terms
    keys: list[str] = []
    for term in terms:
        keys += [key for key in fact_keys(term) if key not in keys]
    return tuple(keys)


def stage_keys(predicate: Predicate) -> tuple[str, ...]:
    """The stages a predicate reads, in order, without repeats."""
    if isinstance(predicate, StageCompleted):
        return (predicate.stage,)
    if isinstance(predicate, Answer):
        return ()
    terms = (predicate.term,) if isinstance(predicate, Not) else predicate.terms
    keys: list[str] = []
    for term in terms:
        keys += [key for key in stage_keys(term) if key not in keys]
    return tuple(keys)


def unknown_keys(predicate: Predicate, context: Context) -> tuple[str, ...]:
    """The answer keys read by the predicate whose answer is missing or counts as unknown."""
    if isinstance(predicate, Answer):
        value = context.answers.get(predicate.key)
        return (predicate.key,) if value is None or value in predicate.unknown else ()
    if isinstance(predicate, StageCompleted):
        return ()
    terms = (predicate.term,) if isinstance(predicate, Not) else predicate.terms
    keys: list[str] = []
    for term in terms:
        keys += [key for key in unknown_keys(term, context) if key not in keys]
    return tuple(keys)


def _strings(value: object, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or len(value) > MAX_VALUES
        or (not value and not allow_empty)
        or not all(isinstance(item, str) and item for item in value)
        or len(set(value)) != len(value)
    ):
        raise PredicateError(f"{where}: expected a list of distinct strings")
    return tuple(value)


def parse(raw: object, where: str, depth: int = 0) -> Predicate:
    """A predicate from its JSON form; anything else is refused."""
    if depth > MAX_DEPTH:
        raise PredicateError(f"{where}: nested too deeply")
    if not isinstance(raw, dict):
        raise PredicateError(f"{where}: expected an object")
    keys = set(raw)
    if "answer" in raw:
        if not keys <= {"answer", "in", "unknown"} or "in" not in raw:
            raise PredicateError(f"{where}: an answer condition takes answer, in and unknown")
        key = raw["answer"]
        if not isinstance(key, str) or not key:
            raise PredicateError(f"{where}.answer: expected a fact key")
        values = _strings(raw["in"], f"{where}.in")
        unknown = (
            _strings(raw["unknown"], f"{where}.unknown", allow_empty=True)
            if "unknown" in raw
            else (NOT_SURE,)
        )
        if set(values) & set(unknown):
            raise PredicateError(f"{where}: a value cannot be both matched and unknown")
        return Answer(key, values, unknown)
    if len(keys) != 1:
        raise PredicateError(f"{where}: expected exactly one condition")
    (name,) = keys
    value = raw[name]
    if name in ("all", "any"):
        if not isinstance(value, list) or not value or len(value) > MAX_TERMS:
            raise PredicateError(f"{where}.{name}: expected 1 to {MAX_TERMS} conditions")
        terms = tuple(
            parse(term, f"{where}.{name}[{index}]", depth + 1) for index, term in enumerate(value)
        )
        return AllOf(terms) if name == "all" else AnyOf(terms)
    if name == "not":
        return Not(parse(value, f"{where}.not", depth + 1))
    if name == "stage_completed":
        if not isinstance(value, str) or not value:
            raise PredicateError(f"{where}.stage_completed: expected a stage key")
        return StageCompleted(value)
    raise PredicateError(f"{where}: unknown condition")
