"""Development-only private object storage on the local filesystem.

Not a production provider. It exists so private-object handling can be built
and tested locally without AWS; staging and production must use the S3
provider (docs/architecture/private-object-storage.md).

Layout under the configured root (never web-served, never inside the
repository)::

    <root>/                         0700
      companies/                    0700
        <company uuid>/             0700
          <object uuid>             0600, write-once

Defense in depth on every operation:

- only ``StorageKey`` values are accepted, and they are re-parsed from their
  canonical string form, so every path segment is a fixed prefix or a UUID;
- the parent directory must resolve inside the root (a symlinked Company
  directory is rejected);
- object files are opened with ``O_NOFOLLOW``, so a symlinked object is never
  followed;
- writes go to a private temporary file in the same directory and are published
  with ``os.link``, which is atomic and never replaces an existing object.

Errors carry fixed messages only; filesystem paths never leave this module.
"""

import os
import stat
import tempfile
from contextlib import suppress
from pathlib import Path

from app.core.config import Environment
from app.storage.errors import (
    InvalidStorageKeyError,
    ObjectExistsError,
    ObjectNotFoundError,
    StorageConfigurationError,
    StorageError,
)
from app.storage.keys import StorageKey

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600

# Directory names conventionally served over HTTP. The storage root must never
# sit inside one, even if no HeroOS server currently serves it.
WEB_SERVED_DIRECTORY_NAMES = frozenset({"public", "static", "www", "htdocs", "wwwroot"})

_APP_PACKAGE_DIR = Path(__file__).resolve().parents[1]
_POSIX = os.name == "posix"
_PARTIAL_PREFIX = ".partial-"


def _source_tree_roots() -> tuple[Path, ...]:
    """Directories that contain HeroOS source code (and may be committed)."""
    roots = [_APP_PACKAGE_DIR]
    # Repository checkout layout: <repo>/apps/api/app. In the container image the
    # package lives at /app/app and there is no repository to protect.
    api_dir = _APP_PACKAGE_DIR.parent
    if api_dir.name == "api" and api_dir.parent.name == "apps":
        roots.append(api_dir.parent.parent)
    return tuple(roots)


def _make_private_directory(path: Path) -> None:
    """Create ``path`` (one level) as a private, non-symlinked directory."""
    with suppress(FileExistsError):
        os.mkdir(path, PRIVATE_DIRECTORY_MODE)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode):
        # A symlink or file where a directory belongs: never follow it.
        raise StorageError("object storage directory failed an integrity check")
    if _POSIX and stat.S_IMODE(info.st_mode) != PRIVATE_DIRECTORY_MODE:
        # mkdir modes are reduced by the umask; set the exact mode explicitly.
        os.chmod(path, PRIVATE_DIRECTORY_MODE)


def _fsync_directory(path: Path) -> None:
    if not _POSIX:
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class LocalFilesystemStorage:
    """``PrivateObjectStorage`` backed by a private local directory."""

    def __init__(self, root: Path, *, environment: Environment) -> None:
        # Re-checked here, independent of Settings validation, so local disk can
        # never be constructed as storage for a deployed environment.
        if environment != "development":
            raise StorageConfigurationError(
                "The local storage provider is only allowed when HEROOS_ENV=development"
            )
        self._root = self._prepare_root(root)

    @staticmethod
    def _prepare_root(root: Path) -> Path:
        if not root.is_absolute():
            raise StorageConfigurationError("HEROOS_LOCAL_STORAGE_ROOT must be an absolute path")
        if any(part.lower() in WEB_SERVED_DIRECTORY_NAMES for part in root.parts):
            raise StorageConfigurationError(
                "HEROOS_LOCAL_STORAGE_ROOT must not be inside a web-served directory"
            )
        if root.is_symlink():
            raise StorageConfigurationError("HEROOS_LOCAL_STORAGE_ROOT must not be a symlink")
        # Checked before anything is created, and again on the final resolved path.
        LocalFilesystemStorage._refuse_source_tree(root.resolve())
        try:
            root.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
            resolved = root.resolve(strict=True)
            info = os.lstat(resolved)
            if not stat.S_ISDIR(info.st_mode):
                raise StorageConfigurationError("HEROOS_LOCAL_STORAGE_ROOT must be a directory")
            if _POSIX:
                if info.st_uid != os.geteuid():
                    raise StorageConfigurationError(
                        "HEROOS_LOCAL_STORAGE_ROOT must be owned by the API user"
                    )
                os.chmod(resolved, PRIVATE_DIRECTORY_MODE)
        except OSError:
            raise StorageConfigurationError(
                "HEROOS_LOCAL_STORAGE_ROOT could not be prepared as a private directory"
            ) from None
        LocalFilesystemStorage._refuse_source_tree(resolved)
        return resolved

    @staticmethod
    def _refuse_source_tree(path: Path) -> None:
        if any(path.is_relative_to(source) for source in _source_tree_roots()):
            raise StorageConfigurationError(
                "HEROOS_LOCAL_STORAGE_ROOT must be outside the HeroOS source tree"
            )

    def _object_path(self, key: StorageKey) -> Path:
        if not isinstance(key, StorageKey):
            raise InvalidStorageKeyError("storage providers accept only StorageKey values")
        # Re-parse the canonical string: every segment is the fixed prefix or a
        # canonical UUID, so no segment can be '..', absolute or contain a separator.
        canonical = StorageKey.parse(str(key))
        path = self._root.joinpath(*canonical.parts)
        # Lexical containment, then containment after resolving any symlinked
        # directory on the way (an escape via a planted symlink is refused).
        if not path.is_relative_to(self._root) or not path.parent.resolve().is_relative_to(
            self._root
        ):
            raise StorageError("object path failed a containment check")
        return path

    def put(self, key: StorageKey, data: bytes) -> None:
        path = self._object_path(key)
        if not isinstance(data, bytes):
            raise StorageError("object data must be bytes")
        try:
            for directory in (path.parent.parent, path.parent):
                _make_private_directory(directory)
            # mkstemp creates the file with O_EXCL and mode 0600.
            fd, partial = tempfile.mkstemp(dir=path.parent, prefix=_PARTIAL_PREFIX)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                if _POSIX:
                    os.chmod(partial, PRIVATE_FILE_MODE)
                try:
                    # Atomic publish that never replaces: readers see the whole
                    # object or nothing, and objects are write-once.
                    os.link(partial, path)
                except FileExistsError:
                    raise ObjectExistsError("object already exists") from None
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(partial)
            _fsync_directory(path.parent)
        except OSError:
            raise StorageError("object storage write failed") from None

    def get(self, key: StorageKey) -> bytes:
        path = self._object_path(key)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            raise ObjectNotFoundError("object not found") from None
        except OSError:
            # Includes ELOOP: a symlink where an object belongs is never followed.
            raise StorageError("object storage read failed") from None
        try:
            with os.fdopen(fd, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise StorageError("object storage read failed")
                return handle.read()
        except OSError:
            raise StorageError("object storage read failed") from None

    def delete(self, key: StorageKey) -> bool:
        path = self._object_path(key)
        try:
            os.unlink(path)
        except FileNotFoundError:
            return False
        except OSError:
            raise StorageError("object storage delete failed") from None
        return True

    def exists(self, key: StorageKey) -> bool:
        path = self._object_path(key)
        try:
            return stat.S_ISREG(os.lstat(path).st_mode)
        except FileNotFoundError:
            return False
        except OSError:
            raise StorageError("object storage lookup failed") from None
