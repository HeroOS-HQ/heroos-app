"""cases before workflow: a conversation's Case may exist before its workflow is known (D7)

Chat-first Case architecture: one Ask HeroOS conversation is one Case, and the
founder's first message starts both. A Case can therefore exist before HeroOS
knows which workflow (if any) it is: "Hi Hannah" starts a Case whose workflow
is still unknown, and a later message in the same conversation may establish
a supported workflow, which then attaches to that same Case (its
``WorkflowInstance``). Nothing is faked: an unclassified Case has no workflow
instance and no ``workflow_key``.

D6's ``ck_assistant_conversations_case_workflow`` (``case_id IS NULL OR
workflow_key IS NOT NULL``) required a workflow for every attached Case, so it
is dropped. Nothing else changes: ``cases`` never required a workflow
(``WorkflowInstance`` attaches to a Case separately), the API role already
updates ``cases`` (RLS, D0) and the conversation's ``case_id`` and
``workflow_key`` (column grants, D6), and every tenant-isolation, foreign-key,
uniqueness (one conversation per Case) and append-only rule stays as it was.

``heroos_schema_contract()`` = 10: the chat-first API creates Cases without a
workflow and refuses to start on D6. The M2-NEW-08 API (contract >= 9) keeps
working on D7 (it never creates such a Case; it reads one as a conversation
without a workflow). The operator CLI gains nothing and needs exactly 10.
Deploy order: D7, then the API and the operator CLI, then the web app.
Downgrade refuses once any conversation holds a Case without a workflow: roll
forward instead.

Revision ID: da3c95517149
Revises: 8860b86ef2ba
Create Date: 2026-10-22 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "da3c95517149"
down_revision: str | Sequence[str] | None = "8860b86ef2ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONVERSATIONS = "assistant_conversations"
CONSTRAINT = "ck_assistant_conversations_case_workflow"
CONVERSATION_SHAPE = "case_id IS NULL OR workflow_key IS NOT NULL"


def guard(condition: str, message: str) -> None:
    """Abort the migration transaction if ``condition`` (SQL) is true (fixed message)."""
    op.execute(
        f"DO $guard$ BEGIN IF ({condition}) THEN "
        f"RAISE EXCEPTION 'heroos migration refused: {message}'; "
        "END IF; END $guard$;"
    )


def _set_schema_contract(value: int) -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION public.heroos_schema_contract() RETURNS integer "
        f"LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT {value} $$"
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(CONSTRAINT, CONVERSATIONS, type_="check")
    _set_schema_contract(10)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"LOCK TABLE {CONVERSATIONS} IN ACCESS EXCLUSIVE MODE")
    guard(
        f"EXISTS (SELECT FROM {CONVERSATIONS} WHERE NOT ({CONVERSATION_SHAPE}))",
        "conversations hold Cases whose workflow is not known yet; a rollback would have "
        "to detach or delete them, so roll forward instead (deletion is decided by PRIV-020)",
    )
    _set_schema_contract(9)
    op.create_check_constraint(CONSTRAINT, CONVERSATIONS, CONVERSATION_SHAPE)
