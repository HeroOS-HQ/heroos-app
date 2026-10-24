"""Fakes for the Ask HeroOS gateway's tests: a scripted provider, companies and proposals.

The provider never reaches a network: it answers each phase from a script
(a dict is sent as JSON, a string as raw text, an ``AssistantError`` is
raised) and records every request. Everything here is fictional.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.assistant.gateway.prompts import UNDERSTANDING_INSTRUCTION
from app.assistant.gateway.proposals import RESPONSE_SCHEMA, UNDERSTANDING_SCHEMA
from app.assistant.gateway.service import AiGateway
from app.assistant.limits import UsageLimits
from app.assistant.provider import AssistantError, ChatTurn, Completion
from app.companies.blueprint import CompanyBlueprintContext, CompanyPerson, JurisdictionContext
from app.knowledge.bundle import KnowledgeBundle

FED, DIFC = "uae_federal", "difc"
Script = dict[str, Any] | str | AssistantError


@dataclass(frozen=True)
class Call:
    phase: str
    system: str
    turns: list[ChatTurn]
    temperature: float
    max_completion_tokens: int
    timeout: float

    @property
    def data(self) -> dict[str, Any]:
        """The data sections of the request (the first user message, its stable part included)."""
        first = self.turns[0]
        loaded: dict[str, Any] = json.loads(first.stable) if first.stable else {}
        loaded.update(json.loads(first.content))
        return loaded

    @property
    def text(self) -> str:
        return self.system + "\n".join(t.content for t in self.turns)


class ScriptedProvider:
    def __init__(
        self,
        understanding: Script | Sequence[Script],
        response: Script | Sequence[Script] | None = None,
    ) -> None:
        self.scripts = {
            "understanding": list(understanding)
            if isinstance(understanding, list)
            else [understanding],
            "response": [] if response is None
            else list(response) if isinstance(response, list) else [response],
        }  # fmt: skip
        self.calls: list[Call] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    def reply(self, system: str, turns: Sequence[ChatTurn]) -> str:
        raise AssertionError("the gateway never asks for free text")

    def complete_json(
        self,
        system: str,
        turns: Sequence[ChatTurn],
        *,
        temperature: float,
        max_completion_tokens: int,
        timeout: float,
    ) -> Completion:
        phase = "understanding" if system == UNDERSTANDING_INSTRUCTION else "response"
        self.calls.append(
            Call(phase, system, list(turns), temperature, max_completion_tokens, timeout)
        )
        script = self.scripts[phase]
        if not script:
            raise AssertionError(f"no scripted {phase} output left")
        item = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(item, AssistantError):
            raise item
        text = item if isinstance(item, str) else json.dumps(item)
        return Completion(text=text, prompt_tokens=100, completion_tokens=20)

    def phase(self, name: str) -> list[Call]:
        return [c for c in self.calls if c.phase == name]

    @property
    def everything_sent(self) -> str:
        return "\n".join(c.text for c in self.calls)


def understanding(
    *,
    intent: str = "supported_hr",
    workflow: str | None = "disciplinary",
    pathway: str | None = None,
    topics: Sequence[str] = (),
    facts: Sequence[dict[str, Any]] = (),
    uncertainties: Sequence[str] = (),
    summary: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": UNDERSTANDING_SCHEMA,
        "intent": intent,
        "workflow_candidate": workflow if intent == "supported_hr" else None,
        "pathway_candidate": pathway,
        "topics": list(topics),
        "fact_proposals": list(facts),
        "uncertainties": list(uncertainties),
        "case_summary": summary,
    }


def fact(
    key: str,
    value: str,
    excerpt: str,
    *,
    turn: int | None = 0,
    provenance: str = "current_user_message",
    basis: str = "explicit",
    confidence: str = "high",
) -> dict[str, Any]:
    return {
        "fact_key": key,
        "proposed_value": value,
        "confidence": confidence,
        "provenance": provenance,
        "source_turn": turn,
        "support_excerpt": excerpt,
        "explicit_or_inferred": basis,
    }


def response(reply: str, targets: Sequence[str] = (), step: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": RESPONSE_SCHEMA,
        "reply": reply,
        "question_target_ids": list(targets),
        "safe_next_step": step,
    }


def company(
    jurisdiction: str | None = FED,
    *,
    confirmed: bool = True,
    user: UUID | None = None,
    company_id: UUID | None = None,
    policy_context: str | None = None,
) -> CompanyBlueprintContext:
    person = CompanyPerson(
        uuid4(), user or uuid4(), "company_admin", datetime(2026, 10, 1, tzinfo=UTC), True, True
    )
    allowed = confirmed and jurisdiction is not None
    return CompanyBlueprintContext(
        company_id=company_id or uuid4(),
        company_display_name="[SYNTHETIC] Example Trading",
        legal_name="[SYNTHETIC] Example Trading LLC",
        industry="Retail",
        employee_count=12,
        website_url="https://example.com/",
        company_summary="[SYNTHETIC] A small chain of shops.",
        jurisdiction=JurisdictionContext(
            readiness="supported_confirmed" if allowed else "unconfirmed",
            reason="confirmed" if allowed else "awaiting_confirmation",
            employment_jurisdiction=jurisdiction if allowed else None,
            confirmed_at=None,
            guidance_allowed=allowed,
            licensing_location="other" if jurisdiction == FED else "difc",
            licensing_authority="[SYNTHETIC] Licensing authority" if jurisdiction == FED else None,
        ),
        policies_exist="yes",
        policy_context=policy_context,
        hr_support="internal",
        hr_support_notes=None,
        primary_contact=person,
        current_user=person,
        updated_at=None,
        missing=(),
    )


def gateway(
    bundle: KnowledgeBundle | None,
    provider: ScriptedProvider | None,
    *,
    enabled: bool = True,
    approval: str | None = "TEST-APPROVAL-1",
    allow_development_knowledge: bool = True,
    limits: UsageLimits | None = None,
) -> AiGateway:
    return AiGateway(
        enabled=enabled,
        provider=provider,
        bundle=bundle,
        approval=approval,
        allow_development_knowledge=allow_development_knowledge,
        limits=limits or UsageLimits(account_limit=100, global_per_minute=100, global_per_day=1000),
    )
