"""Test fixtures that are files (fictional, synthetic content only)."""

import hashlib
from pathlib import Path
from typing import Final

FIXTURES: Final = Path(__file__).resolve().parent
# The fictional rule bundle that exercises the progression engine (M2-03).
SYNTHETIC_BUNDLE: Final = FIXTURES / "rule_bundles" / "synthetic-disciplinary.json"


def synthetic_bundle_pin() -> str:
    """The SHA-256 the synthetic bundle file must have (its deployment pin)."""
    return hashlib.sha256(SYNTHETIC_BUNDLE.read_bytes()).hexdigest()


# The fictional template bundle that exercises the preview engine (M2-04C),
# bound to the stages of SYNTHETIC_BUNDLE.
SYNTHETIC_TEMPLATES: Final = FIXTURES / "template_bundles" / "synthetic-disciplinary.json"


def synthetic_templates_pin() -> str:
    """The SHA-256 the synthetic template bundle file must have (its deployment pin)."""
    return hashlib.sha256(SYNTHETIC_TEMPLATES.read_bytes()).hexdigest()
