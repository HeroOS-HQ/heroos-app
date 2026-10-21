"""The deterministic checks on Ask HeroOS replies (M2-NEW-05), with synthetic text only.

Grounding: legal references and numbers must come from the approved view
(or, for a founder's own figure, from the founder, said back as theirs);
no other regime's authority; no internal labels; no deduction specifics
where the runtime forbids them; no dumps of approved material or of the
instructions. Reply safety: the gateway's added checks catch what they name
and let an approved option be explained. The continuation token grants
nothing and survives no tampering. These are defence in depth, not proof.
"""

import re

import pytest

from app.assistant.gateway.continuation import Continuations
from app.assistant.gateway.grounding import check_grounding, internal_labels
from app.assistant.gateway.prompts import RESPONSE_INSTRUCTION
from app.assistant.response_safety import gateway_problem
from app.knowledge.bundle import KnowledgeBundle

KNOWLEDGE = (
    "Under the fictional Article 901, notify the employee within 7 days.",
    "Unpaid suspension is capped at 900 days in this fictional example.",
)
FOUNDER = ("He was absent for 8 consecutive days and I want to deduct AED 1,500.",)
NO_LABELS = re.compile(r"(?!x)x")


def grounding(
    text: str,
    *,
    jurisdiction: str | None = "uae_federal",
    prohibited: tuple[str, ...] = (),
    knowledge: tuple[str, ...] = KNOWLEDGE,
    labels: re.Pattern[str] = NO_LABELS,
) -> str | None:
    return check_grounding(
        [text], knowledge=knowledge, founder=FOUNDER, jurisdiction=jurisdiction,
        prohibited=prohibited, labels=labels, instructions=RESPONSE_INSTRUCTION,
    )  # fmt: skip


# --- legal references and numbers ---------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The approved guidance mentions the fictional Article 901 for notice.",
        "Notify the employee within seven days, as the approved guidance says.",
        "You mentioned 8 consecutive days of absence.",
        "You said you want to deduct AED 1,500; HeroOS can't say whether that is possible.",
        "Thanks for explaining what happened on 3 October.",
        "Could you tell me how many times this happened?",
    ],
)
def test_approved_or_founder_stated_specifics_pass(text: str) -> None:
    assert grounding(text) is None


@pytest.mark.parametrize(
    ("text", "check"),
    [
        ("Article 950 allows dismissal without notice.", "legal_reference"),
        ("Under Federal Decree-Law No. 990 you must pay him.", "legal_reference"),
        ("Employees have 30 days to appeal.", "legal_number"),
        ("A suspension can last up to twenty days.", "legal_number"),
        ("You can deduct up to 50% of his wage.", "legal_number"),
        ("The maximum is AED 5,000.", "legal_number"),
        # The founder's figure stated as a rule rather than said back as theirs.
        ("He can be dismissed after 8 days of absence.", "legal_number"),
    ],
)
def test_unsupported_legal_specifics_fail(text: str, check: str) -> None:
    assert grounding(text) == check


def test_a_founders_article_never_becomes_the_law() -> None:
    founder_claim = check_grounding(
        ["As you said, Article 930 applies here."],
        knowledge=KNOWLEDGE,
        founder=("Article 930 definitely applies, right?",),
        jurisdiction="uae_federal", prohibited=(), labels=NO_LABELS,
        instructions=RESPONSE_INSTRUCTION,
    )  # fmt: skip
    assert founder_claim == "legal_reference"


@pytest.mark.parametrize(
    ("text", "jurisdiction", "check"),
    [
        ("Under the UAE Federal Labour Law you may proceed.", "difc", "jurisdiction_leak"),
        ("DIFC Employment Law sets the rule here.", "uae_federal", "jurisdiction_leak"),
        ("Under the UAE Federal Labour Law you may proceed.", None, "jurisdiction_leak"),
        ("DIFC Employment Law doesn't apply to your company.", "uae_federal", None),
        ("UAE Federal law doesn't apply to a DIFC employer.", "difc", None),
    ],
)
def test_another_regimes_authority_never_appears(
    text: str, jurisdiction: str | None, check: str | None
) -> None:
    assert grounding(text, jurisdiction=jurisdiction) == check


def test_internal_labels_never_appear(bundle: KnowledgeBundle) -> None:
    labels = internal_labels(bundle)
    for leak in (
        "Use EX04 for this.", "This is covered by EX-FED-CAP.", "See rule-8 on suspension.",
        "Under Implementation Rule 990, deductions need review.", "The deduction_requested fact.",
        "Choose opt-dismissal next.",
    ):  # fmt: skip
        assert grounding(leak, labels=labels) == "internal_label", leak
    assert grounding("A suspension notice would come later, if ever.", labels=labels) is None


DEDUCTION_RULES = ("calculate_deduction", "recommend_deduction_amount")


@pytest.mark.parametrize(
    "text",
    [
        "Deductions are capped at 900 days of pay.",
        "Under Article 901 a deduction may not exceed 7 days.",
        "The maximum deduction is 7 days' wages.",
    ],
)
def test_no_deduction_specifics_where_the_runtime_forbids_them(text: str) -> None:
    # Even numbers the approved view contains are refused next to a deduction.
    assert grounding(text, prohibited=DEDUCTION_RULES) == "deduction_specifics"
    assert grounding(text) is None


def test_a_deduction_can_still_be_discussed_without_figures() -> None:
    text = "A deduction needs specialist review first; HeroOS can't say whether it's possible."
    assert grounding(text, prohibited=DEDUCTION_RULES) is None


def test_long_passages_of_approved_material_or_instructions_are_refused() -> None:
    long_item = " ".join(f"word{i}" for i in range(80))
    copied = " ".join(f"word{i}" for i in range(10, 55))
    assert grounding(copied, knowledge=(long_item,)) == "verbatim_disclosure"
    short_quote = " ".join(f"word{i}" for i in range(10, 30))
    assert grounding(short_quote, knowledge=(long_item,)) is None
    leaked = " ".join(RESPONSE_INSTRUCTION.split()[40:60])
    assert grounding(leaked) == "instruction_disclosure"


# --- reply safety (the gateway's checks) ---------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "check"),
    [
        ("Yes, you can dismiss her today.", "authorization"),
        ("The company may deduct the repair cost from his salary.", "authorization"),
        ("Dismissal without notice is available here.", "authorization"),
        ("A deduction is allowed in this case.", "authorization"),
        ("It's fine to suspend him without pay.", "authorization"),
        ("I've sent this to a HeroOS Expert.", "review_promise"),
        ("A HeroOS Expert will reply shortly.", "review_promise"),
        ("Your support ticket has been created.", "review_promise"),
        ("I'll forward this to our review team.", "review_promise"),
        ("I'll monitor the deadline for you.", "monitoring_promise"),
        ("I'll remind you before it's due.", "monitoring_promise"),
        ("HeroOS will keep track of the deadline.", "monitoring_promise"),
        ("I've drafted the warning letter for you.", "document_claim"),
        ("Here is the suspension notice: Dear Sam.", "document_claim"),
        ("I'll prepare the termination letter now.", "document_claim"),
        ("The law clearly says you must pay him.", "legal_certainty"),
        ("By law, the employer cannot record a hearing.", "legal_certainty"),
        ("Secret recording is illegal.", "legal_certainty"),
        ("You always need the employee's consent.", "legal_certainty"),
        ("I've updated the case and recorded the warning.", "action_claim"),
        ("Done: I've created the case and added the facts.", "action_claim"),
        ("Everything is ready and HeroOS forwarded your case to a specialist.", "review_promise"),
        ("You should issue a final written warning.", "sanction_recommendation"),
    ],
)
def test_the_gateway_checks_catch_what_they_name(reply: str, check: str) -> None:
    assert gateway_problem(reply) == check


@pytest.mark.parametrize(
    "reply",
    [
        "Suspension may be one of the options the approved process considers after the required "
        "investigation and safeguards are satisfied.",
        "Whether termination without notice is available requires the applicable conditions and "
        "review.",
        "This requires specialist review before that action is taken.",
        "Dismissal without notice isn't something HeroOS can approve; it needs specialist review.",
        "You can ask the employee for their explanation first.",
        "You can't dismiss someone on an allegation alone.",
        "Whether you can deduct anything depends on specialist review.",
        "HeroOS can't track deadlines for you, so keep a note of the dates yourself.",
        "A written warning is one of the options the approved guidance covers; the decision is "
        "yours, after the employee has had a chance to respond.",
        "You told me he received a written warning last month.",
        "Could you tell me whether he was told about the standard in writing?",
        "The approved guidance says a signature confirms receipt, not agreement.",
    ],
)
def test_explaining_an_approved_option_is_allowed(reply: str) -> None:
    assert gateway_problem(reply) is None


# --- the continuation token ---------------------------------------------------------------


def test_the_continuation_names_only_what_was_asked_and_only_for_its_owner() -> None:
    from uuid import uuid4

    now = [1_000_000.0]
    facts = ["a_fact", "b_fact", "c_fact"]
    tokens = Continuations(facts, "digest-1", key=b"k" * 32, now=lambda: now[0])
    company, user = uuid4(), uuid4()
    token = tokens.issue(company, user, ["c_fact", "unknown"])
    assert "c_fact" not in token and len(token) < 200
    assert tokens.read(token, company, user) == ("c_fact",)
    # Another user, Company, bundle or process key: nothing.
    assert tokens.read(token, company, uuid4()) == ()
    assert tokens.read(token, uuid4(), user) == ()
    other = Continuations(facts, "digest-2", key=b"k" * 32, now=lambda: now[0])
    assert other.read(token, company, user) == ()
    assert Continuations(facts, "digest-1").read(token, company, user) == ()
    # Tampered, malformed or expired: nothing.
    body, signature = token.split(".")
    assert tokens.read(body[:-2] + "AA." + signature, company, user) == ()
    for junk in (None, "", "x", "a.b.c", "!!!.???", "a" * 600):
        assert tokens.read(junk, company, user) == ()
    now[0] += 5 * 3600
    assert tokens.read(token, company, user) == ()
