"""Document templates (M2-04C) without a database: bundles, values, rendering, eligibility.

The generic preview engine is tested with the fictional synthetic template
bundle (tests/fixtures/template_bundles), bound to the synthetic rule bundle,
and with small changes to it. Proves that:

- a template bundle is accepted only exactly as the schema says, pinned by its
  SHA-256, for the rule bundle it names; anything else is refused with a fixed
  code and a structural location (never wording); production refuses
  synthetic and provisional templates;
- every field and choice a template uses exists and is used, a list only
  appears item by item, and a precondition never reads a sensitive answer or
  an answer or stage the rules don't have;
- rendering is structured text: a value is inserted verbatim as text, a gap is
  visible, an unmade choice never picks an alternative;
- availability fails closed and in a fixed order, and its inputs can't include
  an employer decision record.
"""

import copy
import hashlib
import inspect
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from app.documents import eligibility, render, values
from app.documents.bundle import (
    MAX_BUNDLE_BYTES,
    TemplateBundle,
    TemplateBundleError,
    check_against_rules,
    load_template_bundle,
    parse_template_bundle,
)
from app.workflows.progression.bundle import RuleBundle, load_bundle, parse_bundle
from tests.fixtures import (
    SYNTHETIC_BUNDLE,
    SYNTHETIC_TEMPLATES,
    synthetic_bundle_pin,
    synthetic_templates_pin,
)
from tests.workflows.test_progression import Events, as_difc, intake, recorded, run

SOURCE = "a" * 64


def raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SYNTHETIC_TEMPLATES.read_bytes())
    return data


def parse(data: Mapping[str, Any]) -> TemplateBundle:
    return parse_template_bundle(json.dumps(data).encode(), file_sha256="0" * 64)


def private(data: dict[str, Any], approval: str = "approved") -> dict[str, Any]:
    data = copy.deepcopy(data)
    data |= {"provenance": "private", "approval": approval, "notice": None}
    for template in data["templates"]:
        template["source_sha256"] = SOURCE
    return data


@pytest.fixture(scope="module")
def rules() -> RuleBundle:
    return load_bundle(SYNTHETIC_BUNDLE, synthetic_bundle_pin(), production=False)


@pytest.fixture(scope="module")
def templates() -> TemplateBundle:
    return load_template_bundle(SYNTHETIC_TEMPLATES, synthetic_templates_pin(), production=False)


# --- loading -------------------------------------------------------------------------


def test_the_synthetic_bundle_loads_and_fits_the_synthetic_rules(
    templates: TemplateBundle, rules: RuleBundle
) -> None:
    check_against_rules(templates, rules)
    assert (templates.bundle_id, templates.version) == ("synthetic-templates", "synthetic.1")
    assert (templates.provenance, templates.approval) == ("synthetic", "provisional")
    assert templates.file_sha256 == synthetic_templates_pin()
    assert [t.code for t in templates.templates] == [
        "TEST-01",
        "TEST-02",
        "TEST-03",
        "TEST-04",
        "TEST-05",
    ]
    # Same content, same digest, whatever the formatting.
    assert parse(raw()).digest == templates.digest


def test_a_bundle_that_does_not_match_its_pin_is_refused(tmp_path: Path) -> None:
    changed = tmp_path / "templates.json"
    data = raw()
    data["templates"][0]["body"][0]["content"][0]["text"] = "Edited after approval."
    changed.write_text(json.dumps(data))
    with pytest.raises(TemplateBundleError) as refused:
        load_template_bundle(changed, synthetic_templates_pin(), production=False)
    assert refused.value.code == "checksum_mismatch"
    assert "Edited" not in str(refused.value)


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda p: (p, "not-a-pin"), "invalid_pin"),
        (lambda p: (p.parent / "absent.json", hashlib.sha256(b"").hexdigest()), "unreadable"),
    ],
)
def test_unusable_pins_and_paths_are_refused(
    tmp_path: Path, make: Callable[[Path], tuple[Path, str]], code: str
) -> None:
    path, pin = make(tmp_path / "x.json")
    with pytest.raises(TemplateBundleError) as refused:
        load_template_bundle(path, pin, production=False)
    assert refused.value.code == code


def test_an_oversized_bundle_is_refused(tmp_path: Path) -> None:
    big = tmp_path / "big.json"
    content = b" " * (MAX_BUNDLE_BYTES + 1)
    big.write_bytes(content)
    with pytest.raises(TemplateBundleError) as refused:
        load_template_bundle(big, hashlib.sha256(content).hexdigest(), production=False)
    assert refused.value.code == "too_large"


@pytest.mark.parametrize(
    "content",
    [b"not json", b"\xff\xfe", b'{"schema": 1, "schema": 2}', b'{"version": NaN}', b"[]"],
)
def test_malformed_files_are_refused(content: bytes) -> None:
    with pytest.raises(TemplateBundleError):
        parse_template_bundle(content, file_sha256="0" * 64)


def test_production_refuses_synthetic_and_provisional_templates(tmp_path: Path) -> None:
    with pytest.raises(TemplateBundleError) as refused:
        load_template_bundle(SYNTHETIC_TEMPLATES, synthetic_templates_pin(), production=True)
    assert refused.value.code == "synthetic_in_production"
    for approval, expected in (("provisional", "provisional_in_production"), ("approved", None)):
        path = tmp_path / f"{approval}.json"
        path.write_text(json.dumps(private(raw(), approval)))
        pin = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected is None:
            assert load_template_bundle(path, pin, production=True).approval == "approved"
            continue
        with pytest.raises(TemplateBundleError) as refused:
            load_template_bundle(path, pin, production=True)
        assert refused.value.code == expected


# --- the schema ------------------------------------------------------------------------

T0 = "templates/0"


def _mutate(path: str, value: Any) -> dict[str, Any]:
    """The synthetic bundle with one change: set (or, for ``...``, delete) a path."""
    data = raw()
    *parents, last = path.split("/")
    target: Any = data
    for part in parents:
        target = target[int(part)] if isinstance(target, list) else target[part]
    key: Any = int(last) if isinstance(target, list) else last
    if value is ...:
        del target[key]
    else:
        target[key] = value
    return data


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        ("extra", 1, "unknown_field"),
        ("schema", "heroos.template-bundle/2", "unsupported_schema"),
        ("provenance", "jj", "invalid_provenance"),
        ("approval", "maybe", "invalid_approval"),
        ("approval", "approved", "synthetic_approved"),
        ("notice", None, "synthetic_without_notice"),
        ("workflow", "probation", "unknown_workflow"),
        ("workflow", 7, "unknown_workflow"),
        ("bundle", "Not A Key", "invalid_key"),
        ("rule_bundle/versions", [], "invalid_list"),
        ("fields", [], "invalid_list"),
        ("fields/0/kind", "html", "invalid_field_kind"),
        ("fields/0/max", 10, "unknown_field"),
        ("fields/1/max", ..., "missing_field"),
        ("fields/1/max", 301, "invalid_number"),
        ("fields/5/max", 4001, "invalid_number"),
        ("fields/4/items", ..., "missing_field"),
        ("fields/4/items", 31, "invalid_number"),
        ("fields/1/items", 3, "unknown_field"),
        ("fields/1/suggest", "employee_email", "invalid_suggestion"),
        ("fields/5/suggest", "company_name", "invalid_suggestion"),
        ("fields/0/reminder", True, "invalid_reminder"),
        ("fields/1/label", " padded", "invalid_text"),
        ("fields/1/label", "Two\nlines", "invalid_text"),
        ("fields/1/key", "Recipient Name", "invalid_key"),
        ("fields/1/key", "document_date", "duplicate_key"),
        (f"{T0}/key", "Bad Key", "invalid_key"),
        (f"{T0}/code", "test-01", "invalid_key"),
        ("templates/1/code", "TEST-01", "duplicate_code"),
        ("templates/1/key", "synthetic.check_in_note", "duplicate_key"),
        (f"{T0}/kind", "contract", "invalid_template_kind"),
        (f"{T0}/review", "none", "invalid_review"),
        (f"{T0}/version", 0, "invalid_number"),
        (f"{T0}/version", True, "invalid_number"),
        (f"{T0}/source_sha256", "a" * 64, "synthetic_with_source"),
        (f"{T0}/jurisdictions", {}, "invalid_jurisdictions"),
        (f"{T0}/jurisdictions", {"ksa": {"stages": ["x"]}}, "unsupported_jurisdiction"),
        (f"{T0}/jurisdictions/uae_federal/stages", [], "invalid_list"),
        (f"{T0}/jurisdictions/uae_federal/require", {"eval": "1"}, "invalid_condition"),
        (
            f"{T0}/jurisdictions/uae_federal/require",
            {"answer": "screening.pregnancy_maternity", "in": ["no"]},
            "sensitive_answer_referenced",
        ),
        (
            f"{T0}/jurisdictions/uae_federal/require",
            {"answer": "employee.salary", "in": ["x"]},
            "unknown_answer_referenced",
        ),
        (f"{T0}/body", [], "invalid_list"),
        (f"{T0}/body/0/type", "script", "invalid_block_type"),
        (f"{T0}/body/0/content", [{"html": "<b>x</b>"}], "invalid_segment"),
        (f"{T0}/body/0/content", [{"text": "a", "field": "summary"}], "invalid_segment"),
        (f"{T0}/body/0/content", [{"text": "Bell\u0007"}], "invalid_text"),
        (f"{T0}/body/0/content", [{"text": "Bidi‮"}], "invalid_text"),
        (f"{T0}/body/0/content", [{"text": ""}], "invalid_text"),
        (f"{T0}/body/0/content", [{"break": False}], "invalid_segment"),
        (f"{T0}/body/0/content", [{"field": "no_such_field"}], "unknown_field_reference"),
        (f"{T0}/body/0/content", [{"field": "discussion_points"}], "list_outside_repeat"),
        (f"{T0}/body/0/onclick", "x", "unknown_field"),
        (f"{T0}/body/4/when/choice", "other_choice", "unknown_choice"),
        (f"{T0}/body/4/when/in", ["hybrid"], "unknown_option"),
        (f"{T0}/body/7/repeat", "summary", "invalid_repeat"),
        (f"{T0}/body/7/content", [{"text": "No item"}], "repeat_without_item"),
        (f"{T0}/choices/0/options", [{"value": "only", "label": "Only"}], "invalid_list"),
        (
            f"{T0}/choices/0/options/1",
            {"value": "in_person", "label": "Again"},
            "duplicate_key",
        ),
        (f"{T0}/choices/0/multiple", "no", "expected_boolean"),
        (f"{T0}/instructions/0/content", [{"field": "summary"}], "invalid_segment"),
        (f"{T0}/instructions/0/type", "table", "invalid_block_type"),
        (
            f"{T0}/instructions/0/when",
            {"choice": "meeting_format", "in": ["online"]},
            "unknown_field",
        ),
    ],
)
def test_bundles_outside_the_schema_are_refused(path: str, value: Any, code: str) -> None:
    with pytest.raises(TemplateBundleError) as refused:
        parse(_mutate(path, value))
    assert refused.value.code == code
    # Locations are structural: indexes and keys, never wording.
    assert "Synthetic test" not in str(refused.value)


def test_unused_fields_and_choices_are_refused() -> None:
    data = raw()
    data["fields"].append({"key": "spare", "label": "Spare", "kind": "text", "max": 10})
    with pytest.raises(TemplateBundleError) as refused:
        parse(data)
    assert refused.value.code == "unused_field"
    data = raw()
    data["templates"][1]["choices"] = [
        {
            "key": "unused",
            "label": "Unused",
            "multiple": False,
            "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
        }
    ]
    with pytest.raises(TemplateBundleError) as refused:
        parse(data)
    assert refused.value.code == "unused_choice"


def test_a_private_bundle_names_the_source_document_of_every_template() -> None:
    data = private(raw())
    assert all(t.source_sha256 == SOURCE for t in parse(data).templates)
    data["templates"][2]["source_sha256"] = None
    with pytest.raises(TemplateBundleError) as refused:
        parse(data)
    assert refused.value.code == "invalid_source_sha256"


def test_bounds_are_enforced() -> None:
    data = raw()
    data["templates"][0]["body"] = data["templates"][0]["body"] * 40
    with pytest.raises(TemplateBundleError) as refused:
        parse(data)
    assert refused.value.code == "invalid_list"
    data = raw()
    data["templates"][0]["body"][0]["content"] = [{"text": "x"}] * 65
    with pytest.raises(TemplateBundleError) as refused:
        parse(data)
    assert refused.value.code == "invalid_list"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda d: d["rule_bundle"].update(bundle="other-rules"), "rule_bundle_mismatch"),
        (lambda d: d["rule_bundle"].update(versions=["synthetic.2"]), "rule_bundle_mismatch"),
        (
            lambda d: d["templates"][0]["jurisdictions"]["uae_federal"].update(
                stages=["test_unknown_stage"]
            ),
            "unknown_stage",
        ),
        (
            lambda d: d["templates"][0]["jurisdictions"]["uae_federal"].update(
                require={"answer": "progress.test_check_in.no_such_item", "in": ["yes"]}
            ),
            "unknown_answer_referenced",
        ),
        (
            lambda d: d["templates"][0]["jurisdictions"]["uae_federal"].update(
                require={"stage_completed": "test_unknown_stage"}
            ),
            "unknown_stage_referenced",
        ),
    ],
)
def test_templates_must_fit_the_installed_rules(
    rules: RuleBundle, change: Callable[[dict[str, Any]], None], code: str
) -> None:
    data = raw()
    change(data)
    with pytest.raises(TemplateBundleError) as refused:
        check_against_rules(parse(data), rules)
    assert refused.value.code == code


def test_templates_never_run_without_rules_or_for_a_jurisdiction_the_rules_lack(
    templates: TemplateBundle,
) -> None:
    with pytest.raises(TemplateBundleError) as refused:
        check_against_rules(templates, None)
    assert refused.value.code == "rules_not_installed"
    rules_data = json.loads(SYNTHETIC_BUNDLE.read_bytes())
    del rules_data["jurisdictions"]["difc"]
    federal_only = parse_bundle(json.dumps(rules_data).encode(), file_sha256="0" * 64)
    with pytest.raises(TemplateBundleError) as refused:
        check_against_rules(templates, federal_only)
    assert refused.value.code == "jurisdiction_not_in_rules"


# --- values ----------------------------------------------------------------------------


def test_values_are_kept_exactly_as_typed(templates: TemplateBundle) -> None:
    template = templates.template("synthetic.check_in_note")
    assert template is not None
    accepted, chosen, problems = values.validate_values(
        template,
        templates.fields,
        {"summary": "Inner  spaces kept\n\tand tabs", "discussion_points": ["a", "b"]}
        | {"recipient_name": "Ann"},
        {"meeting_format": ["online"]},
    )
    assert problems == []
    assert accepted == {
        "recipient_name": "Ann",
        "discussion_points": ("a", "b"),
        "summary": "Inner  spaces kept\n\tand tabs",
    }
    assert chosen == {"meeting_format": frozenset({"online"})}


def test_value_problems_name_the_templates_own_keys_only(templates: TemplateBundle) -> None:
    template = templates.template("synthetic.check_in_note")
    assert template is not None
    _, _, problems = values.validate_values(
        template, templates.fields, {"<b>evil</b>": "x", "summary": " "}, {"<i>": ["x"]}
    )
    assert [p.loc for p in problems] == [("values",), ("values", "summary"), ("choices",)]
    assert all("evil" not in p.message and "<" not in p.message for p in problems)


# --- rendering -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "shown"),
    [("2026-10-18", "18 October 2026"), ("1990-01-01", "1 January 1990")],
)
def test_dates_are_written_out(value: str, shown: str) -> None:
    assert render.format_date(value) == shown


def test_a_multiple_choice_keeps_every_selected_alternative(templates: TemplateBundle) -> None:
    data = raw()
    data["templates"][0]["choices"][0]["multiple"] = True
    bundle = parse(data)
    template = bundle.template("synthetic.check_in_note")
    assert template is not None
    out = render.render(
        template, bundle.fields, {}, {"meeting_format": frozenset({"in_person", "online"})}
    )
    texts = [s.text for b in out.blocks for s in b.segments if s.kind == "text"]
    assert "The test conversation took place in person." in texts
    assert "The test conversation took place online." in texts
    assert "meeting_format" not in out.missing


def test_instructions_are_wording_only(templates: TemplateBundle) -> None:
    template = templates.template("synthetic.check_in_note")
    assert template is not None
    blocks = render.render_instructions(template)
    assert {s.kind for b in blocks for s in b.segments} == {"text"}
    # Never part of the letter itself.
    body = render.render(template, templates.fields, {}, {})
    assert not any(
        s.text == "[SYNTHETIC] Test instructions" for b in body.blocks for s in b.segments
    )


# --- eligibility -----------------------------------------------------------------------


def _available(
    templates: TemplateBundle,
    rules: RuleBundle | None,
    events: Events | None,
    *,
    answers: Mapping[str, object] | None = None,
    difc: bool = False,
    screening: bool = True,
    key: str = "synthetic.check_in_note",
) -> str | None:
    base, evaluation = recorded()
    if not screening:
        evaluation = intake(base, screening=False)
    if difc:
        evaluation = as_difc(evaluation)
    merged = {**base, **(answers or {})}
    progression = run(rules, evaluation, merged, events)
    template = templates.template(key)
    assert template is not None
    return eligibility.availability(
        template,
        jurisdiction=evaluation.jurisdiction.jurisdiction,
        progression=progression,
        answers=merged,
    ).reason


def test_availability_fails_closed_in_a_fixed_order(
    templates: TemplateBundle, rules: RuleBundle
) -> None:
    in_check_in = Events().pathway("less_serious").start("test_check_in")
    assert _available(templates, rules, in_check_in) is None
    assert _available(templates, None, in_check_in) == "rules_not_installed"
    assert _available(templates, rules, in_check_in, screening=False) == "case_not_ready"
    escalated = Events().pathway("less_serious").start("test_check_in").escalated("complete:test_x")
    assert _available(templates, rules, escalated) == "case_held"
    assert _available(templates, rules, Events()) == "not_at_this_stage"
    assert _available(templates, rules, Events().pathway("undetermined")) == "not_at_this_stage"
    difc_stage = Events().pathway("less_serious").start("test_difc_review")
    assert _available(templates, rules, difc_stage, difc=True) == "not_for_jurisdiction"
    assert _available(templates, rules, difc_stage, difc=True, key="synthetic.difc_note") is None
    notice = Events().pathway("serious").start("test_notice", "serious")
    assert (
        _available(templates, rules, notice, key="synthetic.specialist_letter")
        == "specialist_review_required"
    )


def test_a_precondition_is_met_only_when_definitely_true(
    templates: TemplateBundle, rules: RuleBundle
) -> None:
    events = (
        Events()
        .pathway("less_serious")
        .start("test_check_in")
        .complete("test_check_in")
        .start("test_written_note")
    )
    key = "progress.test_written_note.note_shared"
    found = {
        answer: _available(
            templates,
            rules,
            events,
            answers={} if answer is None else {key: answer},
            key="synthetic.written_note",
        )
        for answer in (None, "not_sure", "no", "yes")
    }
    assert found == {
        None: "requirement_unknown",
        "not_sure": "requirement_unknown",
        "no": "requirement_not_met",
        "yes": None,
    }


def test_availability_cannot_read_employer_decision_records() -> None:
    parameters = inspect.signature(eligibility.availability).parameters
    assert set(parameters) == {"template", "jurisdiction", "progression", "answers"}
    source = inspect.getsource(eligibility)
    assert "decision" not in source.replace("decision record", "")
