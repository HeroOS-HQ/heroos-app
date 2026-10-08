"""Storage configuration fails closed; deployed environments never use local disk."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.storage.errors import StorageConfigurationError
from app.storage.factory import build_private_object_storage
from app.storage.local import LocalFilesystemStorage

COGNITO = {
    "heroos_auth_provider": "cognito",
    "heroos_cognito_issuer": "https://cognito-idp.test.invalid/test-user-pool",
    "heroos_cognito_app_client_id": "test-app-client-id",
}
ROOT_CANARY = "/srv/SUPER_SECRET_STORAGE_ROOT_CANARY"


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for name in list(os.environ):
        if name.startswith("HEROOS_"):
            monkeypatch.delenv(name)


def make_settings(**values: Any) -> Settings:
    values.setdefault("heroos_env", "development")
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_storage_unconfigured_by_default_builds_none() -> None:
    settings = make_settings()

    assert settings.heroos_storage_provider is None
    assert build_private_object_storage(settings) is None


def test_local_provider_allowed_in_development(tmp_path: Path) -> None:
    settings = make_settings(
        heroos_storage_provider="local", heroos_local_storage_root=tmp_path / "objects"
    )

    assert isinstance(build_private_object_storage(settings), LocalFilesystemStorage)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_local_provider_rejected_outside_development(environment: str) -> None:
    with pytest.raises(ValidationError, match="HEROOS_STORAGE_PROVIDER=local is not allowed") as e:
        make_settings(
            heroos_env=environment,
            heroos_storage_provider="local",
            heroos_local_storage_root=ROOT_CANARY,
            **COGNITO,
        )

    assert "SUPER_SECRET_STORAGE_ROOT_CANARY" not in str(e.value)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_local_root_rejected_outside_development(environment: str) -> None:
    with pytest.raises(ValidationError, match="must not be set outside development") as e:
        make_settings(heroos_env=environment, heroos_local_storage_root=ROOT_CANARY, **COGNITO)

    assert "SUPER_SECRET_STORAGE_ROOT_CANARY" not in str(e.value)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environment_without_storage_does_not_fall_back_to_local(
    environment: str,
) -> None:
    settings = make_settings(heroos_env=environment, **COGNITO)

    assert build_private_object_storage(settings) is None


@pytest.mark.parametrize("root", [None, "relative/objects"])
def test_local_provider_requires_absolute_root(root: str | None) -> None:
    with pytest.raises(ValidationError, match="absolute path"):
        make_settings(heroos_storage_provider="local", heroos_local_storage_root=root)


def test_local_root_without_local_provider_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="only valid with the local provider"):
        make_settings(heroos_local_storage_root=tmp_path)


@pytest.mark.parametrize("provider", ["filesystem", "disk", "S3", "LOCAL", "memory", ""])
def test_unknown_storage_provider_rejected(provider: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(heroos_storage_provider=provider)


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_s3_provider_refused_until_implemented(environment: str) -> None:
    extra = COGNITO if environment != "development" else {}
    settings = make_settings(heroos_env=environment, heroos_storage_provider="s3", **extra)

    with pytest.raises(StorageConfigurationError, match="not available yet"):
        build_private_object_storage(settings)


def test_factory_rechecks_environment_when_validation_is_skipped(tmp_path: Path) -> None:
    settings = Settings.model_construct(
        heroos_env="production",
        heroos_storage_provider="local",
        heroos_local_storage_root=tmp_path / "objects",
    )

    with pytest.raises(StorageConfigurationError):
        build_private_object_storage(settings)
    assert not (tmp_path / "objects").exists()
