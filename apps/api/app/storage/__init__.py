"""Private object storage. See docs/architecture/private-object-storage.md.

``PrivateObjectService`` is the application entry point: it takes a trusted
``CompanyScope`` and derives every storage key server-side. Providers
(``PrivateObjectStorage``) store bytes under canonical keys and perform no
authorization.
"""

from app.storage.base import PrivateObjectStorage
from app.storage.errors import (
    InvalidStorageKeyError,
    ObjectExistsError,
    ObjectNotFoundError,
    StorageConfigurationError,
    StorageError,
)
from app.storage.keys import StorageKey, parse_object_id

__all__ = [
    "InvalidStorageKeyError",
    "ObjectExistsError",
    "ObjectNotFoundError",
    "PrivateObjectStorage",
    "StorageConfigurationError",
    "StorageError",
    "StorageKey",
    "parse_object_id",
]
