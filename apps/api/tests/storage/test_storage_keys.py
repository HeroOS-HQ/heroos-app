"""Storage keys are canonical, server-generated and cannot carry a path."""

import uuid

import pytest

from app.storage.errors import InvalidStorageKeyError
from app.storage.keys import StorageKey, parse_object_id

COMPANY = uuid.UUID("0b6f2c1e-3a8d-4f57-9c2e-6d1a4b7e8f90")
OBJECT = uuid.UUID("5d9e1f2a-7b3c-4d8e-a1f6-2c4b6d8e0a13")

UNSAFE_IDENTIFIERS = [
    "foo/bar",
    "../../secret",
    "..",
    "/tmp/file",
    "C:\\Windows\\system32",
    "company-a/../../company-b/file",
    f"{OBJECT}/../{OBJECT}",
    f"../{OBJECT}",
    f"{OBJECT}/",
    f"/{OBJECT}",
    f"%2e%2e%2f{OBJECT}",
    f"..%2f{OBJECT}",
    f"{str(OBJECT).upper()}",
    f"{{{OBJECT}}}",
    f"urn:uuid:{OBJECT}",
    str(OBJECT).replace("-", ""),
    f" {OBJECT}",
    f"{OBJECT}\x00",
    f"{OBJECT}\n",
    "00000000-0000-0000-0000-000000000000",
    "",
]


def test_canonical_key_layout() -> None:
    key = StorageKey.for_object(COMPANY, OBJECT)

    assert str(key) == f"companies/{COMPANY}/{OBJECT}"
    assert key.parts == ("companies", str(COMPANY), str(OBJECT))


def test_canonical_key_round_trips() -> None:
    key = StorageKey.for_object(COMPANY, OBJECT)

    assert StorageKey.parse(str(key)) == key


def test_canonical_object_id_accepted() -> None:
    assert parse_object_id(str(OBJECT)) == OBJECT


@pytest.mark.parametrize("value", UNSAFE_IDENTIFIERS)
def test_unsafe_object_identifiers_rejected(value: str) -> None:
    with pytest.raises(InvalidStorageKeyError):
        parse_object_id(value)


@pytest.mark.parametrize(
    "value",
    [
        f"companies/{COMPANY}/{OBJECT}/../x",
        f"companies/{COMPANY}/../{OBJECT}",
        f"companies/../{COMPANY}/{OBJECT}",
        f"/companies/{COMPANY}/{OBJECT}",
        f"companies/{COMPANY}//{OBJECT}",
        f"companies\\{COMPANY}\\{OBJECT}",
        f"companies/{COMPANY}/{OBJECT}/",
        f"other/{COMPANY}/{OBJECT}",
        f"companies/{COMPANY}",
        f"companies/{COMPANY}/%2e%2e",
        f"companies/{str(COMPANY).upper()}/{OBJECT}",
        f"companies/00000000-0000-0000-0000-000000000000/{OBJECT}",
        "../../etc/passwd",
        "/etc/passwd",
        "",
    ],
)
def test_non_canonical_keys_rejected(value: str) -> None:
    with pytest.raises(InvalidStorageKeyError):
        StorageKey.parse(value)


@pytest.mark.parametrize(
    ("company_id", "object_id"),
    [
        (uuid.UUID(int=0), OBJECT),
        (COMPANY, uuid.UUID(int=0)),
        (str(COMPANY), OBJECT),
        (COMPANY, "../../secret"),
        (None, OBJECT),
    ],
)
def test_key_requires_non_nil_uuid_instances(company_id: object, object_id: object) -> None:
    with pytest.raises(InvalidStorageKeyError):
        StorageKey.for_object(company_id, object_id)  # type: ignore[arg-type]
