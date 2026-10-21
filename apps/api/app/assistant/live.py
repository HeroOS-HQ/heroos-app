"""Whether this process may call a real external AI provider: never from automated tests.

An automated test run must never reach a real provider, whatever it was given:
a stale gateway or demo switch, a harness that enables the gateway, a real or
placeholder key left in the environment. So the decision doesn't depend on
those settings at all:

- **Deployed environments** (staging, production) that aren't a test run may
  call the provider they are configured for.
- **An automated test run** (pytest is loaded, or the process is marked with
  ``HEROOS_AUTOMATED_TEST=true``, as the end-to-end harness marks every API it
  starts) and **local development** never may.
- **A deliberate live smoke test** opts in explicitly with
  ``HEROOS_AI_LIVE_SMOKE_ENABLED=true`` (refused in production).

Where calls aren't allowed, the gateway and the Hannah demo get an
``OfflineProvider``: the configuration still reads as configured (pages can be
tested), and every request fails as ``unavailable`` without touching the
network. The real transport checks again on each request
(``transport_permitted``), so a provider built any other way inside a test run
can't call out either.
"""

import os
import sys
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import Final

from app.assistant.provider import AssistantError, ChatTurn, Completion

AUTOMATED_TEST: Final = "HEROOS_AUTOMATED_TEST"
LIVE_SMOKE: Final = "HEROOS_AI_LIVE_SMOKE_ENABLED"


def _true(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def automated_test_process(
    environ: Mapping[str, str] = os.environ, modules: Mapping[str, ModuleType] = sys.modules
) -> bool:
    return "pytest" in modules or _true(environ.get(AUTOMATED_TEST))


def external_ai_permitted(
    *,
    environment: str,
    automated_test: bool,
    live_smoke: bool,
    modules: Mapping[str, ModuleType] = sys.modules,
) -> bool:
    """May a provider built from this configuration call the real provider?"""
    if live_smoke:
        return True
    if automated_test or "pytest" in modules:
        return False
    return environment != "development"


def transport_permitted(
    environ: Mapping[str, str] = os.environ, modules: Mapping[str, ModuleType] = sys.modules
) -> bool:
    """The last check, made by the real transport before every request."""
    return _true(environ.get(LIVE_SMOKE)) or not automated_test_process(environ, modules)


class OfflineProvider:
    """A provider that never reaches the network: every request fails as ``unavailable``."""

    def __init__(self, model: str) -> None:
        self._model = model

    @property
    def name(self) -> str:
        return "offline"

    @property
    def model(self) -> str:
        return self._model

    def reply(self, system: str, turns: Sequence[ChatTurn]) -> str:
        raise AssistantError("unavailable")

    def complete_json(
        self,
        system: str,
        turns: Sequence[ChatTurn],
        *,
        temperature: float,
        max_completion_tokens: int,
        timeout: float,
    ) -> Completion:
        raise AssistantError("unavailable")
