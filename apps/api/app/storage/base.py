from typing import Protocol

from app.storage.keys import StorageKey


class PrivateObjectStorage(Protocol):
    """Provider-neutral private object storage over canonical keys.

    Providers store bytes only. They perform no authorization: Company scoping
    belongs to ``PrivateObjectService``, which is the only caller in application
    code. Providers must:

    - accept only ``StorageKey`` values and re-validate them,
    - keep every object private (no public URL, ACL or web-served location),
    - treat objects as write-once (``put`` on an existing key raises
      ``ObjectExistsError``),
    - raise ``ObjectNotFoundError`` for missing objects and ``StorageError``
      with a fixed message for every other failure (never a raw path or provider
      response).
    """

    def put(self, key: StorageKey, data: bytes) -> None: ...

    def get(self, key: StorageKey) -> bytes: ...

    def delete(self, key: StorageKey) -> bool:
        """Delete the object; ``False`` if it did not exist."""
        ...

    def exists(self, key: StorageKey) -> bool: ...
