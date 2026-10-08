"""The local runtime-role bootstrap refuses unsafe targets before connecting."""

import pytest

from scripts.bootstrap_runtime_role import BootstrapError, bootstrap_runtime_role

ADMIN = "postgresql+psycopg://heroos:heroos_local@localhost:5433/heroos"
RUNTIME = "postgresql+psycopg://heroos_app:heroos_app_local@localhost:5433/heroos"


@pytest.mark.parametrize(
    ("admin_url", "runtime_url"),
    [
        pytest.param(
            "postgresql+psycopg://heroos:x@prod.example.com/heroos", RUNTIME, id="remote-admin"
        ),
        pytest.param(
            ADMIN, "postgresql+psycopg://heroos_app:x@rds.amazonaws.com/heroos", id="remote-runtime"
        ),
        pytest.param(ADMIN, ADMIN, id="runtime-is-admin"),
        pytest.param(
            ADMIN,
            "postgresql+psycopg://heroos_app_runtime:x@localhost:5433/heroos",
            id="runtime-is-privilege-role",
        ),
        pytest.param(
            ADMIN, "postgresql+psycopg://heroos_app@localhost:5433/heroos", id="no-password"
        ),
        pytest.param(
            ADMIN, 'postgresql+psycopg://"x; DROP":pw@localhost:5433/heroos', id="unsafe-name"
        ),
    ],
)
def test_refuses_unsafe_configuration(admin_url: str, runtime_url: str) -> None:
    with pytest.raises(BootstrapError):
        bootstrap_runtime_role(admin_url, runtime_url)
