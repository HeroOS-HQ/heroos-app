"""The routing catalog: what the understanding phase may name, built from the installed bundle.

The model never sees the knowledge itself to classify a message, only this
small closed catalog: the workflows the bundle publishes, their pathways,
topics and employer decisions (keys and titles), and the facts a founder may
state (keys and labels). A decision's key is its stable option id, never its
title (M2-NEW-06 binds execution to the id).
Anything outside it is refused by the server. Nothing here is hard-coded: a
workflow that isn't in the bundle (probation, recruitment, performance) is
simply not in the catalog.

Three kinds of facts are left out of what the model may extract:

- the employment jurisdiction: only the Blueprint's operator-confirmed
  jurisdiction counts, never a conversation;
- facts the Company Blueprint holds (the Blueprint page maintains them; the
  runtime reads them from ``CompanyBlueprintContext`` itself);
- sensitive facts (health, pregnancy, complaints, criminal allegations...):
  no privacy basis exists for collecting them in a conversation, so they are
  never extracted, asked for or sent back to a provider.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from app.knowledge.bundle import Fact, KnowledgeBundle


@dataclass(frozen=True, slots=True)
class CatalogItem:
    key: str
    title: str


@dataclass(frozen=True, slots=True)
class CatalogWorkflow:
    key: str
    title: str
    pathways: tuple[CatalogItem, ...]
    topics: tuple[CatalogItem, ...]
    # The employer decisions the approved content covers (option id and title).
    actions: tuple[CatalogItem, ...] = ()

    def has_pathway(self, key: str) -> bool:
        return any(p.key == key for p in self.pathways)

    def has_topic(self, key: str) -> bool:
        return any(t.key == key for t in self.topics)

    def has_action(self, key: str) -> bool:
        return any(a.key == key for a in self.actions)


@dataclass(frozen=True, slots=True)
class RoutingCatalog:
    workflows: tuple[CatalogWorkflow, ...]
    # Facts a founder may state in conversation (key -> label).
    facts: Mapping[str, str]
    # A choice fact's canonical option values (what a proposed value should be one of).
    options: Mapping[str, tuple[str, ...]] = MappingProxyType({})

    def workflow(self, key: str) -> CatalogWorkflow | None:
        return next((w for w in self.workflows if w.key == key), None)

    def model_view(self) -> dict[str, object]:
        """Exactly what the understanding phase sees: keys and titles, nothing else."""
        return {
            "supported_workflows": [
                {
                    "key": w.key,
                    "title": w.title,
                    "pathways": [{"key": p.key, "title": p.title} for p in w.pathways],
                    "topics": [{"key": t.key, "title": t.title} for t in w.topics],
                    "actions": [{"key": a.key, "title": a.title} for a in w.actions],
                }
                for w in self.workflows
            ],
            "facts": [
                {"key": key, "label": label}
                | ({"options": list(self.options[key])} if key in self.options else {})
                for key, label in self.facts.items()
            ],
        }

    def coverage(self) -> tuple[str, ...]:
        """The published workflows' titles (for the founder: what HeroOS covers today)."""
        return tuple(w.title for w in self.workflows)


def extractable(fact: Fact) -> bool:
    """A fact the founder may establish by saying it (see the module docstring)."""
    # The jurisdiction fact is a Blueprint field too, so it is never extractable.
    return not fact.sensitive and fact.blueprint is None


def routing_catalog(
    bundle: KnowledgeBundle,
    *,
    case_facts: Mapping[str, str] | None = None,
    options: Mapping[str, tuple[str, ...]] | None = None,
) -> RoutingCatalog:
    """``case_facts``: a workflow's own Case questions no knowledge fact holds (key -> label),
    which the founder may state too (chat-first); ``options``: choice facts' option values."""
    workflows = tuple(
        CatalogWorkflow(
            key=w.key,
            title=w.title,
            pathways=tuple(CatalogItem(p.key, p.title) for p in w.pathways),
            topics=tuple(CatalogItem(t.key, t.title) for t in bundle.topics if t.workflow == w.key),
            actions=tuple(
                CatalogItem(o.id, o.title) for o in bundle.options if o.workflow == w.key
            ),
        )
        for w in bundle.workflows
    )
    facts = {f.key: f.label for f in bundle.facts if extractable(f)}
    for key, label in (case_facts or {}).items():
        facts.setdefault(key, label)
    choices = {k: v for k, v in (options or {}).items() if k in facts}
    return RoutingCatalog(
        workflows=workflows, facts=MappingProxyType(facts), options=MappingProxyType(choices)
    )


EMPTY_CATALOG: Final = RoutingCatalog(workflows=(), facts=MappingProxyType({}))
