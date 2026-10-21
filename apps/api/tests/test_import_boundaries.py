"""Structural boundaries of M1-10B (ADR-008) and M1-10C, checked on the source and the app.

- Only the operator CLI may reach the identity provisioning and Company
  registration code.
- The application's mutating HTTP routes are exactly: the administrator-only
  Blueprint update, founder self-registration and the administrator-only
  workflow writes (M2-01 Case creation and answer save, M2-03 pathway and
  transitions, M2-04 decision records and corrections). No request can
  grant access to an existing Company, provision anyone into one, assign a
  role, suspend, revoke or confirm a jurisdiction, and nothing deletes.
- The only other POST is the M2-04C document preview: administrator-only, in
  a transaction that can't write (like every document route), and it never
  reads employer decision records.
- The Hannah AI demo's message POST writes nothing either: administrator-only,
  a read-only transaction, the demo switch, and the assistant package
  can't reach the database or the workflow engine.
- So does Ask HeroOS's AI gateway (M2-NEW-05) at Company level: the same
  administrator chain in a read-only transaction; the gateway package can't
  reach the database, the workflow engine or the network (only the provider
  adapter talks to its fixed endpoint), and no route serves the knowledge.
- Founder self-registration is the only route an authenticated identity that
  HeroOS has not provisioned can reach; every other API route resolves an
  active HeroOS User first.
"""

import ast
from pathlib import Path

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from app.api.assistant import require_hannah_demo
from app.api.onboarding import require_self_registration
from app.auth.dependencies import get_current_user, get_verified_identity, require_company_admin
from app.core.config import Settings
from app.main import create_app
from app.tenancy.dependencies import get_company_admin_read_scope, get_company_admin_scope

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
# M2-04C: document templates and previews. POST only so personal details never
# travel in a URL; nothing is written (a read-only transaction).
DOCUMENT_PREVIEW = (
    "POST",
    "/companies/{company_id}/cases/{case_id}/documents/{template_key}/preview",
)
DOCUMENT_ROUTES = {
    ("GET", "/companies/{company_id}/cases/{case_id}/documents"),
    ("GET", "/companies/{company_id}/cases/{case_id}/documents/{template_key}"),
    DOCUMENT_PREVIEW,
}
# The Hannah AI demo: a status read and a message POST that changes nothing.
ASSISTANT_MESSAGE = ("POST", "/companies/{company_id}/cases/{case_id}/assistant/messages")
ASSISTANT_ROUTES = {
    ("GET", "/companies/{company_id}/cases/{case_id}/assistant"),
    ASSISTANT_MESSAGE,
}
# Ask HeroOS's AI gateway (M2-NEW-05): Company level, no Case, nothing written.
GATEWAY_MESSAGE = ("POST", "/companies/{company_id}/assistant/messages")
GATEWAY_ROUTES = {("GET", "/companies/{company_id}/assistant"), GATEWAY_MESSAGE}


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
        and (method, route.path) not in (DOCUMENT_PREVIEW, ASSISTANT_MESSAGE, GATEWAY_MESSAGE)
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


def test_document_routes_are_admin_only_and_cannot_write() -> None:
    routes = {
        (method, route.path): route for route in _app_routes() for method in route.methods or set()
    }
    found = {key for key in routes if "/documents" in key[1]}
    assert found == DOCUMENT_ROUTES
    for key in DOCUMENT_ROUTES:
        calls = _dependency_calls(routes[key].dependant)
        assert require_company_admin in calls, key
        # The administrator scope, in a transaction that refuses every write.
        assert get_company_admin_read_scope in calls, key
        assert get_company_admin_scope in calls, key


def test_assistant_routes_are_admin_only_switched_and_cannot_write() -> None:
    routes = {
        (method, route.path): route for route in _app_routes() for method in route.methods or set()
    }
    found = {key for key in routes if "/assistant" in key[1]}
    assert found == ASSISTANT_ROUTES | GATEWAY_ROUTES
    for key in ASSISTANT_ROUTES | GATEWAY_ROUTES:
        calls = _dependency_calls(routes[key].dependant)
        assert require_company_admin in calls, key
        assert get_company_admin_read_scope in calls, key
        assert get_company_admin_scope in calls, key
    assert require_hannah_demo in _dependency_calls(routes[ASSISTANT_MESSAGE].dependant)
    # The gateway is not the demo: its own switch and prerequisites, never the demo's.
    assert require_hannah_demo not in _dependency_calls(routes[GATEWAY_MESSAGE].dependant)


def test_the_assistant_cannot_reach_the_database_or_the_workflow() -> None:
    """The model's text can't become a workflow action: no path from the assistant package."""
    for path in (APP / "assistant").rglob("*.py"):
        assert not any(
            name.startswith(("app.repositories", "app.db", "app.workflows", "sqlalchemy"))
            for name in _imports(path)
        ), path
    imported = _imports(APP / "api" / "assistant.py")
    assert not any(
        name.startswith(("app.workflows", "app.api.workflows", "app.api.decisions", "app.db"))
        for name in imported
    )
    # The gateway's route doesn't even look a Case up: Company context only.
    imported = _imports(APP / "api" / "gateway.py")
    assert not any(
        name.startswith(
            ("app.workflows", "app.api.workflows", "app.api.decisions", "app.db",
             "app.repositories", "app.knowledge")
        )
        for name in imported
    )  # fmt: skip


def test_the_gateway_never_reaches_the_web_or_source_documents() -> None:
    """M2-NEW-05: no open-web research, URL fetching, browsing or raw-source reading.

    Only the provider adapter (``app.assistant.groq``) opens a connection, to
    its fixed endpoint. The gateway itself imports no network, document or
    evaluation machinery, and its instructions name no tool.
    """
    forbidden = (
        "urllib", "httpx", "requests", "socket", "http.client", "aiohttp", "ssl", "scripts",
        "zipfile", "xml", "openpyxl", "docx", "subprocess", "app.assistant.groq",
    )  # fmt: skip
    for path in (APP / "assistant" / "gateway").rglob("*.py"):
        imported = _imports(path)
        assert not any(name.startswith(forbidden) for name in imported), path
        source = path.read_text(encoding="utf-8")
        assert "eval(" not in source and "exec(" not in source, path
        assert '"tools"' not in source and "tool_choice" not in source, path


def test_documents_never_read_employer_decision_records() -> None:
    """M2-04C: a record can't make a template available or fill one in."""
    modules = [*(APP / "documents").rglob("*.py"), APP / "api" / "documents.py"]
    forbidden = (
        "app.workflows.decisions",
        "app.workflows.timeline",
        "app.api.decisions",
        "app.db.models.workflow.WorkflowDecisionRecord",
        "app.db.models.WorkflowDecisionRecord",
    )
    for path in modules:
        imported = _imports(path)
        assert not any(name.startswith(forbidden) for name in imported), path
        assert "decision_record" not in path.read_text(encoding="utf-8"), path
    # The engine itself reads no database at all.
    for path in (APP / "documents").rglob("*.py"):
        assert not any(
            name.startswith(("app.repositories", "app.db", "sqlalchemy")) for name in _imports(path)
        ), path


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
        "/companies/{company_id}/cases/{case_id}/documents",
        "/companies/{company_id}/cases/{case_id}/documents/{template_key}",
        "/companies/{company_id}/cases/{case_id}/documents/{template_key}/preview",
        "/companies/{company_id}/cases/{case_id}/assistant",
        "/companies/{company_id}/cases/{case_id}/assistant/messages",
        "/companies/{company_id}/assistant",
        "/companies/{company_id}/assistant/messages",
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


def test_the_api_never_reads_word_documents() -> None:
    """M2-04C: converting Word templates is offline tooling (``scripts``), never the API's job.

    Only ``apps/api/app`` is in the API image; nothing in it may import the
    converter, the Word reader, or a ZIP or XML parser.
    """
    for path in APP.rglob("*.py"):
        imported = _imports(path)
        assert not any(
            name.startswith(("scripts", "zipfile", "xml", "lxml", "docx")) for name in imported
        ), path


def test_the_conversation_evaluation_is_pure_and_writes_nothing() -> None:
    """M2-NEW-06: the deterministic evaluation reads no database, calls no model and writes nothing.

    It may read the pure workflow definitions and rule machinery (conditions,
    definitions, predicates, the rule bundle) and the knowledge runtime, never a
    workflow write path, a repository, a route or a provider; and nothing in
    it executes text.
    """
    forbidden = (
        "app.db", "app.repositories", "app.tenancy", "app.api", "app.assistant", "app.auth",
        "app.documents", "app.storage", "sqlalchemy", "fastapi", "pydantic", "httpx", "urllib",
        "socket", "requests", "scripts", "openai", "groq", "anthropic", "subprocess",
    )  # fmt: skip
    allowed_workflows = {
        "app.workflows", "app.workflows.conditions", "app.workflows.definition",
        "app.workflows.progression", "app.workflows.progression.predicates",
        "app.workflows.progression.bundle", "app.workflows.progression.spec",
    }  # fmt: skip
    for path in (APP / "evaluation").rglob("*.py"):
        imported = _imports(path)
        assert not any(name.startswith(forbidden) for name in imported), path
        workflows = {n.rsplit(".", 1)[0] if n.count(".") > 2 else n for n in imported
                     if n.startswith("app.workflows")}  # fmt: skip
        assert workflows <= allowed_workflows | {n.rsplit(".", 1)[0] for n in allowed_workflows}, (
            path,
            workflows,
        )
        source = path.read_text(encoding="utf-8").replace("evaluate(", "").replace(
            "evaluate_conversation(", ""
        )  # fmt: skip
        assert "eval(" not in source and "exec(" not in source, path
    # The routes use only its token bound (no evaluation, rule or profile reaches an API module).
    for path in (APP / "api").rglob("*.py"):
        evaluation = {n for n in _imports(path) if n.startswith("app.evaluation")}
        assert evaluation <= {"app.evaluation.continuation",
                              "app.evaluation.continuation.MAX_TOKEN_CHARS"}, path  # fmt: skip


def test_the_knowledge_runtime_is_pure_and_offline() -> None:
    """M2-NEW-04: the runtime describes approved knowledge; it never acts or reaches out.

    It reads no database (no Case, no Company row: callers pass what they
    have), calls no model, opens no network connection and never parses
    source documents (that is the offline compiler in ``scripts``).
    """
    forbidden = (
        "app.db", "app.repositories", "app.tenancy", "app.api", "app.assistant", "sqlalchemy",
        "httpx", "urllib", "socket", "requests", "scripts", "zipfile", "xml", "openai", "groq",
        "anthropic",
    )  # fmt: skip
    for path in (APP / "knowledge").rglob("*.py"):
        imported = _imports(path)
        assert not any(name.startswith(forbidden) for name in imported), path
        assert "eval(" not in path.read_text(encoding="utf-8").replace("evaluate(", ""), path


def test_no_route_or_api_module_serves_the_knowledge_runtime() -> None:
    """The knowledge is server-side only: no route serves it.

    The AI gateway (M2-NEW-05) composes it inside ``app.assistant.gateway``; no
    API module imports it, and the gateway's responses carry none of it
    (tests/auth/test_gateway_api.py).
    """
    assert not any("knowledge" in route.path for route in _app_routes())
    for path in (APP / "api").rglob("*.py"):
        assert not any(name.startswith("app.knowledge") for name in _imports(path)), path
