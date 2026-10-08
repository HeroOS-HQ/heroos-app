"""Private object storage errors.

Messages are fixed strings. They never contain storage keys, filesystem paths,
provider responses or object content, so they are safe to log and the generic
error boundary never needs to inspect them.
"""


class StorageError(Exception):
    """A storage operation failed for an internal reason (I/O, integrity, provider)."""


class InvalidStorageKeyError(StorageError, ValueError):
    """A storage key or object identifier is not a canonical HeroOS value."""


class ObjectNotFoundError(StorageError, LookupError):
    """No object exists under this key in the caller's Company namespace.

    Raised identically for an object that never existed, was deleted, or belongs
    to another Company: the caller cannot tell these apart.
    """


class ObjectExistsError(StorageError):
    """An object already exists under this key; objects are write-once."""


class StorageConfigurationError(RuntimeError):
    """Storage configuration is unsafe, incomplete or unavailable; startup must stop."""
