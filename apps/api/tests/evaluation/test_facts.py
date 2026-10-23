"""The fact trust pipeline and deterministic canonicalization (M2-NEW-06).

Only ENGINE_TRUSTED values enter a rule, and only the server makes a value
ENGINE_TRUSTED: a bare direct answer to the one question it asked, a
confirmation of its own canonical reading, or the Company Blueprint. The AI's
reading of the founder's words, even of real words, never is.
"""

from datetime import date

import pytest

from app.evaluation.facts import (
    Asked,
    PriorState,
    StatedFact,
    answer_in_words,
    canonical,
    contradicted,
    dated,
    leading_answer,
    one_proposition,
    parse_count,
    parse_insistence,
    parse_yes_no,
    proposition,
    says_not_known,
    trust_facts,
)
from app.evaluation.model import TwoState
from app.evaluation.snapshot import FactSchema, WorkflowExecution
from app.workflows.conditions import Tri
from app.workflows.definition import DISCIPLINARY_V2
from tests.fixtures.evaluation import Artifacts

BLUEPRINT = {"employee_count": 12}


@pytest.fixture
def execution(artifacts: Artifacts) -> WorkflowExecution:
    found = artifacts.snapshot().execution("disciplinary")
    assert found is not None
    return found


def trust(execution: WorkflowExecution, message: str, *, stated=(), prior=None):  # type: ignore[no-untyped-def]
    return trust_facts(
        execution,
        stated=list(stated),
        message=message,
        prior=prior or PriorState(),
        blueprint=BLUEPRINT,
    )


# --- canonicalization: bare answers only ------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Yes.", "yes"),
        ("yes", "yes"),
        ("Yep", "yes"),
        ("No.", "no"),
        ("Nope!", "no"),
        ("Not sure", "not_sure"),
        ("I don't know", "not_sure"),
        # The canonical value itself: a reading of "I don't know", noted for the Case record.
        ("not_sure", "not_sure"),
        # Uncertainty with more words is still no bare answer (the reading may note it).
        ("no idea, I'd have to check", None),
        ("I sort of spoke to him.", None),
        ("Yes, but only verbally.", None),
        ("Maybe", None),
        ("Yes, he didn't", None),
        ("No... well, yes", None),
        ("I spoke to him about it", None),
        ("He has", None),
        ("y" * 200, None),
        # A yes or no with more words is never the answer: the rest may be about something else.
        ("Yes, he has.", None),
        ("Yes, and he was late again today.", None),
        ("No, not yet.", None),
        ("No, they haven't contacted anyone.", None),
        ("No no", None),
    ],
)
def test_yes_no_answers(text: str, expected: str | None) -> None:
    assert parse_yes_no(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Eight.", 8),
        ("8", 8),
        ("8 days", 8),
        ("eight days", 8),
        ("twice", 2),
        ("20 working days", 20),
        ("He's been gone basically all week.", None),
        ("about 8", None),
        ("8 or 9", None),
        ("around eight days", None),
        ("a few days", None),
        ("more than 8", None),
        ("8-10", None),
        ("8 days, maybe 9", None),
        ("all week", None),
    ],
)
def test_exact_numbers_only(text: str, expected: int | None) -> None:
    assert parse_count(text) == expected


def test_a_count_above_its_bound_is_not_an_answer() -> None:
    assert parse_count("400", 365) is None and parse_count("365", 365) == 365


def test_choices_come_from_the_definition(execution: WorkflowExecution) -> None:
    question = DISCIPLINARY_V2.question("context.location")
    assert question is not None
    # The definition's own options: "Yes, at work or while working" / "No, outside work".
    location = FactSchema("incident_location", "Location", "choice", question.options)
    assert canonical(location, "No.") == "outside_work"
    assert canonical(location, "Yes") == "at_work"
    assert canonical(location, "No, outside work") == "outside_work"
    # Live dev-stack run: a reply about something else, never this option.
    assert canonical(location, "No, they haven't contacted anyone.") is None
    assert canonical(location, "No, it was at home") is None
    assert canonical(location, "Not sure") == "not_sure"
    assert canonical(location, "In the car park") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Yes", "insists"),
        ("Yes, I still want to go ahead.", "insists"),
        ("Yes, he was late again.", None),
        ("No, he was late again.", None),
        ("I still want to go ahead", "insists"),
        ("No", "declines"),
        ("OK, understood.", "acknowledged"),
        ("Understood", "acknowledged"),
        ("I WANT TO SUSPEND HIM FOR 20 DAYS!!!", None),
        ("Why?", None),
        ("I suppose I'll go ahead", None),
        ("I don't want to go ahead", None),
    ],
)
def test_insistence_is_explicit_never_tone(text: str, expected: str | None) -> None:
    assert parse_insistence(text) == expected


# --- the pipeline -------------------------------------------------------------------------------


def test_a_wrong_reading_of_real_words_is_never_trusted(execution: WorkflowExecution) -> None:
    """: "I did NOT speak to the employee", read by a bad model as "yes"."""
    words = "I did NOT speak to the employee."
    stated = [StatedFact("given_opportunity_to_explain", "yes", words, True, True)]
    assert contradicted("yes", words)
    result = trust(execution, words, stated=stated)
    assert "given_opportunity_to_explain" not in result.facts.engine
    assert result.facts.level("given_opportunity_to_explain") == "proposed"


def test_an_approximate_number_sets_no_threshold(execution: WorkflowExecution) -> None:
    """: "He's been gone all week" is never an exact number of days."""
    words = "He's been gone basically all week."
    stated = [StatedFact("proposed_suspension_days", "5", words, True, True)]
    result = trust(execution, words, stated=stated)
    assert "proposed_suspension_days" not in result.facts.engine
    assert result.facts.level("proposed_suspension_days") == "proposed"


def test_a_plain_answer_to_the_known_question_is_trusted(execution: WorkflowExecution) -> None:
    """: HeroOS asked one yes/no question; "Yes." is a canonical yes."""
    prior = PriorState(asked=(Asked("fact", "given_opportunity_to_explain"),))
    result = trust(execution, "Yes.", prior=prior)
    assert result.facts.engine["given_opportunity_to_explain"] == "yes"
    assert result.facts.sources["given_opportunity_to_explain"] == "direct_answer"
    assert result.answered
    counted = trust(
        execution, "Eight.", prior=PriorState(asked=(Asked("fact", "proposed_suspension_days"),))
    )
    assert counted.facts.engine["proposed_suspension_days"] == 8


def test_a_yes_or_no_with_more_words_is_never_trusted_as_the_answer(
    execution: WorkflowExecution,
) -> None:
    """Live dev-stack run: "No, they haven't contacted anyone." answered something else."""
    prior = PriorState(asked=(Asked("fact", "given_opportunity_to_explain"),))
    for message in ("No, they haven't contacted anyone.", "Yes, he has."):
        result = trust(execution, message, prior=prior)
        assert "given_opportunity_to_explain" not in result.facts.engine
        assert not result.answered
    confirm = PriorState(asked=(Asked("confirm", "proposed_suspension_days", 20),))
    confirmed = trust(execution, "Yes, and he was late again.", prior=confirm)
    assert "proposed_suspension_days" not in confirmed.facts.engine


def test_a_short_answer_means_nothing_without_one_known_question(
    execution: WorkflowExecution,
) -> None:
    assert "given_opportunity_to_explain" not in trust(execution, "Yes.").facts.engine
    two = PriorState(
        asked=(
            Asked("fact", "given_opportunity_to_explain"),
            Asked("fact", "investigation_completed"),
        )
    )
    assert not trust(execution, "Yes.", prior=two).facts.engine.get("investigation_completed")
    assert "given_opportunity_to_explain" not in trust(execution, "Yes.", prior=two).facts.engine


def test_heroos_own_words_are_never_evidence(execution: WorkflowExecution) -> None:
    """: only the founder's current message and trusted state count; replies never do."""
    result = trust(execution, "Thanks, that's helpful.", prior=PriorState())
    assert dict(result.facts.engine) == {"headcount": 12}
    assert result.facts.sources["headcount"] == "blueprint"


def test_the_newest_explicit_correction_controls(execution: WorkflowExecution) -> None:
    """: a different value stated now voids the trusted one until confirmed again."""
    prior = PriorState(engine={"proposed_suspension_days": 8})
    kept = trust(execution, "Fine.", prior=prior)
    assert kept.facts.engine["proposed_suspension_days"] == 8
    words = "Sorry, I meant 12 days."
    stated = [StatedFact("proposed_suspension_days", "12", "I meant 12 days", True, True)]
    corrected = trust(execution, words, stated=stated, prior=prior)
    assert "proposed_suspension_days" not in corrected.facts.engine
    assert corrected.facts.conversational["proposed_suspension_days"] == "12"
    # The same value restated keeps it.
    same = [StatedFact("proposed_suspension_days", "8", "8 days", True, True)]
    assert (
        trust(execution, "8 days", stated=same, prior=prior).facts.engine[
            "proposed_suspension_days"
        ]
        == 8
    )
    # An older statement doesn't void a newer trusted answer.
    old = [StatedFact("proposed_suspension_days", "12", "12 days", True, False)]
    assert (
        trust(execution, "Fine.", stated=old, prior=prior).facts.engine["proposed_suspension_days"]
        == 8
    )


def test_ambiguous_text_asks_never_guesses(execution: WorkflowExecution) -> None:
    """: a hedged answer to the known question is not a value."""
    prior = PriorState(asked=(Asked("fact", "given_opportunity_to_explain"),))
    result = trust(execution, "I sort of spoke to him.", prior=prior)
    assert "given_opportunity_to_explain" not in result.facts.engine
    assert not result.answered


def test_a_confirmation_trusts_only_the_servers_canonical_candidate(
    execution: WorkflowExecution,
) -> None:
    asked = Asked("confirm", "proposed_suspension_days", 20)
    confirmed = trust(execution, "Yes", prior=PriorState(asked=(asked,)))
    assert confirmed.facts.engine["proposed_suspension_days"] == 20
    assert confirmed.facts.sources["proposed_suspension_days"] == "confirmation"
    declined = trust(execution, "No", prior=PriorState(asked=(asked,)))
    assert "proposed_suspension_days" not in declined.facts.engine
    assert "proposed_suspension_days" in declined.declined


def test_insistence_and_acknowledgment_are_separate(execution: WorkflowExecution) -> None:
    shown = {"fictional_cap": TwoState("fictional_cap", True, False, Tri.FALSE)}
    asked = (Asked("insistence", "fictional_cap", "opt-suspension"),)
    understood = trust(execution, "Understood.", prior=PriorState(two_state=shown, asked=asked))
    state = understood.two_state["fictional_cap"]
    assert state.acknowledged and state.insists is Tri.FALSE
    insisted = trust(execution, "Yes.", prior=PriorState(two_state=shown, asked=asked))
    assert insisted.two_state["fictional_cap"].insists is Tri.TRUE
    shouted = trust(execution, "SUSPEND HIM!!!", prior=PriorState(two_state=shown, asked=asked))
    assert shouted.two_state["fictional_cap"].insists is Tri.FALSE


def test_sensitive_facts_are_never_typed_for_execution(execution: WorkflowExecution) -> None:
    assert "dismissal_without_notice_considered" not in execution.schemas
    prior = PriorState(asked=(Asked("fact", "dismissal_without_notice_considered"),))
    assert (
        "dismissal_without_notice_considered"
        not in trust(execution, "Yes", prior=prior).facts.engine
    )


def test_continued_values_are_revalidated(execution: WorkflowExecution) -> None:
    prior = PriorState(
        engine={
            "proposed_suspension_days": "lots",
            "unknown_fact": "yes",
            "given_opportunity_to_explain": "yes",
        }
    )
    engine = trust(execution, "ok", prior=prior).facts.engine
    assert engine == {"given_opportunity_to_explain": "yes", "headcount": 12}


# --- a confirmation asked as the fact's own question again (robustness pass) ----------------


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("No.", "no"),
        ("Yes", "yes"),  # a direct answer, even against the earlier reading
        ("Not sure", "not_sure"),
        ("No, he hasn't", None),  # more than the answer: never trusted
        ("yes thats right", None),
        ("I think so", None),
    ],
)
def test_a_reask_is_answered_directly_never_as_yes_thats_right(
    execution: WorkflowExecution, reply: str, expected: str | None
) -> None:
    """HeroOS asked the fact's own question again (no candidate): the answer means what it says
    about that question; "yes" never confirms the earlier reading of "no"."""
    asked = Asked("confirm", "employee_aware_of_relevant_policy", None)
    result = trust(execution, reply, prior=PriorState(asked=(asked,)))
    assert result.facts.engine.get("employee_aware_of_relevant_policy") == expected
    assert result.answered is (expected is not None)
    if expected is not None:
        assert result.facts.sources["employee_aware_of_relevant_policy"] == "confirmation"


@pytest.mark.parametrize(
    ("value", "excerpt", "sentence", "hedged"),
    [
        # A hedge anywhere in the founder's sentence counts, not only inside the cited words.
        ("raised_before", "gave her a verbal disciplinary about it once",
         "i think her line manager gave her a verbal disciplinary about it once, but id need to "
         "check with him", True),
        ("no", "nobody saw it", "Not that I know of, nobody saw it", True),
        ("yes", "there were messages", "I was told there were messages", True),
        # Hearsay never weakens a no: the founder heard about it later because nobody saw it.
        ("no", "Nobody actually saw it",
         "Nobody actually saw it. I was told about it afterwards", False),
        ("no", "he hasn't been in touch", "I don't think he has been in touch", True),
        # Plain statements stay statements; a fact about the employee being told is not hearsay.
        ("yes", "he was told the rules", "He was told the rules last month.", False),
        ("no", "I haven't spoken to him", "No, I haven't spoken to him.", False),
        ("yes", "I did speak to him", "He didn't come in on Monday but I did speak to him", False),
        ("not_sure", "I'd need to check", "No idea, I'd need to check.", False),
    ],
)  # fmt: skip
def test_a_hedge_in_the_founders_sentence_makes_any_reading_uncertain(
    value: str, excerpt: str, sentence: str, hedged: bool
) -> None:
    assert contradicted(value, excerpt, context=sentence) is hedged


@pytest.mark.parametrize(
    ("text", "bare"),
    [
        ("i don't know to be honest", True),
        ("no idea tbh", True),
        ("No idea, I'd have to check.", True),
        ("Not sure.", True),
        ("I'm not sure, I wasn't there", True),
        # Naming what they don't know, or saying more, is not a bare answer.
        ("I don't know if anyone saw it", False),
        ("I wasn't there, my manager might know", False),
        ("No, nobody has heard from him.", False),
    ],
)
def test_only_not_known_is_a_bare_answer(text: str, bare: bool) -> None:
    from app.evaluation.facts import only_not_known

    assert only_not_known(text) is bare


def test_saying_they_dont_know_is_said_plainly_whatever_the_readings_confidence(
    execution: WorkflowExecution,
) -> None:
    stated = [
        StatedFact("employee_aware_of_relevant_policy", "not_sure", "i don't know", False, True)
    ]
    result = trust(execution, "i don't know to be honest", stated=stated)
    assert result.facts.conversational["employee_aware_of_relevant_policy"] == "not_sure"
    assert "employee_aware_of_relevant_policy" not in result.facts.engine


@pytest.mark.parametrize(
    ("correction", "explicit"),
    [
        ("Nobody actually saw it.", True),
        ("I don't think anyone actually saw it.", False),  # hedged: still voids
    ],
)
def test_a_correction_voids_the_trusted_value_even_when_hedged(
    execution: WorkflowExecution, correction: str, explicit: bool
) -> None:
    """Found in the final run: a correction read as hedged left the old trusted value standing."""
    prior = PriorState(engine={"evidence.witnesses": "yes"})
    stated = [StatedFact("evidence.witnesses", "no", correction, explicit, True)]
    result = trust(execution, correction, stated=stated, prior=prior)
    assert "evidence.witnesses" not in result.facts.engine
    assert ("evidence.witnesses" in result.facts.conversational) is explicit


def test_the_same_value_hedged_again_keeps_the_trusted_one(execution: WorkflowExecution) -> None:
    prior = PriorState(engine={"evidence.witnesses": "yes"})
    stated = [StatedFact("evidence.witnesses", "yes", "I think two of them saw it", False, True)]
    result = trust(execution, "I think two of them saw it", stated=stated, prior=prior)
    assert result.facts.engine["evidence.witnesses"] == "yes"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("No. The rule was never explained to her.", "no"),
        ("No, nobody has contacted us.", "no"),
        ("Yes, but only once.", "yes"),
        ("Yes - last month.", "yes"),
        ("No and we don't have any evidence either", "no"),
        ("Yep, that's right", "yes"),
        ("Correct, it was the 14th.", "yes"),
        # A bare answer is parse_yes_no's; no plain answer opens these.
        ("No.", None),
        ("Yes!", None),
        ("No idea, sorry.", None),
        ("nope nobody heard frm him", None),
        ("Nobody saw it.", None),
        ("Not really, no.", None),
        ("Maybe, I'd have to check.", None),
    ],
)
def test_a_reply_may_open_with_a_plain_yes_or_no(text: str, expected: str | None) -> None:
    assert leading_answer(text) == expected


@pytest.mark.parametrize(
    ("message", "read", "expected"),
    [
        ("No. The rule was never explained to her.", "no", "no"),
        ("Yes, but only once.", "yes", "yes"),
        # The understanding read another answer, or none: the opening word answers nothing.
        ("No, he knew the rule well.", "yes", None),
        ("No, nobody has heard from him.", None, None),
        # Doubt anywhere in the reply.
        ("Yes, I think so.", "yes", None),
        ("No. I was told he never got it.", "no", None),
        # A doubt about another statement doesn't qualify the answer (hybrid certification).
        ("No, she never got the handbook, and honestly I don't think she'd read it.", "no", "no"),
        ("No, but I'd need to check.", "no", None),
    ],
)
def test_an_answer_in_more_words_binds_only_with_the_same_reading_and_no_doubt(
    execution: WorkflowExecution, message: str, read: str | None, expected: str | None
) -> None:
    schema = execution.schemas["employee_aware_of_relevant_policy"]
    assert answer_in_words(schema, message, read) == expected


@pytest.mark.parametrize(
    "text", ["I can't confirm which entity employs him yet.", "We cannot confirm that today."]
)
def test_saying_they_cant_confirm_is_saying_they_dont_know(text: str) -> None:
    """Found in the final pass: "I can't confirm the entity yet" was asked again at once."""
    assert says_not_known(text)


DATE = FactSchema("incident.date", "Date of the incident", "date")


@pytest.mark.parametrize(
    ("value", "words", "wrong"),
    [
        # Found in the acceptance run (the scenario day: Thursday 22 October 2026).
        ("2026-10-18", "PUSHED a customer saturday night", True),
        ("2026-10-17", "pushed a customer saturday night", False),
        ("2026-10-21", "waiter pushed a customer sat night", True),
        ("2026-10-17", "waiter pushed a customer sat night", False),
        ("2026-10-20", "He hasn't come in since Monday", True),
        ("2026-10-19", "He hasn't come in since Monday", False),
        ("2026-10-14", "tues evening", True),
        ("2026-10-15", "Thurs morning", False),
        # No weekday named: nothing to compare (and no inference here).
        ("2026-10-21", "it happened yesterday", False),
        ("2026-10-16", "my friend saw it last month on the 16th", False),
        # Any weekday the words name may be the day ("not Monday, not Tuesday").
        ("2026-10-19", "not Monday, not Tuesday, not yesterday", False),
    ],
)
def test_a_date_on_another_weekday_than_its_words_name_is_never_trusted(
    value: str, words: str, wrong: bool
) -> None:
    """The model's weekday arithmetic is never the founder's day: such a reading stays proposed
    (never noted or trusted). It never computes a date itself."""
    assert contradicted(value, words, DATE) is wrong
    assert not contradicted(value, words)  # other kinds of fact: not a date question


@pytest.mark.parametrize(
    ("message", "excerpt", "value", "doubted"),
    [
        # The brief's examples: a doubt qualifies the statement it is part of.
        ("He was late again, but I don't think I need his side.", "He was late again", "yes",
         False),
        ("She didn't come in Monday. I think her manager tried calling her.",
         "She didn't come in Monday", "no", False),
        ("She didn't come in Monday. I think her manager tried calling her.",
         "her manager tried calling her", "yes", True),
        # Found in the hybrid certification.
        ("I haven't spoken to her about it, and honestly I don't think I need her side",
         "I haven't spoken to her about it", "no", False),
        ("I sat down with him on Monday and he told me his mother has been ill, which I think "
         "has been weighing on him", "I sat down with him on Monday", "yes", False),
        # A doubt about the whole sentence, or one opening it, qualifies all of it.
        ("I think her manager gave her a verbal warning once, but I'd need to check",
         "gave her a verbal warning once", "yes", True),
        ("Her manager gave her a verbal warning, but I'd need to check with HR.",
         "Her manager gave her a verbal warning", "yes", True),
        ("I think he was told, but not in writing", "not in writing", "verbal_only", True),
        ("Nobody saw it, at least I don't think so.", "Nobody saw it", "no", True),
        ("There were messages, or so I was told.", "There were messages", "yes", True),
        # Without a break between them, statements keep their doubt together.
        ("I think he was late and his manager warned him", "his manager warned him", "yes", True),
        # A doubt that names its own subject is its own statement.
        ("Not sure about the date, but he definitely swore at her.",
         "he definitely swore at her", "yes", False),
        ("I spoke to her yesterday, not sure if she understood.", "I spoke to her yesterday",
         "yes", False),
    ],
)  # fmt: skip
def test_a_doubt_qualifies_the_statement_it_is_part_of_never_the_whole_message(
    message: str, excerpt: str, value: str, doubted: bool
) -> None:
    assert contradicted(value, excerpt, context=proposition(message, excerpt)) is doubted


THURSDAY = date(2026, 10, 22)


@pytest.mark.parametrize(
    ("value", "words", "placed"),
    [
        # Found in the hybrid certification: the 20th was a Tuesday in 2020 too.
        ("2020-10-20", "since Tuesday 20 October", "2026-10-20"),
        ("2026-10-20", "since Tuesday 20 October", "2026-10-20"),
        ("2020-10-05", "the 5th of october", "2026-10-05"),
        ("2026-10-08", "already warned for it 8 oct", "2026-10-08"),
        ("2026-10-20", "Oct 20th", "2026-10-20"),
        ("2026-10-14", "Wednesday, Thursday and Friday (14th to 16th October)", "2026-10-14"),
        # The most recent such day not after today.
        ("2026-11-20", "on 20 November", "2025-11-20"),
        # A year the founder gives is theirs.
        ("2024-10-05", "on 5 October 2024", "2024-10-05"),
        # A day the words don't name, or one no recent year puts on the weekday they name.
        ("2026-10-21", "since Tuesday 20 October", None),
        ("2026-10-20", "since Wednesday 20 October", None),
        # No day with its month: the other checks decide.
        ("2026-10-19", "since Monday", "2026-10-19"),
        ("not_sure", "not sure when", "not_sure"),
    ],
)
def test_a_day_and_month_are_put_on_the_calendar_by_the_server(
    value: str, words: str, placed: str | None
) -> None:
    assert dated(value, words, THURSDAY) == placed


@pytest.mark.parametrize(
    ("question", "single"),
    [
        ("Had this been raised with the employee before?", True),
        ("Has this happened before?", True),
        # One proposition in two forms: a "yes" means at work either way.
        ("Did the incident happen at work, or while the employee was carrying out work duties?",
         True),
        ("Has a manager ever raised it with him, for example by speaking to him or warning him?",
         True),
        # Final ontology pass: alternatives, or a question that points back.
        ("Is this a new issue, or has it been raised before?", False),
        ("Did it happen before or was this the first time?", False),
        ("Has it come up with Venkatesh before, or is it new?", False),
        ("Was that the case?", False),
        ("Is that right?", False),
        ("Had she been told? And has a sanction been issued?", False),
        (None, True),
    ],
)  # fmt: skip
def test_a_bare_yes_or_no_answers_only_a_question_with_one_proposition(
    question: str | None, single: bool
) -> None:
    assert one_proposition(question) is single


@pytest.mark.parametrize(
    ("value", "excerpt", "wrong"),
    [
        # A contrast word clarifies; it never makes a statement doubtful (final ontology pass).
        ("verbal_only", "spoken to him twice, but only verbally", False),
        ("raised_before", "I've spoken to him twice, but only verbally", False),
        ("yes", "spoke to him twice, but never in writing", False),
        ("yes", "he was told, though nothing was written down", False),
        # Negation in the statement itself still contradicts a "yes".
        ("yes", "I did not speak to him, but I left a note", True),
        ("yes", "nobody saw it", True),
        # Partial words still qualify it.
        ("yes", "he was sort of told", True),
        ("raised_before", "it was raised with him sometimes", True),
    ],
)
def test_a_contrast_word_never_downgrades_a_statement(
    value: str, excerpt: str, wrong: bool
) -> None:
    assert contradicted(value, excerpt) is wrong


def test_a_bare_answer_to_a_question_with_alternatives_binds_nothing(
    artifacts: Artifacts,
) -> None:
    """Final ontology pass: "Is this new, or has it been raised before?" then "Yes": which one is
    yes? Nothing is bound; with one proposition, the same "Yes" is a direct answer."""
    execution = artifacts.snapshot().execution("disciplinary")
    assert execution is not None
    prior = PriorState(asked=(Asked("fact", "incident.history"),))
    common = {"stated": (), "message": "Yes", "prior": prior, "blueprint": {}}
    two_sided = trust_facts(execution, bare_answers=False, **common)  # type: ignore[arg-type]
    assert "incident.history" not in two_sided.facts.engine
    single = trust_facts(execution, **common)  # type: ignore[arg-type]
    assert single.facts.engine["incident.history"] == "raised_before"
