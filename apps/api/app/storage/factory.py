from app.core.config import Settings
from app.storage.base import PrivateObjectStorage
from app.storage.errors import StorageConfigurationError
from app.storage.local import LocalFilesystemStorage


def build_private_object_storage(settings: Settings) -> PrivateObjectStorage | None:
    """Build the configured provider, or ``None`` when storage is not configured.

    ``None`` is fail-closed: every storage operation is refused. No configuration
    ever falls back to local disk.
    """
    match settings.heroos_storage_provider:
        case None:
            return None
        case "local":
            if settings.heroos_local_storage_root is None:
                raise StorageConfigurationError("HEROOS_LOCAL_STORAGE_ROOT is required")
            return LocalFilesystemStorage(
                settings.heroos_local_storage_root, environment=settings.heroos_env
            )
        case "s3":
            # The production contract is documented; the adapter is M3 work.
            # Refuse explicitly rather than pretend to store anything.
            raise StorageConfigurationError(
                "HEROOS_STORAGE_PROVIDER=s3 is not available yet (activated in M3)"
            )
