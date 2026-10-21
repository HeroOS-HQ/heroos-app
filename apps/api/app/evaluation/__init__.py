"""Ask HeroOS's deterministic conversation evaluation (M2-NEW-06).

> The language model never determines a HeroOS outcome. It proposes
> understanding and phrases a response. The deterministic backend determines
> the outcome.

> A Condition result and a requested action's availability are separate
> concepts.

The flow, per founder turn (``app.assistant.gateway`` drives it):

1. the AI's understanding is validated and its facts checked against the
   founder's own words (M2-NEW-05);
2. ``facts`` turns them into three trust levels: PROPOSED, ESTABLISHED
   (conversational) and ENGINE_TRUSTED; only canonical, server-typed values
   the founder gave directly (or the Blueprint holds) are ENGINE_TRUSTED, and
   only those enter a rule;
3. ``snapshot`` holds one immutable, version-compatible set of artifacts for
   the whole turn: the approved knowledge (M2-NEW-04), the workflow
   definition, the rule bundle and the ``profile`` (``heroos.execution-profile/1``)
   that approves them together and binds Conditions to rules explicitly;
4. ``evaluator`` runs the bound rules and the server-owned gates on those
   facts, purely: Condition evaluations, action evaluations, review
   requirements, missing requirements, cautions, and one presentation
   (Guidance, Warning, Block, Expert Review) by fixed precedence;
5. ``presentation`` turns that result into the outcome card and the safe next
   step the server owns, and the minimized view the AI may phrase;
6. ``continuation`` carries the trusted state to the next turn, encrypted and
   authenticated with a shared server key.

Nothing here reads or writes a database, calls a model or a network, persists
anything, creates a Case, generates a document or raises an Expert Review.
No Condition is ever executed from its text; a workflow-name branch never
appears in the evaluator (docs/architecture/conversation-evaluation.md).
"""
