"""Database TLS trust anchor (docs/operations/demo-authentication-deployment.md §5).

The public Supabase Root 2021 CA is committed and built into the API image, so
`sslmode=verify-full` works for the non-root runtime user without a platform
secret file. The file must stay exactly that one public certificate: pinned by
fingerprint, never a private key, and copied read-only to the path the runbook's
DATABASE_URL names.
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes

REPO_ROOT = Path(__file__).resolve().parents[3]
CA_FILE = REPO_ROOT / "apps/api/certs/supabase-root-2021-ca.crt"
IMAGE_PATH = "/app/certs/supabase-root-2021-ca.crt"
SHA256_FINGERPRINT = (
    "80:70:25:AD:50:D4:ED:21:9D:2C:9C:7D:29:9C:00:4F:"
    "82:4E:B0:0C:F7:F6:5A:FE:F6:07:D0:7B:72:E6:CA:FA"
)
# Replace the CA (runbook §5) well before it stops verifying.
RENEWAL_MARGIN = timedelta(days=90)


def _certificates() -> list[x509.Certificate]:
    return x509.load_pem_x509_certificates(CA_FILE.read_bytes())


def test_ca_file_is_a_single_public_certificate() -> None:
    content = CA_FILE.read_text(encoding="ascii")

    assert re.findall(r"-----BEGIN ([A-Z0-9 ]+)-----", content) == ["CERTIFICATE"]
    assert "PRIVATE" not in content
    assert len(_certificates()) == 1


def test_ca_fingerprint_is_pinned() -> None:
    (certificate,) = _certificates()

    fingerprint = certificate.fingerprint(hashes.SHA256()).hex(":").upper()
    assert fingerprint == SHA256_FINGERPRINT


def test_ca_is_the_supabase_root() -> None:
    (certificate,) = _certificates()

    assert certificate.subject == certificate.issuer
    assert certificate.subject.rfc4514_string().startswith("CN=Supabase Root 2021 CA,")
    assert certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca


def test_ca_is_not_close_to_expiry() -> None:
    (certificate,) = _certificates()

    assert certificate.not_valid_after_utc - RENEWAL_MARGIN > datetime.now(UTC)


def test_dockerfile_copies_the_ca_read_only_before_dropping_root() -> None:
    lines = (REPO_ROOT / "apps/api/Dockerfile").read_text().splitlines()
    copy = f"COPY --chmod=0444 apps/api/certs/supabase-root-2021-ca.crt {IMAGE_PATH}"

    mkdir = "RUN install -d -m 0755 /app/certs"

    assert copy in lines
    # The directory must exist (0755) first: one created by COPY gets 0444 and
    # cannot be traversed, so uid 1001 could not open the file.
    assert mkdir in lines
    assert lines.index(mkdir) < lines.index(copy)
    # Copied while still root, without --chown: root-owned, unwritable by uid 1001.
    assert lines.index(copy) < lines.index("USER heroos")


def test_runbook_database_url_uses_the_image_ca() -> None:
    runbook = (REPO_ROOT / "docs/operations/demo-authentication-deployment.md").read_text()

    assert f"sslmode=verify-full&sslrootcert={IMAGE_PATH}" in runbook
    assert "sslrootcert=/etc/secrets" not in runbook
