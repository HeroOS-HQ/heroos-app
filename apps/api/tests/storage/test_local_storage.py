"""Development filesystem provider: private, contained, write-once, fail-safe errors."""

import os
import stat
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.storage.errors import (
    InvalidStorageKeyError,
    ObjectExistsError,
    ObjectNotFoundError,
    StorageConfigurationError,
    StorageError,
)
from app.storage.keys import StorageKey
from app.storage.local import LocalFilesystemStorage

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics")

COMPANY_A = uuid.UUID("0b6f2c1e-3a8d-4f57-9c2e-6d1a4b7e8f90")
COMPANY_B = uuid.UUID("7c1d3e5f-9a2b-4c6d-8e0f-1a3b5c7d9e2f")
DATA = b"synthetic private object bytes"
REPO_ROOT = Path(__file__).resolve().parents[4]


def key(company: uuid.UUID = COMPANY_A, obj: uuid.UUID | None = None) -> StorageKey:
    return StorageKey.for_object(company, obj or uuid.uuid4())


def mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


@pytest.fixture
def permissive_umask() -> Iterator[None]:
    """Prove modes are set explicitly rather than inherited from the umask."""
    previous = os.umask(0)
    try:
        yield
    finally:
        os.umask(previous)


def test_put_get_exists_delete(storage: LocalFilesystemStorage) -> None:
    k = key()

    assert not storage.exists(k)
    storage.put(k, DATA)
    assert storage.exists(k)
    assert storage.get(k) == DATA
    assert storage.delete(k) is True
    assert not storage.exists(k)


def test_deleted_object_is_inaccessible(
    storage: LocalFilesystemStorage, storage_root: Path
) -> None:
    k = key()
    storage.put(k, DATA)
    storage.delete(k)

    with pytest.raises(ObjectNotFoundError):
        storage.get(k)
    assert storage.delete(k) is False
    assert not storage_root.joinpath(*k.parts).exists()


def test_missing_object_raises_not_found(storage: LocalFilesystemStorage) -> None:
    with pytest.raises(ObjectNotFoundError):
        storage.get(key())
    assert storage.delete(key()) is False
    assert storage.exists(key()) is False


def test_objects_are_write_once(storage: LocalFilesystemStorage) -> None:
    k = key()
    storage.put(k, DATA)

    with pytest.raises(ObjectExistsError):
        storage.put(k, b"replacement")
    assert storage.get(k) == DATA


def test_object_stored_at_canonical_location(
    storage: LocalFilesystemStorage, storage_root: Path
) -> None:
    k = key()
    storage.put(k, DATA)

    path = storage_root / "companies" / str(k.company_id) / str(k.object_id)
    assert path.read_bytes() == DATA
    # Only the object itself: no partial/temporary files left behind.
    assert sorted(p.name for p in path.parent.iterdir()) == [str(k.object_id)]


def test_failed_publish_leaves_no_object_or_partial_file(
    storage: LocalFilesystemStorage, storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_link(*_: object) -> None:
        raise OSError(28, "No space left on device", str(storage_root))

    monkeypatch.setattr(os, "link", fail_link)
    k = key()

    with pytest.raises(StorageError) as exc_info:
        storage.put(k, DATA)

    assert str(storage_root) not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert list(storage_root.joinpath("companies", str(k.company_id)).iterdir()) == []


@posix_only
@pytest.mark.usefixtures("permissive_umask")
def test_directories_and_files_are_private(
    storage: LocalFilesystemStorage, storage_root: Path
) -> None:
    k = key()
    storage.put(k, DATA)

    assert mode(storage_root) == 0o700
    assert mode(storage_root / "companies") == 0o700
    assert mode(storage_root / "companies" / str(k.company_id)) == 0o700
    assert mode(storage_root.joinpath(*k.parts)) == 0o600


@posix_only
def test_existing_root_with_broad_permissions_is_tightened(tmp_path: Path) -> None:
    root = tmp_path / "broad"
    root.mkdir()
    root.chmod(0o777)

    LocalFilesystemStorage(root, environment="development")

    assert mode(root) == 0o700


@posix_only
def test_existing_company_directory_with_broad_permissions_is_tightened(
    storage: LocalFilesystemStorage, storage_root: Path
) -> None:
    company_dir = storage_root / "companies" / str(COMPANY_A)
    company_dir.mkdir(parents=True)
    company_dir.chmod(0o755)

    storage.put(key(COMPANY_A), DATA)

    assert mode(company_dir) == 0o700


def test_company_namespaces_are_separate_directories(
    storage: LocalFilesystemStorage, storage_root: Path
) -> None:
    obj = uuid.uuid4()
    storage.put(key(COMPANY_A, obj), b"A")

    # The same object UUID in another Company namespace is a different object.
    assert not storage.exists(key(COMPANY_B, obj))
    with pytest.raises(ObjectNotFoundError):
        storage.get(key(COMPANY_B, obj))
    assert storage.delete(key(COMPANY_B, obj)) is False
    assert storage.get(key(COMPANY_A, obj)) == b"A"


@pytest.mark.parametrize("raw", ["../../secret", f"companies/{COMPANY_A}/x", "/etc/passwd"])
def test_provider_rejects_raw_strings(storage: LocalFilesystemStorage, raw: str) -> None:
    for operation in (storage.get, storage.exists, storage.delete):
        with pytest.raises(InvalidStorageKeyError):
            operation(raw)  # type: ignore[arg-type]
    with pytest.raises(InvalidStorageKeyError):
        storage.put(raw, DATA)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "forged",
    ["../../../../outside", "/tmp/heroos-escape", "..", "x/../../outside"],
)
def test_tampered_key_is_rejected_before_any_filesystem_access(
    storage: LocalFilesystemStorage, storage_root: Path, forged: str
) -> None:
    # Bypass StorageKey validation the way a bug might: the provider re-parses
    # the canonical form and must still refuse.
    k = key()
    object.__setattr__(k, "object_id", forged)

    for operation in (storage.get, storage.exists, storage.delete):
        with pytest.raises(InvalidStorageKeyError):
            operation(k)
    with pytest.raises(InvalidStorageKeyError):
        storage.put(k, DATA)
    assert not (storage_root.parent / "outside").exists()
    assert not Path("/tmp/heroos-escape").exists()


@posix_only
def test_symlinked_company_directory_escape_is_refused(
    storage: LocalFilesystemStorage, storage_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = uuid.uuid4()
    (outside / str(victim)).write_bytes(b"outside the storage root")
    (storage_root / "companies").mkdir()
    (storage_root / "companies" / str(COMPANY_A)).symlink_to(outside, target_is_directory=True)

    with pytest.raises(StorageError) as exc_info:
        storage.get(key(COMPANY_A, victim))
    assert str(outside) not in str(exc_info.value)
    with pytest.raises(StorageError):
        storage.put(key(COMPANY_A), DATA)
    with pytest.raises(StorageError):
        storage.delete(key(COMPANY_A, victim))
    assert (outside / str(victim)).read_bytes() == b"outside the storage root"
    assert [p.name for p in outside.iterdir()] == [str(victim)]


@posix_only
def test_symlinked_object_is_not_followed(
    storage: LocalFilesystemStorage, storage_root: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "outside-secret"
    secret.write_bytes(b"must never be returned")
    k = key()
    company_dir = storage_root.joinpath(*k.parts[:2])
    company_dir.mkdir(parents=True)
    (company_dir / str(k.object_id)).symlink_to(secret)

    with pytest.raises(StorageError) as exc_info:
        storage.get(k)
    assert str(secret) not in str(exc_info.value)
    assert storage.exists(k) is False
    with pytest.raises(ObjectExistsError):
        storage.put(k, DATA)
    assert secret.read_bytes() == b"must never be returned"


def test_storage_errors_do_not_expose_paths(
    storage: LocalFilesystemStorage, storage_root: Path
) -> None:
    k = key()
    storage_root.joinpath(*k.parts).mkdir(parents=True)  # a directory where an object belongs

    with pytest.raises(StorageError) as exc_info:
        storage.get(k)

    assert str(storage_root) not in str(exc_info.value)
    assert str(k.object_id) not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_provider_refuses_deployed_environments(tmp_path: Path, environment: str) -> None:
    with pytest.raises(StorageConfigurationError):
        LocalFilesystemStorage(tmp_path / "root", environment=environment)  # type: ignore[arg-type]
    assert not (tmp_path / "root").exists()


@pytest.mark.parametrize(
    "relative_root",
    ["public/objects", "objects/static", "srv/www/objects", "Public/objects"],
)
def test_root_inside_web_served_directory_refused(tmp_path: Path, relative_root: str) -> None:
    with pytest.raises(StorageConfigurationError, match="web-served"):
        LocalFilesystemStorage(tmp_path / relative_root, environment="development")


@pytest.mark.parametrize(
    "root",
    [
        REPO_ROOT / "private-objects",
        REPO_ROOT / "apps" / "api" / "app" / "objects",
        REPO_ROOT / "apps" / "web" / ".next" / "objects",
    ],
)
def test_root_inside_source_tree_refused(root: Path) -> None:
    assert not root.exists()

    with pytest.raises(StorageConfigurationError, match="source tree"):
        LocalFilesystemStorage(root, environment="development")

    # Refused before anything is created inside the repository.
    assert not root.exists()


def test_relative_root_refused() -> None:
    with pytest.raises(StorageConfigurationError, match="absolute"):
        LocalFilesystemStorage(Path("relative/objects"), environment="development")


@posix_only
def test_symlink_root_refused(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(StorageConfigurationError, match="symlink"):
        LocalFilesystemStorage(link, environment="development")


def test_file_root_refused(tmp_path: Path) -> None:
    root = tmp_path / "file"
    root.write_text("not a directory")

    with pytest.raises(StorageConfigurationError) as exc_info:
        LocalFilesystemStorage(root, environment="development")
    assert str(root) not in str(exc_info.value)


def test_put_requires_bytes(storage: LocalFilesystemStorage) -> None:
    with pytest.raises(StorageError):
        storage.put(key(), "text is not bytes")  # type: ignore[arg-type]
