"""Rule-bundle configuration and repository hygiene (M2-03).

- The bundle path and its pinned SHA-256 are set together (absolute path,
  lowercase hex pin), or not at all.
- The application starts without a bundle (progression unavailable), loads a
  valid pinned bundle, and refuses to start on a changed file; refusals name a
  fixed code, never bundle content. Synthetic rules never run in production.
- No private bundle is ever tracked in this repository, private bundle names
  are ignored by git, and the synthetic test bundle isn't part of the API
  image (only ``apps/api/app`` is copied into it).
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import load_rule_bundle
from app.workflows.progression.bundle import SCHEMA, RuleBundleError
from tests.fixtures import SYNTHETIC_BUNDLE, synthetic_bundle_pin

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
DEV_SECRET = "rule-bundle-test-development-secret-0123456789"


def make_settings(**values: Any) -> Settings:
    values.setdefault("heroos_env", "development")
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "values",
    [
        {"heroos_rule_bundle_path": SYNTHETIC_BUNDLE},
        {"heroos_rule_bundle_sha256": "a" * 64},
        {"heroos_rule_bundle_path": Path("relative.json"), "heroos_rule_bundle_sha256": "a" * 64},
        {"heroos_rule_bundle_path": SYNTHETIC_BUNDLE, "heroos_rule_bundle_sha256": "A" * 64},
        {"heroos_rule_bundle_path": SYNTHETIC_BUNDLE, "heroos_rule_bundle_sha256": "a" * 63},
    ],
)
def test_incomplete_or_malformed_bundle_settings_are_refused(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**values)


def test_no_bundle_means_no_rules() -> None:
    assert load_rule_bundle(make_settings()) is None


def test_a_pinned_bundle_loads() -> None:
    settings = make_settings(
        heroos_rule_bundle_path=SYNTHETIC_BUNDLE, heroos_rule_bundle_sha256=synthetic_bundle_pin()
    )
    bundle = load_rule_bundle(settings)
    assert bundle is not None and bundle.version == "synthetic.1"


def test_synthetic_rules_never_load_in_production() -> None:
    settings = make_settings(
        heroos_rule_bundle_path=SYNTHETIC_BUNDLE, heroos_rule_bundle_sha256=synthetic_bundle_pin()
    ).model_copy(update={"heroos_env": "production"})
    with pytest.raises(RuleBundleError) as refused:
        load_rule_bundle(settings)
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


def test_the_application_starts_with_a_valid_bundle_and_logs_no_content() -> None:
    result = _import_app(
        {
            "HEROOS_RULE_BUNDLE_PATH": str(SYNTHETIC_BUNDLE),
            "HEROOS_RULE_BUNDLE_SHA256": synthetic_bundle_pin(),
        }
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert "Workflow progression rules loaded" in output
    assert "version=synthetic.1" in output
    assert "Test stage" not in output


def test_the_application_refuses_to_start_on_a_changed_bundle(tmp_path: Path) -> None:
    changed = tmp_path / "bundle.json"
    data = json.loads(SYNTHETIC_BUNDLE.read_bytes())
    data["notice"]["body"] = "Edited after approval."
    changed.write_text(json.dumps(data))
    result = _import_app(
        {
            "HEROOS_RULE_BUNDLE_PATH": str(changed),
            "HEROOS_RULE_BUNDLE_SHA256": synthetic_bundle_pin(),
        }
    )
    assert result.returncode != 0
    assert "rule bundle refused: checksum_mismatch" in result.stderr
    assert "Edited after approval" not in result.stderr + result.stdout


def _repository_files() -> list[Path]:
    output = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--cached", "--others",
         "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout.decode()  # fmt: skip
    return [REPO_ROOT / name for name in output.split("\0") if name]


def test_no_private_rule_bundle_is_in_the_repository() -> None:
    bundles: dict[str, str] = {}
    for path in _repository_files():
        if path.suffix != ".json" or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if SCHEMA not in text:
            continue
        bundles[str(path.relative_to(REPO_ROOT))] = json.loads(text).get("provenance")
    assert bundles == {
        "apps/api/tests/fixtures/rule_bundles/synthetic-disciplinary.json": "synthetic"
    }


@pytest.mark.parametrize(
    "name",
    ["disciplinary.private-bundle.json", "apps/api/private-rule-bundles/any.json"],
)
def test_private_bundle_names_are_ignored_by_git(name: str) -> None:
    ignored = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--no-index", name], check=False
    )
    assert ignored.returncode == 0, name


def test_the_synthetic_bundle_is_not_part_of_the_api_image() -> None:
    dockerfile = (API_ROOT / "Dockerfile").read_text()
    copied = [line.split()[-2] for line in dockerfile.splitlines() if line.startswith("COPY")]
    assert not any("tests" in source for source in copied)
    assert not any(
        SCHEMA in path.read_text(errors="replace") for path in (API_ROOT / "app").rglob("*.json")
    )


def test_the_validation_tool_prints_the_pin_and_counts_never_content(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import rule_bundle

    assert rule_bundle.main(["validate", str(SYNTHETIC_BUNDLE)]) == 0
    printed = capsys.readouterr().out
    assert f"HEROOS_RULE_BUNDLE_SHA256={synthetic_bundle_pin()}" in printed
    assert "uae_federal / less_serious: 3 stages, 5 checklist items, 7 rules" in printed
    assert "Test stage" not in printed and "test_check_in" not in printed
    assert rule_bundle.main(["validate", str(SYNTHETIC_BUNDLE), "--production"]) == 1
    assert "synthetic_in_production" in capsys.readouterr().err
