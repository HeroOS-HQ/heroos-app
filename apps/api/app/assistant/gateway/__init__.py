"""Ask HeroOS's controlled AI conversation gateway (M2-NEW-05).

The founder writes in their own words; HeroOS answers from the approved
knowledge runtime (``app.knowledge``), never from a model's general
knowledge, the open web or the raw source documents. One founder turn is two
model requests at most twice each (a schema repair), in fixed layers the
application controls:

1. **Understanding** (``proposals``, ``catalog``): the model proposes what the
   situation is about, from a closed catalog built from the installed bundle
   (workflows, pathways, topics, fact keys), and which facts the founder
   stated, each with the user turn and the words that support it. Everything
   is a candidate: the server validates it, keeps only facts the founder (or
   the canonical Company Blueprint) actually stated, and never lets the
   model choose the jurisdiction.
2. **Retrieval and planning** (``planning``): the server, not the model, calls
   ``get_knowledge_context`` with the validated route, the Blueprint's
   confirmed jurisdiction and the established facts, and selects what HeroOS
   needs to establish next (``QuestionTarget``) in the runtime's own order of
   safety significance.
3. **Grounded response** (``projection``, ``prompts``): the model phrases the
   reply from a minimized view of that knowledge (no ids, sources, digests or
   raw rows) and the server's question targets.
4. **Checks** (``grounding``, ``app.assistant.response_safety``): every reply
   is checked for legal specifics the approved view doesn't contain, internal
   labels, recommended or authorized sanctions, claimed actions and promises
   HeroOS can't keep; a failing reply is replaced by a fixed one.

What the gateway never does: evaluate a Condition, decide WARN / BLOCK /
ESCALATE / ALLOW, create or change a Case, store the conversation or its
facts, generate a document, raise an Expert Review, fetch a URL or search the
web. It reads no database (the API route loads the Blueprint context and
releases the connection before any model request) and the model gets no
tools (docs/architecture/ai-gateway.md).
"""
