"""The canonical Company Blueprint context (M2-NEW-03), without a database.

Validation shared by the Blueprint update and founder registration, the
completeness rule, and the exact shape of ``CompanyBlueprintContext`` (what
future HeroOS AI may read, and nothing else). The database behaviour is in
tests/auth/test_company_blueprint_context_api.py (SQLite) and
tests/tenant_isolation/test_company_blueprint_context.py (PostgreSQL).
"""

import dataclasses
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.companies.blueprint import (
    BLUEPRINT_DETAILS,
    CompanyBlueprintContext,
    CompanyPerson,
    JurisdictionContext,
    missing_details,
    normalize_website_url,
    plain_text,
)
from app.db.models import CompanyBlueprint

CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "website_urls.json").read_text("utf-8")
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[repr(case["input"])[:60] for case in CASES])
def test_website_urls_are_normalized_or_refused_like_the_web_app(case: dict[str, Any]) -> None:
    # The same cases run in the web app's tests (normalizeWebsiteUrl).
    if case["stored"] is None:
        with pytest.raises(ValueError):
            normalize_website_url(case["input"])
    else:
        assert normalize_website_url(case["input"]) == case["stored"]


def test_a_website_url_longer_than_500_characters_is_refused() -> None:
    base = "https://bushandbush.example/"
    assert len(normalize_website_url(base + "a" * (500 - len(base)))) == 500
    with pytest.raises(ValueError):
        normalize_website_url(base + "a" * (501 - len(base)))


def test_url_refusals_never_echo_the_value() -> None:
    with pytest.raises(ValueError) as refused:
        normalize_website_url("javascript:steal(document.cookie)")
    assert "steal" not in str(refused.value)


@pytest.mark.parametrize(
    "value",
    ["One line.", "Two\nparagraphs.\n\nWith a gap.", "Tab\tseparated", "Arabic: شركة"],
)
def test_plain_text_keeps_line_breaks_exactly(value: str) -> None:
    assert plain_text(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "   ", " padded", "padded\n", "bell\x07", "carriage\rreturn", "nul\x00", "nbsp\xa0x"],
)
def test_plain_text_refuses_untidy_or_invisible_characters(value: str) -> None:
    with pytest.raises(ValueError):
        plain_text(value)


def _person(*, current: bool, primary: bool) -> CompanyPerson:
    return CompanyPerson(
        membership_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="company_admin",
        member_since=datetime(2026, 10, 1, tzinfo=UTC),
        is_current_user=current,
        is_primary_contact=primary,
    )


def test_an_empty_blueprint_needs_every_detail() -> None:
    assert missing_details(CompanyBlueprint(), None) == BLUEPRINT_DETAILS


def test_a_complete_blueprint_needs_nothing_and_optional_context_never_counts() -> None:
    blueprint = CompanyBlueprint(
        legal_name="Bush & Bush LLC",
        industry="Legal services",
        employee_count=0,
        company_summary="A small law firm.",
        licensing_location="difc",
        policies_exist="no",
        hr_support="none",
    )
    # No website, policy notes or HR notes: still complete.
    assert missing_details(blueprint, _person(current=True, primary=True)) == ()


@pytest.mark.parametrize(
    ("location", "authority", "missing"),
    [
        (None, None, True),
        ("not_sure", None, True),
        ("other", None, True),
        ("other", "Example Free Zone Authority", False),
        ("difc", None, False),
    ],
)
def test_the_jurisdiction_needs_attention_until_the_licensing_answer_is_definite(
    location: str | None, authority: str | None, missing: bool
) -> None:
    blueprint = CompanyBlueprint(licensing_location=location, licensing_authority=authority)
    assert ("jurisdiction" in missing_details(blueprint, None)) is missing


@pytest.mark.parametrize(("answer", "missing"), [(None, True), ("not_sure", True), ("yes", False)])
def test_policies_need_attention_until_answered_yes_or_no(
    answer: str | None, missing: bool
) -> None:
    blueprint = CompanyBlueprint(policies_exist=answer)
    assert ("policies" in missing_details(blueprint, None)) is missing


# Exactly what HeroOS AI may read. Adding a field is a deliberate change here.
CONTEXT_FIELDS = {
    "company_id",
    "company_display_name",
    "legal_name",
    "industry",
    "employee_count",
    "website_url",
    "company_summary",
    "jurisdiction",
    "policies_exist",
    "policy_context",
    "hr_support",
    "hr_support_notes",
    "primary_contact",
    "current_user",
    "updated_at",
    "missing",
}
PERSON_FIELDS = {
    "membership_id",
    "user_id",
    "role",
    "member_since",
    "is_current_user",
    "is_primary_contact",
}
JURISDICTION_FIELDS = {
    "readiness",
    "reason",
    "employment_jurisdiction",
    "confirmed_at",
    "guidance_allowed",
    "licensing_location",
    "licensing_authority",
}
# Nothing credential-like, identity-provider-specific or internal, at any depth.
FORBIDDEN_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "subject",
    "issuer",
    "claim",
    "identity",
    "session",
    "email",
    "audit",
    "actor",
    "created_at",
    "primary_jurisdiction",
)


def _field_names(cls: type) -> set[str]:
    return {field.name for field in dataclasses.fields(cls)}


def test_the_context_contract_is_exactly_the_safe_company_context() -> None:
    assert _field_names(CompanyBlueprintContext) == CONTEXT_FIELDS
    assert _field_names(CompanyPerson) == PERSON_FIELDS
    assert _field_names(JurisdictionContext) == JURISDICTION_FIELDS
    every = CONTEXT_FIELDS | PERSON_FIELDS | JURISDICTION_FIELDS
    assert not [name for name in every for bad in FORBIDDEN_FRAGMENTS if bad in name]


def test_the_context_is_immutable_and_knows_when_it_is_complete() -> None:
    contact = _person(current=False, primary=True)
    current = _person(current=True, primary=False)
    context = CompanyBlueprintContext(
        company_id=uuid.uuid4(),
        company_display_name="Bush & Bush",
        legal_name=None,
        industry=None,
        employee_count=None,
        website_url=None,
        company_summary=None,
        jurisdiction=JurisdictionContext(
            readiness="unconfirmed",
            reason="licensing_not_provided",
            employment_jurisdiction=None,
            confirmed_at=None,
            guidance_allowed=False,
            licensing_location=None,
            licensing_authority=None,
        ),
        policies_exist=None,
        policy_context=None,
        hr_support=None,
        hr_support_notes=None,
        primary_contact=contact,
        current_user=current,
        updated_at=None,
        missing=("legal_name",),
    )
    assert not context.complete
    # The primary contact and the person signed in are distinct people here.
    assert context.primary_contact != context.current_user
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.legal_name = "Changed"  # type: ignore[misc]
    assert dataclasses.replace(context, missing=()).complete
