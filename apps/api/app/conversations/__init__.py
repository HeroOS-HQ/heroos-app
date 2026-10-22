"""Durable Ask HeroOS conversations (M2-NEW-07).

> AI controls the conversation. Approved HeroOS methodology controls the
> guidance. The employer makes the final employment decision.

A conversation is a Company-owned record around the existing Case chain
(Case -> WorkflowInstance -> WorkflowSubmission -> CaseFact), never a second
Case system:

- ``service``: one founder turn, persisted (replay, load, answer, record);
- ``checkpoint``: the bounded trusted state the next turn starts from,
  rebuilt from the records whenever it can't be trusted;
- ``bridge``: when a conversation becomes a Case, its safe title, and which
  canonical facts may enter it (through ``app.cases.mutation``, the same
  pipeline as a step's form).

The model's text never becomes a workflow action here: only the server's own
canonical, ENGINE_TRUSTED values (M2-NEW-06) reach a Case, and nothing selects
a pathway, moves a stage, records an employer decision or names a person.
"""
