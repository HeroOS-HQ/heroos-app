"""Post-restore verification suite (``make backup-restore-check``).

``scripts/verify-backup-restore.sh`` creates a disposable source database,
migrates and seeds it, backs it up with ``scripts.db_recovery``, restores the
archive into a second disposable database and then runs this suite against
both. The script owns both databases and drops them afterwards.

Without configuration the suite is skipped (``make check`` needs no database);
with ``RECOVERY_TEST_REQUIRED=1`` missing configuration fails instead.
"""

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

SOURCE_URL_ENV = "RECOVERY_TEST_SOURCE_URL"
RESTORED_URL_ENV = "RECOVERY_TEST_RESTORED_URL"
RUNTIME_ROLE_ENV = "RECOVERY_TEST_RUNTIME_ROLE"
RUNTIME_PASSWORD_ENV = "RECOVERY_TEST_RUNTIME_PASSWORD"
REQUIRED_ENV = "RECOVERY_TEST_REQUIRED"

DISPOSABLE_RUNTIME_ROLE = re.compile(r"heroos_app_t_[0-9a-f]{8}")

SAFE_NAMES = {
    SOURCE_URL_ENV: re.compile(r"[a-z0-9_]+_backup_source_test"),
    RESTORED_URL_ENV: re.compile(r"[a-z0-9_]+_backup_restore_test"),
}


@dataclass(frozen=True)
class RecoveryDatabases:
    source_admin_url: str
    restored_admin_url: str
    restored_runtime_url: str
    admin_role: str
    runtime_role: str


@pytest.fixture(scope="session")
def recovery() -> RecoveryDatabases:
    urls: dict[str, str] = {}
    for env, pattern in SAFE_NAMES.items():
        url = os.environ.get(env)
        if not url:
            message = f"{env} not set; run `make backup-restore-check`"
            if os.environ.get(REQUIRED_ENV) == "1":
                pytest.fail(message)
            pytest.skip(message)
        database = make_url(url).database or ""
        if not pattern.fullmatch(database):
            pytest.fail(f"refusing to use database {database!r} for {env}")
        urls[env] = url

    restored = make_url(urls[RESTORED_URL_ENV])
    # The script's disposable runtime login role; no default credential.
    runtime_role = os.environ.get(RUNTIME_ROLE_ENV, "")
    runtime_password = os.environ.get(RUNTIME_PASSWORD_ENV, "")
    if not DISPOSABLE_RUNTIME_ROLE.fullmatch(runtime_role) or not runtime_password:
        pytest.fail(
            f"{RUNTIME_ROLE_ENV} must name a disposable heroos_app_t_<8 hex> role and "
            f"{RUNTIME_PASSWORD_ENV} must be set; run `make backup-restore-check`"
        )
    runtime_url = restored.set(username=runtime_role, password=runtime_password).render_as_string(
        hide_password=False
    )
    return RecoveryDatabases(
        source_admin_url=urls[SOURCE_URL_ENV],
        restored_admin_url=urls[RESTORED_URL_ENV],
        restored_runtime_url=runtime_url,
        admin_role=restored.username or "",
        runtime_role=runtime_role,
    )


def _engine(url: str) -> Iterator[Engine]:
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def source_admin(recovery: RecoveryDatabases) -> Iterator[Engine]:
    yield from _engine(recovery.source_admin_url)


@pytest.fixture(scope="session")
def restored_admin(recovery: RecoveryDatabases) -> Iterator[Engine]:
    yield from _engine(recovery.restored_admin_url)


@pytest.fixture(scope="session")
def restored_runtime(recovery: RecoveryDatabases) -> Iterator[Engine]:
    """The API runtime role on the restored database: subject to RLS."""
    yield from _engine(recovery.restored_runtime_url)
