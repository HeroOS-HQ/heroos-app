# Chat-First Case Architecture

**Status:** in development (branch `feat/chat-first-case-architecture`); migration D7 (`da3c95517149`), schema contract 10. Not deployed; D7 is applied only to the local/VPS dev database.

> **Chat is the experience. Case is the durable authoritative state behind it.** One chat is one Case; the first submitted message starts it; a Case may exist before its workflow is known. The workflow engine governs HeroOS; the founder does not operate it.

This supersedes, where they conflict, the Case-creation threshold of [ask-conversations.md](ask-conversations.md) §5 (a Case only at a supported workflow) and the "point the founder to their case" parts of [disciplinary-reference-workflow.md](disciplinary-reference-workflow.md). Everything else in those documents (the turn, reconciliation, trust, reviews, jurisdiction, privacy) stands.

## 1. The model

```text
AssistantConversation  1 ── 1  Case
                                 ├── (no workflow yet: case_type "unclassified", title "New case")
                                 └── WorkflowInstance (attached when a supported workflow is established)
                                      └── WorkflowSubmission (structured | assistant) ── CaseFact
```

- **The first completed turn starts the Case** (`AskConversations._start_case`), whatever the message says ("Hi", "Can you help me?"). The Case has no `WorkflowInstance`, `case_type = "unclassified"` and the server title "New case". Opening an empty New Chat stores nothing.
- **A workflow attaches to the same Case** (`_attach_workflow`, `workflows.attach_workflow`) when the turn's deterministic evaluation establishes a supported workflow (the same threshold as M2-NEW-07: supported matter, a real definition, one matter, no other workflow). The Case takes the workflow's `case_type`; the instance's `request_key` is still derived from the conversation (one per conversation). "Hi" never establishes a workflow.
- **Titles** are the server's and only ever become more specific: "New case" → "Disciplinary case · 22 Oct" → an approved topic label ("Conduct concern"). Never a name, an allegation, a sanction or a finding (`bridge.better_title`).
- **Access:** `unclassified` is a restricted Case type (`app.workflows.access`): Company administrators only, like Disciplinary.
- **New Chat** starts a new conversation, so a new Case on its first message; nothing of another Case is read (every turn loads only its own conversation, Case and checkpoint).

## 2. Facts in conversation

The trust model is unchanged (PROPOSED, ESTABLISHED_CONVERSATIONAL, ENGINE_TRUSTED; `app.evaluation.facts`). What changed is *which* Case facts the conversation can carry and how they reach the Case:

1. **Case-only intake questions are facts too** (`snapshot._schemas`). A non-sensitive choice or date question of the definition that no knowledge fact holds (whether the issue was raised before, the incident date, earlier documented action, witnesses) gets a schema under its question key, so it can be asked, answered directly, confirmed and saved like a knowledge-mapped fact. Never a sensitive (screening) question, the jurisdiction or free text.
2. **HeroOS may ask about what the Case record still needs** (`progress._open_intake`, gateway `_case_targets`): the open questions are offered to the response phase as *optional* question targets (at most two, never one already answered or said), and listed as `case_progress.case_record_still_needs`. The model chooses whether and how to ask, one question at a time. A direct answer to the one question asked is parsed deterministically and becomes ENGINE_TRUSTED, then a Case fact through the shared pipeline (`app.cases.mutation`, origin `assistant`).
3. **Several facts in one reply are noted, not trusted** (`bridge.noted_facts`). An ESTABLISHED_CONVERSATIONAL reading of a Case question ("it happened last month too, we spoke to him then, I have the WhatsApp messages") is canonicalized by the server and validated against the Case; it is stored in the checkpoint (`noted`, bounded codes) and shown as "For your case record". **The employer saves it with one click** (`POST .../conversations/{id}/noted`, the values are the server's own, never the browser's); it then goes through the shared pipeline as an assistant submission of the latest founder message. HeroOS never asks again for what was said (M2-NEW-06 already reuses conversational facts).
4. **The narrative** ("What happened?") is the founder's own words: the message that established the matter is saved as written when the workflow attaches (never the AI's summary).
5. The jurisdiction confirmation and the safety screening are never collected in words: they stay inline button steps (`CaseSteps`).

Structured edits and chat share one state: a correction saved in Case details is a newer Case fact, which the next turn reads (`checkpoint.resume` loads Case-backed facts every turn).

## 3. Formal employer actions

Unchanged authority: the pathway, starting and completing stages, stage checklists and caution acknowledgements are the employer's clicks on the Case's existing routes (`CaseSteps`, inline in the chat), never inferred. What changed:

- While the Case's intake still has questions the conversation can collect, no card sends the founder to the form (the old "N case details are still open… review the case details" card is gone). The progression engine still requires a recorded intake before a pathway (`intake_incomplete`): that safeguard is not weakened.
- The pathway card adds "I'm not sure", which only puts words in the founder's box (nothing is recorded).
- The response instruction says these steps appear as buttons in the conversation (it used to say "point the founder to their case").

## 4. The UI

- **Ask HeroOS is the Case page.** Over the chat, a light Case header: the title, where it stands ("In progress", "Investigation stage in progress"), and Case details (once a workflow is attached), History and New chat. Attention chips only when something needs attention.
- **History is the Case list** (the header's control and the chat's): one list, today's then earlier; choosing one reopens that chat. Case records created before the chat-first Case (through the guided form, with no chat) are listed apart as "Earlier case records" and open their Case page; nothing is fabricated for them.
- **Case details** (the structured record, `/cases/{id}`) is secondary: "Continue with HeroOS" first, the record folded.

## 5. Migration D7 and schema contract 10

- **Change:** drop `ck_assistant_conversations_case_workflow` (`case_id IS NULL OR workflow_key IS NOT NULL`). Nothing else: `cases` never required a workflow; the API role already updates `cases` (D0) and the conversation's `case_id`/`workflow_key` (D6 column grants). RLS, Company-qualified keys, the one-conversation-per-Case uniqueness and append-only grants are unchanged.
- **Contract:** `heroos_schema_contract()` = 10; the API requires ≥ 10; the operator CLI requires exactly 10 (it gains nothing).
- **Compatibility:** the M2-NEW-08 API (contract ≥ 9) keeps working on D7 (it never creates such a Case). Existing data is untouched: a conversation that already has a Case keeps it; a conversation stored without a Case gets its Case on its next completed turn (never retroactively); a form-created Case with no chat stays a Case record.
- **Rollback:** the downgrade refuses once any conversation holds a Case without a workflow (roll forward instead); otherwise it restores the check and contract 9.
- **Deploy order:** D7, then the API and operator CLI, then the web app.

## 6. Not changed / not done here

ActionEvaluation, its presentation mapping and semantics (ALLOW is never "lawful"), Block per action, action-scoped Expert Review (no whole-Case freeze), jurisdiction isolation, concurrency (no lock during model latency; fresh state wins at commit), privacy exclusions, the staging chat-only demo (`HEROOS_CHAT_ONLY_DEMO`, preserved, not needed), M2-NEW-09 (no Expert Review service), documents.
