"""Knowledge-bundle configuration, startup and repository hygiene (M2-NEW-04).

- The bundle path and its pinned SHA-256 are set together (absolute path,
  lowercase hex pin), or not at all.
- The application starts without knowledge (the runtime answers "bundle
  unavailable"), loads a valid pinned bundle and logs its identity and both
  digests (never content), and refuses to start on a missing, changed or
  invalid file. Synthetic or development knowledge never runs in production.
- Nothing serves the knowledge: no API route, no web asset. No private
  knowledge bundle, compile mapping, validation report, Word document or
  workbook is ever tracked in this repository (it is public), their names
  are ignored by git, and neither the compiler nor its test package is part
  of the API image.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import iter_route_contexts
from pydantic import ValidationError

from app.core.config import Settings
from app.knowledge.bundle import SCHEMA, KnowledgeBundleError
from app.main import create_app, load_knowledge

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]
DEV_SECRET = "knowledge-bundle-test-development-secret-0123456789"
# Fictional wording from the synthetic package that must never reach a log.
WORDING = ("Example Reminder", "fictional", "Confirm the jurisdiction before anything")


def make_settings(**values: Any) -> Settings:
    values.setdefault("heroos_env", "development")
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "values",
    [
        {"heroos_knowledge_bundle_path": Path("/srv/knowledge.json")},
        {"heroos_knowledge_bundle_sha256": "a" * 64},
        {
            "heroos_knowledge_bundle_path": Path("relative.json"),
            "heroos_knowledge_bundle_sha256": "a" * 64,
        },
        {
            "heroos_knowledge_bundle_path": Path("/srv/knowledge.json"),
            "heroos_knowledge_bundle_sha256": "A" * 64,
        },
    ],
)
def test_incomplete_or_malformed_knowledge_settings_are_refused(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**values)


def test_no_bundle_means_no_knowledge(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    assert load_knowledge(make_settings()) is None
    assert "Approved knowledge not installed" in caplog.text


def test_a_pinned_bundle_loads_and_logs_its_identity_not_its_content(
    bundle_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    pin = hashlib.sha256(bundle_file.read_bytes()).hexdigest()
    bundle = load_knowledge(
        make_settings(heroos_knowledge_bundle_path=bundle_file, heroos_knowledge_bundle_sha256=pin)
    )
    assert bundle is not None
    assert f"runtime_bundle_digest={bundle.runtime_digest}" in caplog.text
    assert f"source_package_digest={bundle.source_package_digest}" in caplog.text
    assert not any(words in caplog.text for words in WORDING)


def test_synthetic_knowledge_never_loads_in_production(bundle_file: Path) -> None:
    pin = hashlib.sha256(bundle_file.read_bytes()).hexdigest()
    config = make_settings(
        heroos_knowledge_bundle_path=bundle_file, heroos_knowledge_bundle_sha256=pin
    )
    config.heroos_env = "production"
    with pytest.raises(KnowledgeBundleError) as refused:
        load_knowledge(config)
    assert refused.value.code == "synthetic_in_production"


def _import_app(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    clean_env = {
        name: value for name, value in os.environ.items() if not name.startswith("HEROOS_")
    }
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=API_ROOT,
        env={
            **clean_env,
            "HEROOS_ENV": "development",
            "HEROOS_AUTH_PROVIDER": "development",
            "HEROOS_DEV_AUTH_SECRET": DEV_SECRET,
            **env,
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_without_knowledge_the_application_starts() -> None:
    result = _import_app({})
    assert result.returncode == 0, result.stderr
    assert "Approved knowledge not installed" in result.stdout + result.stderr


def test_the_application_starts_with_valid_knowledge(bundle_file: Path) -> None:
    pin = hashlib.sha256(bundle_file.read_bytes()).hexdigest()
    result = _import_app(
        {"HEROOS_KNOWLEDGE_BUNDLE_PATH": str(bundle_file), "HEROOS_KNOWLEDGE_BUNDLE_SHA256": pin}
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert "Approved knowledge loaded" in output and "provenance=synthetic" in output
    assert not any(words in output for words in WORDING)


@pytest.mark.parametrize("problem", ["missing", "changed", "half"])
def test_a_configured_but_unusable_bundle_stops_startup(
    bundle_file: Path, tmp_path: Path, problem: str
) -> None:
    pin = hashlib.sha256(bundle_file.read_bytes()).hexdigest()
    env = {"HEROOS_KNOWLEDGE_BUNDLE_PATH": str(bundle_file), "HEROOS_KNOWLEDGE_BUNDLE_SHA256": pin}
    if problem == "missing":
        env["HEROOS_KNOWLEDGE_BUNDLE_PATH"] = "/nonexistent/knowledge.json"
        refusal = "knowledge bundle refused: unreadable"
    elif problem == "changed":
        changed = tmp_path / "changed.json"
        data = json.loads(bundle_file.read_bytes())
        data["runtime"]["units"][0]["title"] = "Edited after approval"
        changed.write_text(json.dumps(data))
        env["HEROOS_KNOWLEDGE_BUNDLE_PATH"] = str(changed)
        refusal = "knowledge bundle refused: checksum_mismatch"
    else:
        del env["HEROOS_KNOWLEDGE_BUNDLE_PATH"]
        refusal = "must be set"
    result = _import_app(env)
    assert result.returncode != 0
    assert refusal in result.stderr
    assert "Edited after approval" not in result.stderr + result.stdout


# --- nothing serves the knowledge -------------------------------------------------------


def test_no_route_serves_knowledge() -> None:
    app = create_app(make_settings())
    paths = [
        context.path for context in iter_route_contexts(app.routes) if hasattr(context, "path")
    ]
    assert paths
    assert not any("knowledge" in path for path in paths)


def test_the_web_app_never_references_the_knowledge_bundle() -> None:
    web = REPO_ROOT / "apps" / "web" / "src"
    for path in web.rglob("*"):
        if path.is_file() and path.suffix in (".ts", ".tsx", ".js", ".mjs", ".json"):
            text = path.read_text(errors="replace")
            assert "heroos.knowledge-bundle" not in text, path
            assert "private-knowledge" not in text, path


# --- repository hygiene ---------------------------------------------------------------------


def _repository_files() -> list[Path]:
    output = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        capture_output=True,
        check=True,
    ).stdout.decode()
    return [REPO_ROOT / name for name in output.split("\0") if name]


def test_no_knowledge_bundle_mapping_report_or_source_document_is_in_the_repository() -> None:
    offenders = []
    for path in _repository_files():
        if path.suffix.lower() in (".docx", ".doc", ".xlsx", ".xlsm", ".xls"):
            offenders.append(path)
        if path.suffix != ".json" or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if SCHEMA in text or "heroos.knowledge-mapping/" in text:
            offenders.append(path)
    assert offenders == []


@pytest.mark.parametrize(
    "name",
    [
        "disciplinary-knowledge.private-knowledge.json",
        "disciplinary.private-knowledge-mapping.json",
        "private-knowledge-bundles/any.json",
        "knowledge-reports/validation-report.md",
        "sources/example-conditions.xlsx",
        "sources/old.xlsm",
    ],
)
def test_private_knowledge_names_are_ignored_by_git(name: str) -> None:
    ignored = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--no-index", name], check=False
    )
    assert ignored.returncode == 0, name


def test_the_compiler_and_its_test_package_are_not_part_of_the_api_image() -> None:
    dockerfile = (API_ROOT / "Dockerfile").read_text()
    copied = [line.split()[-2] for line in dockerfile.splitlines() if line.startswith("COPY")]
    assert not any("scripts" in source or "tests" in source for source in copied)
    assert not any(
        SCHEMA in path.read_text(errors="replace") for path in (API_ROOT / "app").rglob("*.json")
    )
