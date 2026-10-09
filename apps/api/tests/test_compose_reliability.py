"""Preview reliability contract for compose.yaml (docs/operations/preview-operations.md).

Services come back after a host reboot or crash, start in dependency order, keep
the named PostgreSQL volume, and report health. Security properties (loopback
ports, required credentials) are covered in test_credential_hygiene.py.
"""

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICES = {"api", "web", "db"}


def _compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((REPO_ROOT / "compose.yaml").read_text())
    return loaded


def test_every_service_restarts_unless_stopped() -> None:
    services = _compose()["services"]

    assert set(services) == SERVICES
    for name, service in services.items():
        # `always` would also restart services an operator stopped on purpose;
        # `on-failure` would not start them again after a reboot.
        assert service.get("restart") == "unless-stopped", name


def test_database_keeps_its_named_volume() -> None:
    compose = _compose()

    assert compose["name"] == "heroos-local"  # volume heroos-local_heroos_postgres_data
    assert compose["services"]["db"]["volumes"] == ["heroos_postgres_data:/var/lib/postgresql/data"]
    assert "heroos_postgres_data" in compose["volumes"]
    assert not (compose["volumes"]["heroos_postgres_data"] or {}).get("external")


def test_services_start_in_dependency_order_once_healthy() -> None:
    services = _compose()["services"]

    assert services["api"]["depends_on"] == {"db": {"condition": "service_healthy"}}
    assert services["web"]["depends_on"] == {"api": {"condition": "service_healthy"}}


def test_every_service_reports_health() -> None:
    services = _compose()["services"]

    for name in ("db", "web"):
        assert services[name]["healthcheck"]["test"], name
    # The API's health check is part of its image.
    dockerfile = (REPO_ROOT / "apps/api/Dockerfile").read_text()
    assert re.search(r"^HEALTHCHECK\b", dockerfile, flags=re.MULTILINE)
    assert "/health" in dockerfile
