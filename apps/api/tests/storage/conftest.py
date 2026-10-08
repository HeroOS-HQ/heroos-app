from pathlib import Path

import pytest

from app.storage.local import LocalFilesystemStorage


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    """A storage root that does not exist yet; the provider must create it."""
    return tmp_path / "private-objects"


@pytest.fixture
def storage(storage_root: Path) -> LocalFilesystemStorage:
    return LocalFilesystemStorage(storage_root, environment="development")
