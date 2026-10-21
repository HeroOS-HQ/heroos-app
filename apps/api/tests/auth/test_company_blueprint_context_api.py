"""The Company Blueprint context through the real application (M2-NEW-03).

``create_app`` with staging settings, Cognito access tokens verified by the
production provider, and in-memory SQLite built from the real models (no RLS;
grants, the Company-qualified contact key and the text checks are proven on
PostgreSQL in tests/tenant_isolation/test_company_blueprint_context.py).

Seed (tests/auth/conftest.py): Company A with alice, Company B with bob;
``dave`` joins Company A here, so the primary contact and the person signed in
can differ.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth.models import AuthenticatedCompanyContext
from app.companies.blueprint import load_company_blueprint_context
from app.db.models import CompanyBlueprint, Membership, User, UserIdentity
from app.tenancy.scope import CompanyScope
from tests.auth.conftest import TEST_COGNITO_ISSUER, CognitoTokenFactory, SeedData, bearer
from tests.auth.test_company_admin_api import (  # noqa: F401 (fixtures)
    alice,
    blueprints,
    client,
    make_admin,
    stored_blueprint,
)

FORBIDDEN = (403, {"detail": "Forbidden"})
SUMMARY = (
    "Corporate and employment law firm.\n\n"
    "Two partners lead small teams of associates, supported by front-desk staff."
)


@pytest.fixture
def dave(blueprints: sessionmaker[Session], seed: SeedData) -> uuid.UUID:  # noqa: F811
    """A second person in Company A (a member), able to sign in. Returns the Membership id."""
    with blueprints() as db:
        user = User()
        db.add(user)
        db.flush()
        db.add(UserIdentity(user_id=user.id, issuer=TEST_COGNITO_ISSUER, subject="dave-subject"))
        membership = Membership(company_id=seed.company_a, user_id=user.id)
        db.add(membership)
        db.commit()
        return membership.id


@pytest.fixture
def admin_url(blueprints: sessionmaker[Session], seed: SeedData) -> str:  # noqa: F811
    make_admin(blueprints, seed.company_a, seed.alice)
    return f"/companies/{seed.company_a}/blueprint"


def test_an_administrator_saves_the_company_context_and_reads_it_back(
    client: TestClient,  # noqa: F811
    blueprints: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
) -> None:
    body = {
        "website_url": "BushAndBush.example/",
        "company_summary": SUMMARY,
        "policies_exist": "yes",
        "policy_context": "Employee handbook\nDisciplinary policy",
        "hr_support": "external",
        "hr_support_notes": "An outside HR consultant supports us.",
        "primary_contact_membership_id": str(seed.alice_membership_a),
    }
    saved = client.patch(admin_url, headers=alice, json=body)

    assert saved.status_code == 200
    out = saved.json()
    # The URL is stored normalized; the text exactly as sent, line breaks included.
    assert out["website_url"] == "https://bushandbush.example"
    assert out["company_summary"] == SUMMARY
    assert (out["policies_exist"], out["policy_context"]) == (
        "yes",
        "Employee handbook\nDisciplinary policy",
    )
    assert (out["hr_support"], out["hr_support_notes"]) == (
        "external",
        "An outside HR consultant supports us.",
    )
    assert out["primary_contact"] == {
        "membership_id": str(seed.alice_membership_a),
        "role": "company_admin",
        "member_since": out["primary_contact"]["member_since"],
        "is_current_user": True,
        "is_primary_contact": True,
    }
    assert out["company_name"] == "Company A"
    assert out["updated_at"] is not None
    assert out["completeness"] == {
        "complete": False,
        "missing": ["legal_name", "industry", "employee_count", "jurisdiction"],
    }
    assert client.get(admin_url, headers=alice).json() == out
    stored = stored_blueprint(blueprints, seed.company_a)
    assert stored is not None
    assert (stored.website_url, stored.primary_contact_membership_id) == (
        "https://bushandbush.example",
        seed.alice_membership_a,
    )


def test_partial_updates_change_only_the_fields_sent_and_null_clears(
    client: TestClient,  # noqa: F811
    blueprints: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
) -> None:
    client.patch(
        admin_url,
        headers=alice,
        json={
            "legal_name": "Alpha LLC",
            "licensing": {"location": "difc"},
            "company_summary": SUMMARY,
            "hr_support": "internal",
        },
    )
    second = client.patch(admin_url, headers=alice, json={"website_url": "alpha.example"})
    out = second.json()
    assert (out["legal_name"], out["company_summary"], out["hr_support"]) == (
        "Alpha LLC",
        SUMMARY,
        "internal",
    )
    assert out["licensing"] == {"location": "difc", "authority": None}
    assert out["website_url"] == "https://alpha.example"

    cleared = client.patch(
        admin_url, headers=alice, json={"website_url": None, "hr_support": None}
    ).json()
    assert (cleared["website_url"], cleared["hr_support"]) == (None, None)
    assert (cleared["legal_name"], cleared["company_summary"]) == ("Alpha LLC", SUMMARY)


def test_context_edits_never_touch_the_jurisdiction(
    client: TestClient,  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
) -> None:
    before = client.patch(
        admin_url, headers=alice, json={"licensing": {"location": "other", "authority": "JAFZA"}}
    ).json()
    after = client.patch(
        admin_url,
        headers=alice,
        json={"company_summary": "We trade in DIFC and the mainland.", "policies_exist": "no"},
    ).json()
    # Text that mentions a jurisdiction establishes nothing: the canonical fields are unchanged.
    assert after["licensing"] == before["licensing"]
    assert after["jurisdiction"] == before["jurisdiction"]
    assert after["jurisdiction"]["employment_jurisdiction"] is None
    assert after["jurisdiction"]["guidance_allowed"] is False


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"website_url": "javascript:alert(1)"}, id="javascript-url"),
        pytest.param({"website_url": "data:text/html,x"}, id="data-url"),
        pytest.param({"website_url": "file:///etc/passwd"}, id="file-url"),
        pytest.param({"website_url": "ftp://alpha.example"}, id="ftp-url"),
        pytest.param({"website_url": "https://user:pw@alpha.example"}, id="credentials"),
        pytest.param({"website_url": "https://127.0.0.1"}, id="ip-address"),
        pytest.param({"website_url": "https://alpha.example:8443"}, id="port"),
        pytest.param({"website_url": ""}, id="empty-url"),
        pytest.param({"website_url": "https://a.example/" + "x" * 600}, id="long-url"),
        pytest.param({"website_url": 42}, id="url-not-text"),
        pytest.param({"company_summary": "x" * 2001}, id="long-summary"),
        pytest.param({"company_summary": " padded"}, id="padded-summary"),
        pytest.param({"company_summary": "bell\x07"}, id="control-summary"),
        pytest.param({"company_summary": ""}, id="empty-summary"),
        pytest.param({"policy_context": "x" * 1001}, id="long-policy-context"),
        pytest.param({"hr_support_notes": "x" * 501}, id="long-hr-notes"),
        pytest.param({"policies_exist": "maybe"}, id="unknown-policies-answer"),
        pytest.param({"policies_exist": "YES"}, id="policies-wrong-case"),
        pytest.param({"policies_exist": True}, id="policies-boolean"),
        pytest.param({"hr_support": "outsourced"}, id="unknown-hr-support"),
        pytest.param({"primary_contact_membership_id": "not-a-uuid"}, id="malformed-contact"),
        pytest.param({"primary_contact_membership_id": 7}, id="numeric-contact"),
    ],
)
def test_invalid_context_is_refused_without_echo_or_change(
    client: TestClient,  # noqa: F811
    blueprints: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
    body: dict[str, Any],
) -> None:
    response = client.patch(admin_url, headers=alice, json=body)

    assert response.status_code == 422
    for error in response.json()["detail"]:
        assert set(error) <= {"type", "loc", "msg"}
    assert "alert" not in response.text and "passwd" not in response.text
    assert stored_blueprint(blueprints, seed.company_a) is None


def test_the_longest_accepted_text_is_stored(
    client: TestClient,  # noqa: F811
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
) -> None:
    body = {
        "company_summary": "s" * 2000,
        "policy_context": "p" * 1000,
        "hr_support_notes": "h" * 500,
    }
    out = client.patch(admin_url, headers=alice, json=body).json()
    assert [len(out[name]) for name in body] == [2000, 1000, 500]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"company_name": "Renamed"}, id="display-name-is-read-only-here"),
        pytest.param({"people": []}, id="people"),
        pytest.param({"primary_contact": {"membership_id": str(uuid.uuid4())}}, id="contact"),
        pytest.param({"completeness": {"complete": True, "missing": []}}, id="completeness"),
        pytest.param({"updated_at": "2026-10-21T00:00:00Z"}, id="updated-at"),
        pytest.param({"policies": "yes"}, id="unknown-policies-name"),
        pytest.param({"policy_documents": ["handbook.pdf"]}, id="policy-documents"),
    ],
)
def test_read_only_and_unknown_fields_are_refused(
    client: TestClient,  # noqa: F811
    blueprints: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
    body: dict[str, Any],
) -> None:
    response = client.patch(admin_url, headers=alice, json=body)
    assert response.status_code == 422
    assert {error["type"] for error in response.json()["detail"]} == {"extra_forbidden"}
    assert stored_blueprint(blueprints, seed.company_a) is None


@pytest.mark.parametrize("answer", ["yes", "no", "not_sure", None])
def test_every_policies_answer_is_kept(
    client: TestClient,  # noqa: F811
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
    answer: str | None,
) -> None:
    out = client.patch(admin_url, headers=alice, json={"policies_exist": answer}).json()
    assert out["policies_exist"] == answer
    # Only a definite yes or no settles the policies question.
    assert ("policies" in out["completeness"]["missing"]) is (answer in (None, "not_sure"))


@pytest.mark.parametrize("support", ["none", "internal", "external", "mixed", "other"])
def test_every_hr_support_arrangement_is_kept(
    client: TestClient,  # noqa: F811
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
    support: str,
) -> None:
    out = client.patch(admin_url, headers=alice, json={"hr_support": support}).json()
    assert out["hr_support"] == support
    assert "hr_support" not in out["completeness"]["missing"]


def test_the_primary_contact_must_be_an_active_member_of_the_same_company(
    client: TestClient,  # noqa: F811
    blueprints: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
) -> None:
    with blueprints() as db:
        bob_membership = db.scalar(select(Membership.id).where(Membership.user_id == seed.bob))
    refusals = [
        client.patch(
            admin_url, headers=alice, json={"primary_contact_membership_id": str(candidate)}
        )
        for candidate in (bob_membership, uuid.uuid4(), seed.company_a, seed.alice)
    ]
    # Another Company's Membership reads exactly like an id that exists nowhere.
    assert {(r.status_code, r.text) for r in refusals} == {
        (
            422,
            '{"detail":[{"type":"value_error","loc":["body","primary_contact_membership_id"],'
            '"msg":"invalid"}]}',
        )
    }
    assert stored_blueprint(blueprints, seed.company_a) is None

    accepted = client.patch(
        admin_url,
        headers=alice,
        json={"primary_contact_membership_id": str(seed.alice_membership_a), "industry": "Law"},
    )
    assert accepted.status_code == 200
    # A refused contact leaves the rest of the request unapplied too.
    refused = client.patch(
        admin_url,
        headers=alice,
        json={"primary_contact_membership_id": str(bob_membership), "industry": "Changed"},
    )
    assert refused.status_code == 422
    stored = stored_blueprint(blueprints, seed.company_a)
    assert stored is not None
    assert (stored.primary_contact_membership_id, stored.industry) == (
        seed.alice_membership_a,
        "Law",
    )
    cleared = client.patch(admin_url, headers=alice, json={"primary_contact_membership_id": None})
    assert cleared.json()["primary_contact"] is None
    assert "primary_contact" in cleared.json()["completeness"]["missing"]


def test_the_primary_contact_and_the_person_signed_in_are_distinct(
    client: TestClient,  # noqa: F811
    blueprints: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
    dave: uuid.UUID,
    make_cognito_token: CognitoTokenFactory,
) -> None:
    as_alice = client.patch(
        admin_url, headers=alice, json={"primary_contact_membership_id": str(dave)}
    ).json()
    assert as_alice["primary_contact"]["membership_id"] == str(dave)
    assert as_alice["primary_contact"]["is_current_user"] is False
    people = {p["membership_id"]: p for p in as_alice["people"]}
    assert set(people) == {str(seed.alice_membership_a), str(dave)}
    assert people[str(seed.alice_membership_a)]["is_current_user"] is True
    assert people[str(dave)]["is_primary_contact"] is True
    assert people[str(dave)]["role"] == "member"

    # dave (a member) reads the same Blueprint: now he is the current user and the contact.
    as_dave = client.get(admin_url, headers=bearer(make_cognito_token("dave-subject"))).json()
    assert as_dave["primary_contact"]["is_current_user"] is True
    assert {p["membership_id"]: p["is_current_user"] for p in as_dave["people"]} == {
        str(seed.alice_membership_a): False,
        str(dave): True,
    }
    # ...but a member can't change it.
    denied = client.patch(
        admin_url,
        headers=bearer(make_cognito_token("dave-subject")),
        json={"primary_contact_membership_id": str(dave), "company_summary": "x"},
    )
    assert (denied.status_code, denied.json()) == FORBIDDEN


def test_a_revoked_primary_contact_is_no_longer_presented(
    client: TestClient,  # noqa: F811
    blueprints: sessionmaker[Session],  # noqa: F811
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
    dave: uuid.UUID,
) -> None:
    client.patch(admin_url, headers=alice, json={"primary_contact_membership_id": str(dave)})
    with blueprints() as db:
        db.execute(
            update(Membership)
            .where(Membership.id == dave)
            .values(status="revoked", revoked_at=Membership.created_at)
        )
        db.commit()

    out = client.get(admin_url, headers=alice).json()
    assert out["primary_contact"] is None
    assert "primary_contact" in out["completeness"]["missing"]
    assert [p["membership_id"] for p in out["people"]] != [] and str(dave) not in {
        p["membership_id"] for p in out["people"]
    }
    # And a revoked Membership can't be chosen again.
    again = client.patch(
        admin_url, headers=alice, json={"primary_contact_membership_id": str(dave)}
    )
    assert again.status_code == 422


def test_completeness_follows_the_saved_details(
    client: TestClient,  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
) -> None:
    out = client.patch(
        admin_url,
        headers=alice,
        json={
            "legal_name": "Alpha LLC",
            "industry": "Retail",
            "employee_count": 12,
            "company_summary": "Two shops in Dubai.",
            "licensing": {"location": "difc"},
            "policies_exist": "no",
            "hr_support": "none",
            "primary_contact_membership_id": str(seed.alice_membership_a),
        },
    ).json()
    # The website and the notes are optional context: complete without them.
    assert out["completeness"] == {"complete": True, "missing": []}


def test_the_canonical_context_matches_the_api_view(
    client: TestClient,  # noqa: F811
    blueprints: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
    dave: uuid.UUID,
) -> None:
    out = client.patch(
        admin_url,
        headers=alice,
        json={
            "website_url": "alpha.example",
            "company_summary": SUMMARY,
            "policies_exist": "yes",
            "hr_support": "mixed",
            "primary_contact_membership_id": str(dave),
        },
    ).json()
    alice_context = AuthenticatedCompanyContext(
        user_id=seed.alice,
        company_id=seed.company_a,
        membership_id=seed.alice_membership_a,
        identity_id=seed.alice_identity,
        role="company_admin",
    )
    with blueprints() as db:
        context = load_company_blueprint_context(
            CompanyScope(session=db, company_id=seed.company_a), alice_context
        )
    assert context.company_display_name == out["company_name"] == "Company A"
    assert (context.website_url, context.company_summary) == ("https://alpha.example", SUMMARY)
    assert (context.policies_exist, context.hr_support) == ("yes", "mixed")
    assert context.primary_contact is not None and context.primary_contact.membership_id == dave
    assert not context.primary_contact.is_current_user
    assert context.current_user.membership_id == seed.alice_membership_a
    assert context.current_user.user_id == seed.alice
    assert context.current_user.role == "company_admin"
    assert context.jurisdiction.guidance_allowed is False
    assert list(context.missing) == out["completeness"]["missing"]
    # Nothing identity-provider-specific is reachable from the context.
    assert "alice-subject" not in repr(context) and TEST_COGNITO_ISSUER not in repr(context)


def test_another_company_can_neither_read_nor_write_the_context(
    client: TestClient,  # noqa: F811
    blueprints: sessionmaker[Session],  # noqa: F811
    seed: SeedData,
    alice: dict[str, str],  # noqa: F811
    admin_url: str,
) -> None:
    other = f"/companies/{seed.company_b}/blueprint"
    for response in (
        client.get(other, headers=alice),
        client.patch(other, headers=alice, json={"company_summary": "Taken over"}),
        client.patch(
            other,
            headers=alice,
            json={"primary_contact_membership_id": str(seed.alice_membership_a)},
        ),
    ):
        assert (response.status_code, response.json()) == FORBIDDEN
    with blueprints() as db:
        assert (
            db.scalar(select(CompanyBlueprint).where(CompanyBlueprint.company_id == seed.company_b))
            is None
        )
