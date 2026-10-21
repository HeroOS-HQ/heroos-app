"""Fixtures for the knowledge runtime: the fictional package, compiled once per session."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.knowledge.bundle import KnowledgeBundle, load_knowledge_bundle
from scripts.knowledge.compiler import CompileResult, compile_package
from tests.fixtures.knowledge import synthetic


@pytest.fixture(scope="session")
def synthetic_sources(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return synthetic.write_sources(tmp_path_factory.mktemp("sources") / "package")


@pytest.fixture(scope="session")
def synthetic_mapping_path(
    synthetic_sources: Path, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    path = tmp_path_factory.mktemp("mapping") / "example.mapping.json"
    return synthetic.write_mapping(path, synthetic.mapping(synthetic_sources))


@pytest.fixture(scope="session")
def compiled(synthetic_sources: Path, synthetic_mapping_path: Path) -> CompileResult:
    result = compile_package(synthetic_sources, synthetic_mapping_path)
    assert result.bundle_bytes is not None, [f.detail for f in result.findings.fatal()]
    return result


@pytest.fixture(scope="session")
def bundle_file(compiled: CompileResult, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("bundle") / "example.knowledge.json"
    assert compiled.bundle_bytes is not None
    path.write_bytes(compiled.bundle_bytes)
    return path


@pytest.fixture(scope="session")
def bundle(bundle_file: Path) -> KnowledgeBundle:
    pin = hashlib.sha256(bundle_file.read_bytes()).hexdigest()
    return load_knowledge_bundle(bundle_file, pin, production=False)


@pytest.fixture
def bundle_data(compiled: CompileResult) -> dict[str, Any]:
    """A fresh, mutable copy of the compiled bundle (for tampering tests)."""
    assert compiled.bundle_bytes is not None
    data: dict[str, Any] = json.loads(compiled.bundle_bytes)
    return data
