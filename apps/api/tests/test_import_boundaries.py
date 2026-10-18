"""Structural boundaries of M1-10B (ADR-008) and M1-10C, checked on the source and the app.

- Only the operator CLI may reach the identity provisioning and Company
  registration code.
- The application's mutating HTTP routes are exactly: the administrator-only
  Blueprint update, founder self-registration and the administrator-only
  workflow writes (M2-01 Case creation and answer save, M2-03 pathway and
  transitions, M2-04 decision records and corrections). No request can
  grant access to an existing Company, provision anyone into one, assign a
  role, suspend, revoke or confirm a jurisdiction, and nothing deletes.
- Founder self-registration is the only route an authenticated identity that
  HeroOS has not provisioned can reach; every other API route resolves an
  active HeroOS User first.
"""

import ast
from pathlib import Path

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from app.api.onboarding import require_self_registration
from app.auth.dependencies import get_current_user, get_verified_identity, require_company_admin
from app.core.config import Settings
from app.main import create_app
from app.tenancy.dependencies import get_company_admin_scope

API_ROOT = Path(__file__).resolve().parents[1]
APP = API_ROOT / "app"

# (method, path) of every route that may change state.
ADMIN_BLUEPRINT_UPDATE = ("PATCH", "/companies/{company_id}/blueprint")
FOUNDER_REGISTRATION = ("POST", "/company-registrations")
WORKFLOW_CASE_CREATE = ("POST", "/companies/{company_id}/workflows/{workflow_key}/cases")
WORKFLOW_ANSWERS_SAVE = (
    "PUT",
    "/companies/{company_id}/cases/{case_id}/workflow/steps/{step_key}/answers",
)
# M2-03: the employer's pathway choice and stage transitions.
WORKFLOW_PATHWAY = ("POST", "/companies/{company_id}/cases/{case_id}/workflow/progression/pathway")
WORKFLOW_TRANSITION = (
    "POST",
    "/companies/{company_id}/cases/{case_id}/workflow/progression/transitions",
)
# M2-04: employer decision records and their corrections (never an authorization).
WORKFLOW_DECISION = ("POST", "/companies/{company_id}/cases/{case_id}/decisions")
WORKFLOW_DECISION_CORRECTION = (
    "POST",
    "/companies/{company_id}/cases/{case_id}/decisions/{record_id}/corrections",
)
ADMIN_ROUTES = {
    ADMIN_BLUEPRINT_UPDATE,
    WORKFLOW_CASE_CREATE,
    WORKFLOW_ANSWERS_SAVE,
    WORKFLOW_PATHWAY,
    WORKFLOW_TRANSITION,
    WORKFLOW_DECISION,
    WORKFLOW_DECISION_CORRECTION,
}
# M2-04 reads: decision records, their categories and the case history are for
# administrators only, like every Disciplinary read.
ADMIN_READS = {
    ("GET", "/companies/{company_id}/workflows/{workflow_key}/decision-categories"),
    ("GET", "/companies/{company_id}/cases/{case_id}/decisions"),
    ("GET", "/companies/{company_id}/cases/{case_id}/history"),
}
MUTATING_ROUTES = {*ADMIN_ROUTES, FOUNDER_REGISTRATION}


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _app_routes() -> list[RouteContext]:
    """Every API route, including those of included routers.

    FastAPI wraps an included router in one opaque entry of ``app.routes``, so
    iterating ``app.routes`` alone would never see the Company routes.
    """
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="development",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
    )
    return [
        route
        for route in iter_route_contexts(create_app(settings).routes)
        if isinstance(route.original_route, APIRoute)
    ]


def _dependency_calls(dependant: Dependant) -> set[object]:
    calls: set[object] = set()
    for sub in dependant.dependencies:
        calls.add(sub.call)
        calls |= _dependency_calls(sub)
    return calls


def test_only_the_identity_package_and_cli_reach_provisioning_code() -> None:
    offenders = {
        str(path.relative_to(API_ROOT))
        for path in APP.rglob("*.py")
        if "identity" not in path.relative_to(APP).parts[:1]
        and any(name.startswith(("app.identity", "scripts")) for name in _imports(path))
    }
    assert offenders == set()


def test_operator_scope_is_used_only_by_the_operator_services_and_cli() -> None:
    users = {
        str(path.relative_to(API_ROOT))
        for path in (*APP.rglob("*.py"), *(API_ROOT / "scripts").rglob("*.py"))
        if "app.identity.operator" in _imports(path)
    }
    assert users == {
        "app/identity/service.py",
        "app/identity/companies.py",
        "scripts/manage_identities.py",
    }


def test_the_only_mutating_routes_are_admin_routes_and_founder_registration() -> None:
    mutating = {
        (method, route.path): route
        for route in _app_routes()
        for method in route.methods or set()
        if method not in ("GET", "HEAD")
    }
    assert set(mutating) == MUTATING_ROUTES

    for route in ADMIN_ROUTES:
        admin = _dependency_calls(mutating[route].dependant)
        # Role check at authorization and again inside the write transaction.
        assert require_company_admin in admin, route
        assert get_company_admin_scope in admin, route

    reads = {
        (method, route.path): route for route in _app_routes() for method in route.methods or set()
    }
    for route in ADMIN_READS:
        admin = _dependency_calls(reads[route].dependant)
        assert require_company_admin in admin, route
        assert get_company_admin_scope in admin, route

    registration = _dependency_calls(mutating[FOUNDER_REGISTRATION].dependant)
    # A verified credential and the activation switch; never a client claim.
    assert get_verified_identity in registration
    assert require_self_registration in registration


def test_only_founder_registration_accepts_an_unprovisioned_identity() -> None:
    without_user = {
        route.path
        for route in _app_routes()
        if get_current_user not in _dependency_calls(route.dependant)
    }
    assert without_user == {"/health", "/company-registrations"}


def test_no_route_manages_access_to_existing_companies() -> None:
    paths = {route.path for route in _app_routes()}
    assert paths == {
        "/health",
        "/company-registrations",
        "/me/companies",
        "/companies/{company_id}",
        "/companies/{company_id}/membership",
        "/companies/{company_id}/blueprint",
        "/companies/{company_id}/cases",
        "/companies/{company_id}/cases/{case_id}",
        "/companies/{company_id}/workflows/{workflow_key}/cases",
        "/companies/{company_id}/cases/{case_id}/workflow",
        "/companies/{company_id}/cases/{case_id}/workflow/steps/{step_key}/answers",
        "/companies/{company_id}/cases/{case_id}/workflow/progression/pathway",
        "/companies/{company_id}/cases/{case_id}/workflow/progression/transitions",
        "/companies/{company_id}/workflows/{workflow_key}/decision-categories",
        "/companies/{company_id}/cases/{case_id}/decisions",
        "/companies/{company_id}/cases/{case_id}/decisions/{record_id}/corrections",
        "/companies/{company_id}/cases/{case_id}/history",
    }


def test_the_rules_never_read_employer_decision_records() -> None:
    """M2-04: a record is the employer's account, never a workflow authorization.

    The intake rules, the progression engine and the answers they read can't
    reach decision records or the history built from them, so no record can
    start or complete a stage, release a hold or count as a prerequisite.
    """
    rule_modules = [
        APP / "workflows" / "answers.py",
        APP / "workflows" / "conditions.py",
        APP / "workflows" / "intake.py",
        APP / "workflows" / "progress.py",
        *(APP / "workflows" / "progression").rglob("*.py"),
    ]
    forbidden = (
        "app.workflows.decisions",
        "app.workflows.timeline",
        "app.api.decisions",
        "app.db.models.workflow.WorkflowDecisionRecord",
        "app.db.models.WorkflowDecisionRecord",
    )
    for path in rule_modules:
        imported = _imports(path)
        assert not any(name.startswith(forbidden) for name in imported), path
        assert "decision_record" not in path.read_text(encoding="utf-8"), path
