"""Template-bundle configuration and repository hygiene (M2-04C).

- The bundle path and its pinned SHA-256 are set together (absolute path,
  lowercase hex pin), or not at all, and never without a rule bundle.
- The application starts without templates (previews unavailable), loads a
  valid pinned bundle that fits the installed rules, and refuses to start on a
  changed or mismatched file; refusals name a fixed code, never wording.
  Synthetic or provisional templates never run in production.
- No private template bundle, converter mapping or Word document is ever
  tracked in this repository (it is public), their names are ignored by git,
  and the synthetic test bundle isn't part of the API image.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.documents.bundle import SCHEMA, TemplateBundleError
from app.main import load_rule_bundle, load_templates
from tests.fixtures import (
    SYNTHETIC_BUNDLE,
    SYNTHETIC_TEMPLATES,
    synthetic_bundle_pin,
    synthetic_templates_pin,
)

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
DEV_SECRET = "template-bundle-test-development-secret-0123456789"
RULES = {
    "heroos_rule_bundle_path": SYNTHETIC_BUNDLE,
    "heroos_rule_bundle_sha256": synthetic_bundle_pin(),
}
TEMPLATES = {
    "heroos_template_bundle_path": SYNTHETIC_TEMPLATES,
    "heroos_template_bundle_sha256": synthetic_templates_pin(),
}
# Wording from the synthetic bundle that must never reach a log or an error.
WORDING = ("Synthetic test letter", "Test instructions", "Recipient's name", "check-in note")


def make_settings(**values: Any) -> Settings:
    values.setdefault("heroos_env", "development")
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "values",
    [
        {**RULES, "heroos_template_bundle_path": SYNTHETIC_TEMPLATES},
        {**RULES, "heroos_template_bundle_sha256": "a" * 64},
        {
            **RULES,
            "heroos_template_bundle_path": Path("relative.json"),
            "heroos_template_bundle_sha256": "a" * 64,
        },
        {**RULES, "heroos_template_bundle_path": SYNTHETIC_TEMPLATES,
         "heroos_template_bundle_sha256": "A" * 64},
        # Templates are bound to the rules' stages: never without them.
        TEMPLATES,
    ],
)  # fmt: skip
def test_incomplete_or_malformed_template_settings_are_refused(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**values)


def test_no_bundle_means_no_templates(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    settings = make_settings(**RULES)
    assert load_templates(settings, load_rule_bundle(settings)) is None
    assert "Document templates not installed" in caplog.text


def test_a_pinned_bundle_loads_with_its_rules() -> None:
    settings = make_settings(**RULES, **TEMPLATES)
    bundle = load_templates(settings, load_rule_bundle(settings))
    assert bundle is not None and bundle.version == "synthetic.1"


def test_synthetic_templates_never_load_in_production() -> None:
    settings = make_settings(**RULES, **TEMPLATES).model_copy(update={"heroos_env": "production"})
    with pytest.raises(TemplateBundleError) as refused:
        load_templates(settings, None)
    assert refused.value.code == "synthetic_in_production"


def _import_app(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    clean_env = {
        name: value for name, value in os.environ.items() if not name.startswith("HEROOS_")
    }
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=API_ROOT,
        env={
            name: value
            for name, value in {
                **clean_env,
                "HEROOS_ENV": "development",
                "HEROOS_AUTH_PROVIDER": "development",
                "HEROOS_DEV_AUTH_SECRET": DEV_SECRET,
                "HEROOS_RULE_BUNDLE_PATH": str(SYNTHETIC_BUNDLE),
                "HEROOS_RULE_BUNDLE_SHA256": synthetic_bundle_pin(),
                **env,
            }.items()
            # An empty value removes the variable (an unset rule bundle).
            if value != ""
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_without_templates_the_application_starts_healthy_and_previews_are_unavailable() -> None:
    """Absent (not configured) is a normal state: the API runs, previews are off."""
    result = _import_app({})
    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert "Workflow progression rules loaded" in output
    assert "Document templates not installed" in output


@pytest.mark.parametrize(
    ("env", "refusal"),
    [
        # Configured but missing: never silently treated as "not installed".
        (
            {"HEROOS_TEMPLATE_BUNDLE_PATH": "/nonexistent/templates.json",
             "HEROOS_TEMPLATE_BUNDLE_SHA256": "a" * 64},
            "template bundle refused: unreadable",
        ),
        # Half configured.
        ({"HEROOS_TEMPLATE_BUNDLE_SHA256": "a" * 64}, "must be set together"),
        # Templates without the rules they are bound to.
        (
            {"HEROOS_TEMPLATE_BUNDLE_PATH": "TEMPLATES", "HEROOS_RULE_BUNDLE_PATH": "",
             "HEROOS_RULE_BUNDLE_SHA256": ""},
            "requires HEROOS_RULE_BUNDLE_PATH",
        ),
    ],
)  # fmt: skip
def test_a_configured_but_unusable_template_bundle_stops_startup(
    env: dict[str, str], refusal: str
) -> None:
    """Configured is a promise: missing, partial or rule-less templates refuse to start."""
    env = {
        key: str(SYNTHETIC_TEMPLATES) if value == "TEMPLATES" else value
        for key, value in env.items()
    }
    if env.get("HEROOS_TEMPLATE_BUNDLE_PATH") == str(SYNTHETIC_TEMPLATES):
        env["HEROOS_TEMPLATE_BUNDLE_SHA256"] = synthetic_templates_pin()
    result = _import_app(env)
    assert result.returncode != 0
    assert refusal in result.stderr
    assert not any(words in result.stderr + result.stdout for words in WORDING)


def test_the_application_starts_with_valid_templates_and_logs_no_wording() -> None:
    result = _import_app(
        {
            "HEROOS_TEMPLATE_BUNDLE_PATH": str(SYNTHETIC_TEMPLATES),
            "HEROOS_TEMPLATE_BUNDLE_SHA256": synthetic_templates_pin(),
        }
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert "Document templates loaded" in output
    assert "approval=provisional" in output
    assert not any(words in output for words in WORDING)


def test_the_application_refuses_to_start_on_a_changed_bundle(tmp_path: Path) -> None:
    changed = tmp_path / "templates.json"
    data = json.loads(SYNTHETIC_TEMPLATES.read_bytes())
    data["templates"][0]["title"] = "Edited after approval"
    changed.write_text(json.dumps(data))
    result = _import_app(
        {
            "HEROOS_TEMPLATE_BUNDLE_PATH": str(changed),
            "HEROOS_TEMPLATE_BUNDLE_SHA256": synthetic_templates_pin(),
        }
    )
    assert result.returncode != 0
    assert "template bundle refused: checksum_mismatch" in result.stderr
    assert "Edited after approval" not in result.stderr + result.stdout


def test_the_application_refuses_templates_written_for_other_rules(tmp_path: Path) -> None:
    other = tmp_path / "templates.json"
    data = json.loads(SYNTHETIC_TEMPLATES.read_bytes())
    data["rule_bundle"]["versions"] = ["synthetic.2"]
    other.write_text(json.dumps(data))
    result = _import_app(
        {
            "HEROOS_TEMPLATE_BUNDLE_PATH": str(other),
            "HEROOS_TEMPLATE_BUNDLE_SHA256": hashlib.sha256(other.read_bytes()).hexdigest(),
        }
    )
    assert result.returncode != 0
    assert "template bundle refused: rule_bundle_mismatch" in result.stderr


def _repository_files() -> list[Path]:
    output = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--cached", "--others",
         "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout.decode()  # fmt: skip
    return [REPO_ROOT / name for name in output.split("\0") if name]


def test_no_private_template_bundle_or_word_document_is_in_the_repository() -> None:
    bundles: dict[str, str] = {}
    word = []
    for path in _repository_files():
        if path.suffix.lower() in (".docx", ".docm", ".dotx", ".dotm", ".doc"):
            word.append(path)
        if path.suffix != ".json" or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if SCHEMA in text or "heroos.template-mapping/" in text:
            bundles[str(path.relative_to(REPO_ROOT))] = json.loads(text).get("provenance")
    assert bundles == {
        "apps/api/tests/fixtures/template_bundles/synthetic-disciplinary.json": "synthetic"
    }
    assert word == []


@pytest.mark.parametrize(
    "name",
    [
        "disciplinary.private-templates.json",
        "EX-01.private-mapping.json",
        "apps/api/private-template-bundles/any.json",
        "template-review-packs/EX-01.md",
        "source-documents/EX-01 example letter.docx",
        "EX-02.docm",
        "old.doc",
    ],
)
def test_private_template_names_are_ignored_by_git(name: str) -> None:
    ignored = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--no-index", name], check=False
    )
    assert ignored.returncode == 0, name


def test_the_synthetic_templates_are_not_part_of_the_api_image() -> None:
    dockerfile = (API_ROOT / "Dockerfile").read_text()
    copied = [line.split()[-2] for line in dockerfile.splitlines() if line.startswith("COPY")]
    assert not any("tests" in source for source in copied)
    assert not any(
        SCHEMA in path.read_text(errors="replace") for path in (API_ROOT / "app").rglob("*.json")
    )


def test_the_validation_tool_prints_the_pin_and_counts_never_wording(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import template_bundle

    assert template_bundle.main(["validate", str(SYNTHETIC_TEMPLATES), str(SYNTHETIC_BUNDLE)]) == 0
    printed = capsys.readouterr().out
    assert f"HEROOS_TEMPLATE_BUNDLE_SHA256={synthetic_templates_pin()}" in printed
    assert (
        "TEST-01 v1 (letter, review=employer, uae_federal): 6 fields, 1 choices, 11 blocks"
        in printed
    )
    assert not any(words in printed for words in WORDING)
    assert "synthetic.check_in_note" not in printed
    args = ["validate", str(SYNTHETIC_TEMPLATES), str(SYNTHETIC_BUNDLE), "--production"]
    assert template_bundle.main(args) == 1
    assert "synthetic_in_production" in capsys.readouterr().err
    assert template_bundle.main(["validate", "/nonexistent.json", str(SYNTHETIC_BUNDLE)]) == 1
