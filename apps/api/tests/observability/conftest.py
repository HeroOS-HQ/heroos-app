"""Capture what HeroOS actually writes to stdout, at the most verbose level."""

import io
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.observability.logging import configure_logging


@dataclass
class CapturedLogs:
    stream: io.StringIO = field(default_factory=io.StringIO)

    @property
    def text(self) -> str:
        return self.stream.getvalue()

    def lines(self) -> list[dict[str, Any]]:
        # Every line must be one JSON object: nothing unstructured is emitted.
        return [json.loads(line) for line in self.text.splitlines() if line]

    def events(self, name: str) -> list[dict[str, Any]]:
        return [line for line in self.lines() if line.get("event") == name]


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture) -> Iterator[CapturedLogs]:
    """The production handler/formatter at DEBUG, writing to a buffer.

    ``caplog`` is also set to DEBUG so tests can inspect raw records too.
    """
    root = logging.getLogger()
    previous_level = root.level
    captured = CapturedLogs()
    handler = configure_logging("DEBUG", stream=captured.stream)
    caplog.set_level(logging.DEBUG)
    try:
        yield captured
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


def raw_record_text(caplog: pytest.LogCaptureFixture) -> str:
    """Everything a raw record carries: message, args and every attribute."""
    return "\n".join(
        f"{record.getMessage()} {record.args!r} {record.__dict__!r}" for record in caplog.records
    )
