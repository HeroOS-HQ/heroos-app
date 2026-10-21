"""The routing catalog: what the understanding phase may name, built from the installed bundle.

The model never sees the knowledge itself to classify a message, only this
small closed catalog: the workflows the bundle publishes, their pathways and
topics (keys and titles), and the facts a founder may state (keys and labels).
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

    def has_pathway(self, key: str) -> bool:
        return any(p.key == key for p in self.pathways)

    def has_topic(self, key: str) -> bool:
        return any(t.key == key for t in self.topics)


@dataclass(frozen=True, slots=True)
class RoutingCatalog:
    workflows: tuple[CatalogWorkflow, ...]
    # Facts a founder may state in conversation (key -> label).
    facts: Mapping[str, str]

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
                }
                for w in self.workflows
            ],
            "facts": [{"key": key, "label": label} for key, label in self.facts.items()],
        }

    def coverage(self) -> tuple[str, ...]:
        """The published workflows' titles (for the founder: what HeroOS covers today)."""
        return tuple(w.title for w in self.workflows)


def extractable(fact: Fact) -> bool:
    """A fact the founder may establish by saying it (see the module docstring)."""
    # The jurisdiction fact is a Blueprint field too, so it is never extractable.
    return not fact.sensitive and fact.blueprint is None


def routing_catalog(bundle: KnowledgeBundle) -> RoutingCatalog:
    workflows = tuple(
        CatalogWorkflow(
            key=w.key,
            title=w.title,
            pathways=tuple(CatalogItem(p.key, p.title) for p in w.pathways),
            topics=tuple(CatalogItem(t.key, t.title) for t in bundle.topics if t.workflow == w.key),
        )
        for w in bundle.workflows
    )
    facts = {f.key: f.label for f in bundle.facts if extractable(f)}
    return RoutingCatalog(workflows=workflows, facts=MappingProxyType(facts))


EMPTY_CATALOG: Final = RoutingCatalog(workflows=(), facts=MappingProxyType({}))
