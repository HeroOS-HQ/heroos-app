"""Settings and startup for the deterministic evaluation (M2-NEW-06).

The profile and its pin are set together, an absolute path, and need the
shared continuation key; a bad profile stops startup; a profile that doesn't
fit the installed artifacts leaves evaluation unavailable (logged with fixed
codes, never content); production refuses synthetic or development profiles.
"""

import base64
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.evaluation.profile import ExecutionProfileError
from app.knowledge.bundle import KnowledgeBundle
from app.main import continuation_codec, load_evaluation
from tests.fixtures.evaluation import Artifacts, to_bytes

KEY = base64.urlsafe_b64encode(b"s" * 32).decode()


def settings(**values: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        **({"heroos_env": "development"} | values),
    )


def pinned(tmp_path: Path, data: dict[str, Any]) -> dict[str, Any]:
    path = tmp_path / "execution-profile.json"
    path.write_bytes(to_bytes(data))
    return {
        "heroos_execution_profile_path": path,
        "heroos_execution_profile_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "heroos_evaluation_continuation_key": KEY,
    }


def test_off_by_default() -> None:
    config = settings()
    assert config.heroos_execution_profile_path is None
    assert config.heroos_evaluation_continuation_key is None
    assert not continuation_codec(config).trusted


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"heroos_execution_profile_path": "/x.json"}, "set together"),
        (
            {
                "heroos_execution_profile_path": "x.json",
                "heroos_execution_profile_sha256": "a" * 64,
                "heroos_evaluation_continuation_key": KEY,
            },
            "absolute",
        ),
        (
            {
                "heroos_execution_profile_path": "/x.json",
                "heroos_execution_profile_sha256": "A" * 64,
                "heroos_evaluation_continuation_key": KEY,
            },
            "64 lowercase",
        ),
        (
            {
                "heroos_execution_profile_path": "/x.json",
                "heroos_execution_profile_sha256": "a" * 64,
            },
            "requires HEROOS_EVALUATION_CONTINUATION_KEY",
        ),
        ({"heroos_evaluation_continuation_key": "too-short"}, "at least 32"),
    ],
)
def test_settings_are_checked(values: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        settings(**values)


def test_the_shared_key_makes_the_continuation_trusted() -> None:
    assert continuation_codec(settings(heroos_evaluation_continuation_key=KEY)).trusted


def test_no_profile_leaves_evaluation_unavailable(bundle: KnowledgeBundle) -> None:
    snapshot = load_evaluation(settings(), bundle, None).snapshot()
    assert snapshot.availability("disciplinary") == "execution_profile_missing"


def test_a_profile_that_doesnt_fit_is_unavailable_and_logged_without_content(
    tmp_path: Path, artifacts: Artifacts, bundle: KnowledgeBundle, caplog: pytest.LogCaptureFixture
) -> None:
    # The installed knowledge is the fictional package alone: the profile was approved for
    # another runtime digest (and another rule bundle), so nothing runs stale.
    with caplog.at_level(logging.INFO):
        snapshot = load_evaluation(settings(**pinned(tmp_path, artifacts.profile)), bundle, None)
        snapshot = snapshot.snapshot()
    assert snapshot.availability("disciplinary") == "incompatible_versions"
    text = caplog.text
    assert "knowledge_digest_mismatch" in text and "synthetic-execution@synthetic.1" in text
    assert "fictional_cap" not in text and "EX-FED" not in text and KEY not in text


def test_a_bad_profile_stops_startup(tmp_path: Path, artifacts: Artifacts) -> None:
    values = pinned(tmp_path, artifacts.profile)
    values["heroos_execution_profile_sha256"] = "0" * 64
    with pytest.raises(ExecutionProfileError, match="checksum_mismatch"):
        load_evaluation(settings(**values), None, None)


def test_production_refuses_a_synthetic_profile(tmp_path: Path, artifacts: Artifacts) -> None:
    config = settings(**pinned(tmp_path, artifacts.profile))
    object.__setattr__(config, "heroos_env", "production")
    with pytest.raises(ExecutionProfileError, match="synthetic_in_production"):
        load_evaluation(config, None, None)


REPO_ROOT = Path(__file__).resolve().parents[4]


def test_no_execution_profile_is_in_the_repository() -> None:
    """A real profile names private Condition ids: only fixtures generated in tests exist."""
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
    for name in output.split("\0"):
        path = REPO_ROOT / name
        if name and path.suffix == ".json" and path.is_file():
            assert "heroos.execution-profile/1" not in path.read_text(errors="replace"), name


@pytest.mark.parametrize(
    "name",
    [
        "disciplinary.dev-1.private-execution-profile.json",
        "apps/api/private-execution-profiles/any.json",
        "execution-coverage-audit.json",
    ],
)
def test_private_profile_names_are_ignored_by_git(name: str) -> None:
    ignored = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--no-index", name], check=False
    )
    assert ignored.returncode == 0, name
