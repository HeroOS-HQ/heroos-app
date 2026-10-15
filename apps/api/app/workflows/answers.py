"""Validation of one step's submitted answers (pure; no database).

Answers are validated, never normalized: what is stored is exactly what the
client sent. A ``None`` value clears an answer. Error messages are fixed text
and never contain the submitted value (it can be HR case content).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from app.workflows.definition import NOT_SURE, Question, Step

# Earliest incident date accepted. A guard against typos, not a legal limit.
EARLIEST_DATE: Final = date(1990, 1, 1)
# Allowed control characters in free text: line breaks and tabs only.
TEXT_CONTROL_CHARACTERS: Final = frozenset("\n\t")


@dataclass(frozen=True, slots=True)
class FieldError:
    key: str
    message: str


def _text_error(value: str, question: Question) -> str | None:
    if value == "" or value.strip() == "":
        return "an answer must not be empty"
    if value != value.strip():
        return "must not start or end with whitespace"
    if question.max_length is not None and len(value) > question.max_length:
        return f"must be at most {question.max_length} characters"
    if any(not c.isprintable() and c not in TEXT_CONTROL_CHARACTERS for c in value):
        return "must not contain control characters"
    return None


def _date_error(value: str, question: Question, today: date) -> str | None:
    if question.allow_not_sure and value == NOT_SURE:
        return None
    # Exactly YYYY-MM-DD (date.fromisoformat also accepts other ISO forms).
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return "must be a date (YYYY-MM-DD)"
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return "must be a date (YYYY-MM-DD)"
    # One day of tolerance for the employer's time zone ahead of UTC.
    if parsed > today + timedelta(days=1):
        return "must not be in the future"
    if parsed < EARLIEST_DATE:
        return "is too far in the past"
    return None


def _answer_error(value: object, question: Question, today: date) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return "must be text"
    if question.kind == "text":
        return _text_error(value, question)
    if question.kind == "date":
        return _date_error(value, question, today)
    if value not in {option.value for option in question.options}:
        return "must be one of the listed options"
    return None


def validate_answers(
    step: Step, answers: Mapping[str, object], *, today: date
) -> tuple[dict[str, str | None], list[FieldError]]:
    """The accepted answers (fact key -> value, ``None`` = clear) or the errors."""
    errors: list[FieldError] = []
    accepted: dict[str, str | None] = {}
    for key, value in answers.items():
        question = step.question(key)
        if question is None:
            errors.append(FieldError(key, "is not a question of this step"))
            continue
        message = _answer_error(value, question, today)
        if message is not None:
            errors.append(FieldError(key, message))
        else:
            accepted[key] = value  # type: ignore[assignment]  # str or None, checked above
    return ({}, errors) if errors else (accepted, [])
