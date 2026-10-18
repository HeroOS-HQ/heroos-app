"""Document templates and safe previews (M2-04C) through the real application.

Same harness as test_progression_api.py: ``create_app`` with staging settings,
Cognito tokens verified by the production provider, in-memory SQLite built from
the real models (RLS, the read-only transaction and real isolation are proven
on PostgreSQL in tests/tenant_isolation/test_workflow_documents.py), and the
fictional synthetic rule and template bundles installed the way a deployment
installs them (paths and pinned SHA-256).

Covers: no installed templates (fail closed); availability per stage,
jurisdiction, hold, escalation, specialist-review requirement and
precondition (unknown never counts); the form and its suggestions; previews as
structured text with a watermark and visible gaps; values that look like
markup, links or template syntax staying literal text; validation that never
echoes a value; a changed template version; members and other Companies; that
nothing is written, logged or changed by any document route; and that an
employer decision record never makes a template available.
"""

import json
import logging
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.db.base import Base
from app.db.models import (
    Case,
    CaseFact,
    CaseSubject,
    Membership,
    WorkflowDecisionRecord,
    WorkflowEvaluation,
    WorkflowInstance,
    WorkflowProgressEvent,
    WorkflowSubmission,
)
from app.db.session import get_db
from app.documents.bundle import TemplateBundleError
from app.main import create_app
from app.tenancy.dependencies import ReadOnlyTransactionError, make_read_only
from tests.auth.conftest import SeedData
from tests.auth.test_company_admin_api import make_admin
from tests.auth.test_company_api import staging_settings
from tests.auth.test_decisions_api import record, record_body
from tests.auth.test_intake_api import CLEAR
from tests.auth.test_progression_api import (  # noqa: F401  (pytest fixtures)
    checklist,
    complete_stage,
    into_stage,
    ok,
    pathway,
    recorded_case,
    transition,
)
from tests.auth.test_workflow_api import (  # noqa: F401  (pytest fixtures)
    CONFLICT,
    FORBIDDEN,
    NOT_FOUND,
    admin_alice,
    alice,
    bob,
    create,
    sessions,
)
from tests.fixtures import (
    SYNTHETIC_BUNDLE,
    SYNTHETIC_TEMPLATES,
    synthetic_bundle_pin,
    synthetic_templates_pin,
)

CHECK_IN = "synthetic.check_in_note"
WRITTEN = "synthetic.written_note"
SPECIALIST = "synthetic.specialist_letter"
MEETING = "synthetic.meeting_record"
DIFC = "synthetic.difc_note"
NAME = "[SYNTHETIC] Sam Example"
SUMMARY = "[SYNTHETIC] We talked about the test.\nNothing else came up."
POINTS = ["[SYNTHETIC] Arrival times", "[SYNTHETIC] Handover notes"]
# Values that must stay literal text: markup, a link, template syntax.
HOSTILE = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(1)",
    "https://example.invalid/phish",
    "{{7*7}} ${7*7} {summary} %(summary)s",
]
TABLES = (
    Case,
    CaseFact,
    Membership,
    WorkflowDecisionRecord,
    WorkflowEvaluation,
    WorkflowInstance,
    WorkflowProgressEvent,
    WorkflowSubmission,
)


def documents_client(
    sessions: sessionmaker[Session],  # noqa: F811
    provider: CognitoAccessTokenProvider,
    *,
    templates: bool = True,
    rules: bool = True,
) -> TestClient:
    update_: dict[str, Any] = {"heroos_sensitive_screening": "synthetic_demo"}
    if rules:
        update_ |= {
            "heroos_rule_bundle_path": SYNTHETIC_BUNDLE,
            "heroos_rule_bundle_sha256": synthetic_bundle_pin(),
        }
    if templates:
        update_ |= {
            "heroos_template_bundle_path": SYNTHETIC_TEMPLATES,
            "heroos_template_bundle_sha256": synthetic_templates_pin(),
        }
    app = create_app(staging_settings().model_copy(update=update_))

    def _db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def client(
    sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
) -> TestClient:
    """Synthetic demo data only, with the synthetic rules and templates installed."""
    return documents_client(sessions, cognito_provider)


@pytest.fixture
def no_templates_client(
    sessions: sessionmaker[Session],  # noqa: F811
    cognito_provider: CognitoAccessTokenProvider,
) -> TestClient:
    return documents_client(sessions, cognito_provider, templates=False)


def documents(client: TestClient, headers: dict[str, str], company: uuid.UUID, case_id: str) -> Any:  # noqa: F811
    return client.get(f"/companies/{company}/cases/{case_id}/documents", headers=headers)


def form(
    client: TestClient,  # noqa: F811
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    key: str,
) -> Any:
    return client.get(f"/companies/{company}/cases/{case_id}/documents/{key}", headers=headers)


def preview(
    client: TestClient,  # noqa: F811
    headers: dict[str, str],
    company: uuid.UUID,
    case_id: str,
    key: str,
    *,
    values: dict[str, Any] | None = None,
    choices: dict[str, Any] | None = None,
    version: int = 1,
) -> Any:
    return client.post(
        f"/companies/{company}/cases/{case_id}/documents/{key}/preview",
        headers=headers,
        json={"template_version": version, "values": values or {}, "choices": choices or {}},
    )


def reasons(body: Any) -> dict[str, str | None]:
    return {t["key"]: t["reason"] for t in body["templates"]}


def counts(sessions: sessionmaker[Session]) -> dict[str, int]:  # noqa: F811
    with sessions() as db:
        return {
            model.__tablename__: db.scalar(select(func.count()).select_from(model)) or 0
            for model in TABLES
        }


def revision(sessions: sessionmaker[Session]) -> list[int]:  # noqa: F811
    with sessions() as db:
        return list(db.scalars(select(WorkflowInstance.revision)).all())


def text_of(blocks: list[Any]) -> str:
    """The preview as plain text (values and wording; gaps as [label])."""
    parts: list[str] = []

    def segments(items: list[Any]) -> str:
        out = ""
        for s in items:
            if s["kind"] in ("text", "value"):
                out += s["text"]
            elif s["kind"] == "missing":
                out += f"[{s['label']}]"
            elif s["kind"] == "blank":
                out += f"<{s['label']}>"
            else:
                out += "\n"
        return out

    for block in blocks:
        if block["type"] == "table":
            parts += [" | ".join(segments(cell) for cell in row) for row in block["rows"]]
        else:
            parts.append(segments(block["segments"]))
    return "\n".join(parts)


def at_check_in(
    client: TestClient,  # noqa: F811
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    headers: dict[str, str],
) -> tuple[str, Any]:
    """A UAE Federal Case with the intake recorded and stage 1 of the less serious pathway."""
    case_id, rev = recorded_case(client, sessions, seed, headers)
    body = into_stage(client, headers, seed.company_a, case_id, rev)
    return case_id, body


# --- fail closed -----------------------------------------------------------------------


def test_without_a_template_bundle_nothing_is_offered(
    no_templates_client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(no_templates_client, sessions, seed, admin_alice)
    body = ok(documents(no_templates_client, admin_alice, seed.company_a, case_id))
    assert body["installed"] is False
    assert body["templates"] == [] and body["bundle"] is None
    assert body["unavailable"] == "Document templates aren't available in this environment."
    for response in (
        form(no_templates_client, admin_alice, seed.company_a, case_id, CHECK_IN),
        preview(no_templates_client, admin_alice, seed.company_a, case_id, CHECK_IN),
    ):
        assert (response.status_code, response.json()) == NOT_FOUND


def test_templates_need_the_rules_they_were_written_for() -> None:
    settings = staging_settings().model_copy(
        update={
            "heroos_template_bundle_path": SYNTHETIC_TEMPLATES,
            "heroos_template_bundle_sha256": synthetic_templates_pin(),
        }
    )
    # The settings validator refuses this on load; the loader refuses it too.
    with pytest.raises(TemplateBundleError) as refused:
        create_app(settings)
    assert refused.value.code == "rules_not_installed"


def test_a_fresh_case_offers_nothing_until_it_can_move_on(
    client: TestClient,
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id = create(client, admin_alice, seed.company_a).json()["id"]
    body = ok(documents(client, admin_alice, seed.company_a, case_id))
    assert body["installed"] is True
    assert body["bundle"]["provenance"] == "synthetic"
    assert body["bundle"]["approval"] == "provisional"
    assert body["bundle"]["notice"]["title"] == "Synthetic test templates"
    assert set(reasons(body).values()) == {"case_not_ready"}
    assert all(not t["available"] for t in body["templates"])
    assert all(t["reason_text"] for t in body["templates"])
    for response in (
        form(client, admin_alice, seed.company_a, case_id, CHECK_IN),
        preview(client, admin_alice, seed.company_a, case_id, CHECK_IN),
    ):
        assert (response.status_code, response.json()) == CONFLICT


def test_availability_follows_the_stage_jurisdiction_and_review(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, rev = recorded_case(client, sessions, seed, admin_alice)
    before = reasons(ok(documents(client, admin_alice, seed.company_a, case_id)))
    assert before == {
        CHECK_IN: "not_at_this_stage",
        WRITTEN: "not_at_this_stage",
        SPECIALIST: "specialist_review_required",
        MEETING: "not_at_this_stage",
        DIFC: "not_for_jurisdiction",
    }

    into_stage(client, admin_alice, seed.company_a, case_id, rev)
    body = ok(documents(client, admin_alice, seed.company_a, case_id))
    assert reasons(body)[CHECK_IN] is None
    assert [t["code"] for t in body["templates"] if t["available"]] == ["TEST-01"]
    assert next(t for t in body["templates"] if t["key"] == CHECK_IN)["reason_text"] is None


def test_a_completed_stage_no_longer_offers_its_template(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, body = at_check_in(client, sessions, seed, admin_alice)
    complete_stage(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "test_check_in",
        {
            "progress.test_check_in.conversation_held": "yes",
            "progress.test_check_in.employee_heard": "yes",
        },
        body,
    )
    after = reasons(ok(documents(client, admin_alice, seed.company_a, case_id)))
    assert after[CHECK_IN] == "not_at_this_stage"


def test_a_precondition_must_be_definitely_met(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, body = at_check_in(client, sessions, seed, admin_alice)
    done = complete_stage(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "test_check_in",
        {
            "progress.test_check_in.conversation_held": "yes",
            "progress.test_check_in.employee_heard": "yes",
        },
        body,
    )
    started = ok(
        transition(
            client,
            admin_alice,
            seed.company_a,
            case_id,
            "start:test_written_note",
            revision=done["workflow"]["revision"],
        )
    )
    # Unanswered: unknown never counts as met.
    assert (
        reasons(ok(documents(client, admin_alice, seed.company_a, case_id)))[WRITTEN]
        == "requirement_unknown"
    )
    key = "progress.test_written_note.note_shared"
    rev = started["workflow"]["revision"]
    for answer, expected in (
        ("not_sure", "requirement_unknown"),
        ("no", "requirement_not_met"),
        ("yes", None),
    ):
        saved = ok(
            checklist(
                client,
                admin_alice,
                seed.company_a,
                case_id,
                "test_written_note",
                {key: answer},
                revision=rev,
            )
        )
        rev = saved["workflow"]["revision"]
        found = reasons(ok(documents(client, admin_alice, seed.company_a, case_id)))
        assert found[WRITTEN] == expected, answer
        status = preview(client, admin_alice, seed.company_a, case_id, WRITTEN).status_code
        assert status == (200 if expected is None else 409), answer


def test_a_held_case_offers_nothing(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = recorded_case(
        client,
        sessions,
        seed,
        admin_alice,
        screening={**CLEAR, "screening.pregnancy_maternity": "yes"},
    )
    body = ok(documents(client, admin_alice, seed.company_a, case_id))
    assert set(reasons(body).values()) == {"case_held"}
    assert all(
        t["reason_text"] == "Not available while this case is on hold for specialist review."
        for t in body["templates"]
    )


def test_a_recorded_escalation_holds_every_template(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, rev = recorded_case(client, sessions, seed, admin_alice)
    body = into_stage(
        client, admin_alice, seed.company_a, case_id, rev, choice="serious", stage="test_notice"
    )
    done = complete_stage(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "test_notice",
        {"progress.test_notice.notice_given": "yes"},
        body,
    )
    started = ok(
        transition(
            client,
            admin_alice,
            seed.company_a,
            case_id,
            "start:test_pause",
            revision=done["workflow"]["revision"],
        )
    )
    saved = ok(
        checklist(
            client,
            admin_alice,
            seed.company_a,
            case_id,
            "test_pause",
            {"progress.test_pause.pause_paid": "no"},
            revision=started["workflow"]["revision"],
        )
    )
    escalated = ok(
        transition(
            client,
            admin_alice,
            seed.company_a,
            case_id,
            "complete:test_pause",
            revision=saved["workflow"]["revision"],
        )
    )
    assert escalated["progression"]["escalations"]
    assert set(reasons(ok(documents(client, admin_alice, seed.company_a, case_id))).values()) == {
        "case_held"
    }


def test_an_employer_record_never_makes_a_template_available(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, rev = recorded_case(client, sessions, seed, admin_alice)
    before = ok(documents(client, admin_alice, seed.company_a, case_id))
    for category in ("meeting_recorded", "internal_review_completed", "other_note"):
        saved = record(
            client,
            admin_alice,
            seed.company_a,
            case_id,
            record_body(rev, category=category, summary="[SYNTHETIC] Check-in held and done"),
        )
        rev = ok(saved)["workflow"]["revision"]
    after = ok(documents(client, admin_alice, seed.company_a, case_id))
    assert after == before
    assert not any(t["available"] for t in after["templates"])


# --- the form ---------------------------------------------------------------------------


def test_the_form_lists_fields_choices_instructions_and_case_suggestions(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    body = ok(form(client, admin_alice, seed.company_a, case_id, CHECK_IN))
    assert body["template"] == {
        "key": CHECK_IN,
        "code": "TEST-01",
        "title": "Synthetic test letter: check-in note",
        "kind": "letter",
        "version": 1,
    }
    fields = {f["key"]: f for f in body["fields"]}
    assert list(fields) == [
        "document_date",
        "recipient_name",
        "company_name",
        "meeting_date",
        "discussion_points",
        "summary",
    ]
    assert fields["discussion_points"]["max_items"] == 5
    assert fields["summary"]["reminder"] is True
    assert fields["company_name"]["suggested"] == "Company A"
    # The Case has no subject: nothing to suggest, never a guess.
    assert fields["recipient_name"]["suggested"] is None
    assert [c["key"] for c in body["choices"]] == ["meeting_format"]
    assert body["instructions"][0]["segments"][0]["text"] == "[SYNTHETIC] Test instructions"
    assert "Nothing you type here is saved" in body["notice"]
    assert "Leave out health, family, religion" in body["reminder"]


def test_the_subject_suggestion_comes_from_this_case_only(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    # This harness builds only the workflow tables; the subject table is M1's.
    Base.metadata.create_all(sessions.kw["bind"], tables=[CaseSubject.__table__])
    with sessions() as db:
        subject = CaseSubject(company_id=seed.company_a, subject_type="employee", display_name=NAME)
        db.add(subject)
        db.flush()
        db.execute(update(Case).where(Case.id == uuid.UUID(case_id)).values(subject_id=subject.id))
        db.commit()
    fields = {
        f["key"]: f
        for f in ok(form(client, admin_alice, seed.company_a, case_id, CHECK_IN))["fields"]
    }
    assert fields["recipient_name"]["suggested"] == NAME


def test_an_unavailable_or_unknown_template_has_no_form(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    for key in (WRITTEN, SPECIALIST, MEETING, DIFC):
        response = form(client, admin_alice, seed.company_a, case_id, key)
        assert (response.status_code, response.json()) == CONFLICT, key
    for key in ("synthetic.unknown", "SYNTHETIC.CHECK_IN_NOTE", "x" * 100):
        response = form(client, admin_alice, seed.company_a, case_id, key)
        assert (response.status_code, response.json()) == NOT_FOUND, key
    assert form(client, admin_alice, seed.company_a, case_id, "x" * 101).status_code == 422


# --- the preview ------------------------------------------------------------------------


def test_a_preview_fills_the_template_with_a_watermark(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    body = ok(
        preview(
            client,
            admin_alice,
            seed.company_a,
            case_id,
            CHECK_IN,
            values={
                "document_date": "2026-10-18",
                "recipient_name": NAME,
                "company_name": "[SYNTHETIC] Example Trading LLC",
                "meeting_date": "2026-10-12",
                "discussion_points": POINTS,
                "summary": SUMMARY,
            },
            choices={"meeting_format": ["online"]},
        )
    )
    assert body["watermark"]["title"] == "Preview — not issued"
    assert "HeroOS doesn't give legal advice" in body["watermark"]["body"]
    assert body["watermark"]["approval"] == "Template wording: provisional, not approved for use."
    assert body["watermark"]["notice"]["title"] == "Synthetic test templates"
    assert body["missing"] == []
    text = text_of(body["blocks"])
    assert "18 October 2026" in text and "12 October 2026" in text
    assert f"To: {NAME}" in text
    assert "took place online." in text and "in person" not in text
    assert [b["segments"][0]["text"] for b in body["blocks"] if b["type"] == "item"] == POINTS
    assert "Summary:\n" + SUMMARY in text
    assert "Signed: <Signature>" in text


def test_missing_values_and_choices_are_visible_gaps(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    body = ok(preview(client, admin_alice, seed.company_a, case_id, CHECK_IN))
    assert body["missing"] == [
        "document_date",
        "recipient_name",
        "company_name",
        "meeting_date",
        "meeting_format",
        "discussion_points",
        "summary",
    ]
    text = text_of(body["blocks"])
    assert "To: [Recipient's name]" in text
    # One gap for the choice; no alternative is picked silently.
    assert text.count("[Choose: How the test conversation took place]") == 1
    assert "in person" not in text and "online" not in text
    assert "[Points discussed]" in text


def test_values_are_literal_text_never_markup_links_or_template_syntax(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    body = ok(
        preview(
            client,
            admin_alice,
            seed.company_a,
            case_id,
            CHECK_IN,
            values={
                "recipient_name": HOSTILE[0],
                "discussion_points": HOSTILE,
                "summary": HOSTILE[4],
            },
        )
    )
    values = [s for block in body["blocks"] for s in block["segments"] if s["kind"] == "value"]
    assert [s["text"] for s in values] == [HOSTILE[0], *HOSTILE, HOSTILE[4]]
    # Nothing was expanded, evaluated or turned into a link or markup.
    assert "49" not in text_of(body["blocks"])
    assert all(set(s) == {"kind", "text", "field", "label"} for s in values)
    assert {b["type"] for b in body["blocks"]} <= {"heading", "paragraph", "item", "table"}


def test_a_table_template_renders_rows_and_repeated_items(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, rev = recorded_case(client, sessions, seed, admin_alice)
    body = into_stage(
        client, admin_alice, seed.company_a, case_id, rev, choice="serious", stage="test_notice"
    )
    done = complete_stage(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        "test_notice",
        {"progress.test_notice.notice_given": "yes"},
        body,
    )
    ok(
        transition(
            client,
            admin_alice,
            seed.company_a,
            case_id,
            "start:test_meeting",
            revision=done["workflow"]["revision"],
        )
    )
    questions = [f"[SYNTHETIC] Question {n}" for n in range(1, 31)]
    shown = ok(
        preview(
            client,
            admin_alice,
            seed.company_a,
            case_id,
            MEETING,
            values={"meeting_date": "2026-10-01", "questions": questions},
        )
    )
    table = next(b for b in shown["blocks"] if b["type"] == "table")
    assert text_of([table]).splitlines() == [
        "Meeting date | 1 October 2026",
        "Attendees | [Attendees (roles only)]",
        "Signed | <Signature>",
    ]
    assert sum(1 for b in shown["blocks"] if b["type"] == "item") == 30
    assert shown["missing"] == ["attendee_roles"]


@pytest.mark.parametrize(
    ("values", "choices", "loc"),
    [
        ({"document_date": "18/10/2026"}, {}, ["body", "values", "document_date"]),
        ({"document_date": "2026-02-30"}, {}, ["body", "values", "document_date"]),
        ({"document_date": "1989-12-31"}, {}, ["body", "values", "document_date"]),
        ({"recipient_name": "Line\nbreak"}, {}, ["body", "values", "recipient_name"]),
        ({"recipient_name": "Right‮to-left"}, {}, ["body", "values", "recipient_name"]),
        ({"recipient_name": "Zero​width"}, {}, ["body", "values", "recipient_name"]),
        ({"recipient_name": " padded"}, {}, ["body", "values", "recipient_name"]),
        ({"recipient_name": "   "}, {}, ["body", "values", "recipient_name"]),
        ({"recipient_name": "x" * 121}, {}, ["body", "values", "recipient_name"]),
        ({"recipient_name": ["a list"]}, {}, ["body", "values", "recipient_name"]),
        ({"summary": "Bell\x07"}, {}, ["body", "values", "summary"]),
        ({"discussion_points": []}, {}, ["body", "values", "discussion_points"]),
        ({"discussion_points": ["a"] * 6}, {}, ["body", "values", "discussion_points"]),
        ({"discussion_points": "not a list"}, {}, ["body", "values", "discussion_points"]),
        ({"discussion_points": ["ok", ""]}, {}, ["body", "values", "discussion_points"]),
        ({"attendee_roles": "used elsewhere"}, {}, ["body", "values"]),
        ({"<script>": "x"}, {}, ["body", "values"]),
        ({}, {"meeting_format": ["in_person", "online"]}, ["body", "choices", "meeting_format"]),
        ({}, {"meeting_format": ["hybrid"]}, ["body", "choices", "meeting_format"]),
        ({}, {"meeting_format": []}, ["body", "choices", "meeting_format"]),
        ({}, {"meeting_format": ["online", "online"]}, ["body", "choices", "meeting_format"]),
        ({}, {"unknown_choice": ["online"]}, ["body", "choices"]),
    ],
)
def test_invalid_values_are_refused_without_echoing_them(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    values: dict[str, Any],
    choices: dict[str, Any],
    loc: list[str],
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    response = preview(
        client, admin_alice, seed.company_a, case_id, CHECK_IN, values=values, choices=choices
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert loc in [error["loc"] for error in detail]
    shown = json.dumps(detail)
    for value in (*values.values(), *choices.values()):
        for item in value if isinstance(value, list) else [value]:
            if len(item) > 3:
                assert item not in shown


def test_bounds_on_the_request_itself(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    path = f"/companies/{seed.company_a}/cases/{case_id}/documents/{CHECK_IN}/preview"
    for body in (
        {"template_version": 1, "values": {"summary": "x" * 4001}},
        {"template_version": 1, "values": {f"k{n}": "x" for n in range(61)}},
        {"template_version": 1, "values": {"discussion_points": ["x"] * 31}},
        {"template_version": 1, "choices": {f"c{n}": ["x"] for n in range(9)}},
        {"template_version": 1, "unexpected": True},
        {"template_version": "1"},
        {"template_version": 0},
        {},
    ):
        assert client.post(path, headers=admin_alice, json=body).status_code == 422, body


def test_a_changed_template_version_is_a_conflict(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    response = preview(client, admin_alice, seed.company_a, case_id, CHECK_IN, version=2)
    assert (response.status_code, response.json()) == CONFLICT


# --- access ------------------------------------------------------------------------------


def test_members_and_signed_out_users_get_nothing(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    with sessions() as db:
        db.execute(update(Membership).values(role="member"))
        db.commit()
    for response in (
        documents(client, alice, seed.company_a, case_id),
        form(client, alice, seed.company_a, case_id, CHECK_IN),
        preview(client, alice, seed.company_a, case_id, CHECK_IN),
    ):
        assert (response.status_code, response.json()) == FORBIDDEN
    for response in (
        documents(client, {}, seed.company_a, case_id),
        form(client, {}, seed.company_a, case_id, CHECK_IN),
        preview(client, {}, seed.company_a, case_id, CHECK_IN),
    ):
        assert response.status_code == 401


def test_another_companys_case_is_not_found_and_its_routes_forbidden(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    bob: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    make_admin(sessions, seed.company_b, seed.bob)
    # A's Case through B's routes, and a random id: identical 404s.
    for target in (case_id, str(uuid.uuid4())):
        for response in (
            documents(client, bob, seed.company_b, target),
            form(client, bob, seed.company_b, target, CHECK_IN),
            preview(client, bob, seed.company_b, target, CHECK_IN),
        ):
            assert (response.status_code, response.json()) == NOT_FOUND
    # A's routes with B's token: 403, exactly like a Company that does not exist.
    for response in (
        documents(client, bob, seed.company_a, case_id),
        preview(client, bob, seed.company_a, case_id, CHECK_IN),
    ):
        assert (response.status_code, response.json()) == FORBIDDEN


# --- nothing kept --------------------------------------------------------------------------


def test_no_document_route_writes_or_changes_anything(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    before, revisions, view = (
        counts(sessions),
        revision(sessions),
        client.get(
            f"/companies/{seed.company_a}/cases/{case_id}/workflow", headers=admin_alice
        ).json(),
    )
    for _ in range(3):
        ok(documents(client, admin_alice, seed.company_a, case_id))
        ok(form(client, admin_alice, seed.company_a, case_id, CHECK_IN))
        ok(
            preview(
                client,
                admin_alice,
                seed.company_a,
                case_id,
                CHECK_IN,
                values={"recipient_name": NAME, "summary": SUMMARY},
            )
        )
        preview(client, admin_alice, seed.company_a, case_id, CHECK_IN, values={"x": "y"})
    assert counts(sessions) == before
    assert revision(sessions) == revisions
    after = client.get(
        f"/companies/{seed.company_a}/cases/{case_id}/workflow", headers=admin_alice
    ).json()
    assert after == view
    # Nothing about a preview reaches the case history.
    assert NAME not in json.dumps(after) and "preview" not in json.dumps(after["timeline"]).lower()


def test_responses_are_never_cached(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    for response in (
        documents(client, admin_alice, seed.company_a, case_id),
        form(client, admin_alice, seed.company_a, case_id, CHECK_IN),
        preview(
            client, admin_alice, seed.company_a, case_id, CHECK_IN, values={"summary": SUMMARY}
        ),
    ):
        assert response.headers["Cache-Control"] == "no-store"


def test_logs_name_the_template_and_outcome_never_values_or_wording(
    client: TestClient,
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    admin_alice: dict[str, str],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    case_id, _ = at_check_in(client, sessions, seed, admin_alice)
    caplog.clear()
    caplog.set_level(logging.DEBUG)
    ok(form(client, admin_alice, seed.company_a, case_id, CHECK_IN))
    ok(
        preview(
            client,
            admin_alice,
            seed.company_a,
            case_id,
            CHECK_IN,
            values={"recipient_name": NAME, "summary": SUMMARY, "discussion_points": POINTS},
            choices={"meeting_format": ["online"]},
        )
    )
    preview(
        client,
        admin_alice,
        seed.company_a,
        case_id,
        CHECK_IN,
        values={"recipient_name": NAME + "\n"},
    )
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert f"template={CHECK_IN}" in logged
    for secret in (NAME, "We talked about", *POINTS, "online", "Test letter", "check-in note"):
        assert secret not in logged, secret


def test_the_read_only_guard_refuses_any_write(
    sessions: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
) -> None:
    with sessions() as db:
        make_read_only(db)
        db.add(Case(company_id=seed.company_a, case_type="general", title="[SYNTHETIC] Never"))
        with pytest.raises(ReadOnlyTransactionError):
            db.flush()
        db.rollback()
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Case)) == 0


def test_the_synthetic_bundle_is_fictional_and_bound_to_the_synthetic_rules() -> None:
    data = json.loads(Path(SYNTHETIC_TEMPLATES).read_text())
    assert data["provenance"] == "synthetic" and data["approval"] == "provisional"
    assert data["rule_bundle"] == {"bundle": "synthetic-progression", "versions": ["synthetic.1"]}
    assert all(t["source_sha256"] is None for t in data["templates"])
    assert all("SYNTHETIC" in json.dumps(t["body"]) for t in data["templates"])


def test_count_helper_covers_every_workflow_table(sessions: sessionmaker[Session]) -> None:  # noqa: F811
    names = {model.__tablename__ for model in TABLES}
    workflow_tables = {
        name for name in Base.metadata.tables if name.startswith(("workflow_", "case_facts"))
    }
    assert workflow_tables <= names
