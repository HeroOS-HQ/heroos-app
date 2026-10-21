"""The fictional knowledge package (shared with tests/knowledge) and fictional execution content."""

from typing import Any

import pytest

from tests.fixtures.evaluation import Artifacts
from tests.knowledge.conftest import (  # noqa: F401  (pytest fixtures)
    bundle,
    bundle_data,
    bundle_file,
    compiled,
    synthetic_mapping_path,
    synthetic_sources,
)


@pytest.fixture
def artifacts(bundle_data: dict[str, Any]) -> Artifacts:  # noqa: F811
    """Fresh, mutable fictional artifacts (a test may change one and rebuild)."""
    return Artifacts(bundle_data)
