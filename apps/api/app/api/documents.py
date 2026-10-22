"""Document templates and safe previews (M2-04C): list, open and preview. Nothing is written.

Same dependency chain as every Company route, for Company administrators only,
in a transaction that can't write (``CompanyAdminReadOnlyDb``: PostgreSQL
refuses any write, and the ORM refuses to flush one).

- ``GET .../cases/{case}/documents``: every template of the installed template
  bundle and whether it can be previewed in this Case now, with the reason
  when it can't (``app.documents.eligibility``).
- ``GET .../cases/{case}/documents/{template}``: an available template's form:
  its fields, choices and employer instructions, with suggestions taken only
  from this Case's own Company and subject.
- ``POST .../cases/{case}/documents/{template}/preview``: the template filled
  with the values in the request body, as structured text blocks with a
  watermark. POST only so personal details never travel in a URL; availability
  is checked again here, never trusted from an earlier read.

A preview is never stored, cached, logged, sent, signed or issued: the values
exist only in this request and its response (``Cache-Control: no-store`` like
every API response). Logs name the template and the outcome only. Nothing
here reads an employer decision record or changes a Case.

Responses:

- 401 / 403 exactly as the Company routes (403 also for any member).
- 404 ``Not found``: a Case that isn't a workflow Case of the authorized
  Company (identical for another Company's Case), or a template that isn't
  installed.
- 409 ``Conflict``: the template can't be previewed in this Case now (the list
  says why), or ``template_version`` isn't the installed version.
- 422: invalid input; field locations only, submitted values are never echoed.
"""

import logging
from collections.abc import Mapping
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, StringConstraints

from app.api.workflows import InstalledRules, ScreeningPolicy
from app.cases.mutation import evaluate_case
from app.documents.bundle import (
    MAX_LIST_ITEMS,
    MAX_TEMPLATE_FIELDS,
    FieldSpec,
    Template,
    TemplateBundle,
)
from app.documents.eligibility import Availability, Reason, availability
from app.documents.render import OutBlock, OutSegment, SegmentKind, render, render_instructions
from app.documents.values import line_error, validate_values
from app.repositories import workflows
from app.repositories.case_subjects import get_case_subject
from app.repositories.companies import get_company
from app.tenancy.dependencies import CompanyAdminReadOnlyDb
from app.tenancy.scope import CompanyScope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies/{company_id}", tags=["documents"])

# --- fixed wording (public, generic; never template content) ---------------------------

NOT_INSTALLED: Final = "Document templates aren't available in this environment."
PREVIEW_NOTICE: Final = (
    "A preview is a draft for your own review. Nothing you type here is saved, sent or kept: "
    "it's gone when you close or reload the page. HeroOS doesn't issue, send or sign documents."
)
REMINDER: Final = (
    "Keep to the facts. Leave out health, family, religion or other personal details that "
    "aren't needed for this letter."
)
WATERMARK_TITLE: Final = "Preview — not issued"
WATERMARK_BODY: Final = (
    "Draft for the employer's review only. HeroOS doesn't give legal advice, and the employer "
    "decides whether and how to use this letter."
)
APPROVAL_TEXT: Final[Mapping[str, str]] = {
    "provisional": "Template wording: provisional, not approved for use.",
    "approved": "Template wording: approved for use in HeroOS.",
}
REASON_TEXT: Final[Mapping[str, str]] = {
    "rules_not_installed": (
        "Templates follow the workflow's stages, and no approved stages are available in this "
        "environment."
    ),
    "case_held": "Not available while this case is on hold for specialist review.",
    "case_not_ready": "Not available until the case can move on (see “Next steps”).",
    "not_for_jurisdiction": "Not offered for this case's jurisdiction.",
    "specialist_review_required": (
        "Needs a specialist's review before it can be offered, and that review isn't available "
        "in HeroOS yet."
    ),
    "not_at_this_stage": "Offered at another stage of this case.",
    "requirement_not_met": "Not available: something it requires isn't in place for this case.",
    "requirement_unknown": (
        "Not available until the information it depends on is answered (an unanswered or "
        "“Not sure” answer doesn't count)."
    ),
}


def installed_templates(request: Request) -> TemplateBundle | None:
    """The template bundle loaded and verified at startup; None if none is installed."""
    bundle: TemplateBundle | None = request.app.state.template_bundle
    return bundle


InstalledTemplates = Annotated[TemplateBundle | None, Depends(installed_templates)]
TemplateKeyParam = Annotated[str, PathParam(max_length=100)]

# --- request and response models ------------------------------------------------------

FieldValue = Annotated[StrictStr, StringConstraints(max_length=4000)]
OptionValue = Annotated[StrictStr, StringConstraints(max_length=30)]


class PreviewIn(BaseModel):
    """What the employer typed: field values and choices (nothing else, nothing kept)."""

    model_config = ConfigDict(extra="forbid")

    # The template version the form was built from: a changed bundle is a conflict.
    template_version: Annotated[StrictInt, Field(ge=1)]
    values: Annotated[
        dict[StrictStr, FieldValue | Annotated[list[FieldValue], Field(max_length=MAX_LIST_ITEMS)]],
        Field(max_length=MAX_TEMPLATE_FIELDS),
    ] = {}
    choices: Annotated[
        dict[StrictStr, Annotated[list[OptionValue], Field(max_length=8)]],
        Field(max_length=8),
    ] = {}


class NoticeOut(BaseModel):
    title: str
    body: str


class BundleOut(BaseModel):
    bundle: str
    version: str
    provenance: Literal["synthetic", "private"]
    approval: Literal["provisional", "approved"]
    # Synthetic templates are always announced as such.
    notice: NoticeOut | None


class TemplateRefOut(BaseModel):
    key: str
    code: str
    title: str
    kind: str
    version: int


class TemplateSummaryOut(TemplateRefOut):
    available: bool
    reason: Reason | None
    reason_text: str | None


class DocumentsOut(BaseModel):
    installed: bool
    # Why there's nothing to show (no bundle installed), else None.
    unavailable: str | None
    notice: str
    bundle: BundleOut | None
    templates: list[TemplateSummaryOut]


class SegmentOut(BaseModel):
    kind: SegmentKind
    text: str | None = None
    field: str | None = None
    label: str | None = None


class BlockOut(BaseModel):
    type: Literal["heading", "paragraph", "item", "table"]
    segments: list[SegmentOut] = []
    rows: list[list[list[SegmentOut]]] = []


class FieldOut(BaseModel):
    key: str
    label: str
    kind: Literal["text", "long_text", "date", "list"]
    help: str | None
    max_length: int | None
    max_items: int | None
    # From this Case's own Company or subject; the employer can change or clear it.
    suggested: str | None
    reminder: bool


class OptionOut(BaseModel):
    value: str
    label: str


class ChoiceOut(BaseModel):
    key: str
    label: str
    help: str | None
    multiple: bool
    options: list[OptionOut]


class TemplateFormOut(BaseModel):
    template: TemplateRefOut
    bundle: BundleOut
    instructions: list[BlockOut]
    fields: list[FieldOut]
    choices: list[ChoiceOut]
    notice: str
    reminder: str


class WatermarkOut(BaseModel):
    title: str
    body: str
    approval: str
    notice: NoticeOut | None


class PreviewOut(BaseModel):
    template: TemplateRefOut
    watermark: WatermarkOut
    blocks: list[BlockOut]
    # Fields and choices not filled in yet, in order of appearance.
    missing: list[str]


# --- helpers --------------------------------------------------------------------------


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _conflict() -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflict")


def _notice_out(bundle: TemplateBundle) -> NoticeOut | None:
    notice = bundle.notice
    return None if notice is None else NoticeOut(title=notice.title, body=notice.body)


def _bundle_out(bundle: TemplateBundle) -> BundleOut:
    return BundleOut(
        bundle=bundle.bundle_id,
        version=bundle.version,
        provenance=bundle.provenance,
        approval=bundle.approval,
        notice=_notice_out(bundle),
    )


def _ref(template: Template) -> TemplateRefOut:
    return TemplateRefOut(
        key=template.key,
        code=template.code,
        title=template.title,
        kind=template.kind,
        version=template.version,
    )


def _segment_out(segment: OutSegment) -> SegmentOut:
    return SegmentOut(
        kind=segment.kind, text=segment.text, field=segment.field, label=segment.label
    )


def _block_out(block: OutBlock) -> BlockOut:
    return BlockOut(
        type=block.type,
        segments=[_segment_out(s) for s in block.segments],
        rows=[[[_segment_out(s) for s in cell] for cell in row] for row in block.rows],
    )


def _availabilities(
    scope: CompanyScope,
    case_id: UUID,
    policy: ScreeningPolicy,
    rules: InstalledRules,
    bundle: TemplateBundle,
) -> list[Availability]:
    """Every template's availability in this Case now (404 for a Case that isn't one)."""
    item = workflows.get_workflow_case(scope, case_id)
    if item is None:
        raise _not_found()
    state = evaluate_case(scope, item, policy, rules)
    if state.definition.key != bundle.workflow_key:
        return []
    return [
        availability(
            template,
            jurisdiction=state.intake.jurisdiction.jurisdiction,
            progression=state.progression,
            answers=state.answers,
        )
        for template in bundle.templates
    ]


def _available(
    scope: CompanyScope,
    case_id: UUID,
    template_key: str,
    policy: ScreeningPolicy,
    rules: InstalledRules,
    bundle: TemplateBundle | None,
) -> tuple[TemplateBundle, Template]:
    """The template, if this Case may preview it now: 404 unknown, 409 unavailable."""
    if bundle is None:
        # No template exists here: indistinguishable from an unknown one.
        raise _not_found()
    found = next(
        (a for a in _availabilities(scope, case_id, policy, rules, bundle)
         if a.template.key == template_key),
        None,
    )  # fmt: skip
    if found is None:
        raise _not_found()
    if not found.available:
        raise _conflict()
    return bundle, found.template


def _suggestion(scope: CompanyScope, case_id: UUID, spec: FieldSpec) -> str | None:
    """A value from this Case's own Company or subject, if it fits the field as it is."""
    if spec.suggest is None or spec.max_length is None:
        return None
    value: str | None = None
    if spec.suggest == "company_name":
        company = get_company(scope)
        value = None if company is None else company.name
    else:
        item = workflows.get_workflow_case(scope, case_id)
        subject_id = None if item is None else item.case.subject_id
        subject = None if subject_id is None else get_case_subject(scope, subject_id)
        value = None if subject is None else subject.display_name
    if value is None or line_error(value, spec.max_length) is not None:
        return None
    return value


# --- routes ---------------------------------------------------------------------------


@router.get("/cases/{case_id}/documents", response_model=DocumentsOut)
def list_case_documents(
    case_id: UUID,
    scope: CompanyAdminReadOnlyDb,
    policy: ScreeningPolicy,
    rules: InstalledRules,
    templates: InstalledTemplates,
) -> DocumentsOut:
    """Each installed template and whether it can be previewed in this Case now."""
    if templates is None:
        if workflows.get_workflow_case(scope, case_id) is None:
            raise _not_found()
        return DocumentsOut(
            installed=False,
            unavailable=NOT_INSTALLED,
            notice=PREVIEW_NOTICE,
            bundle=None,
            templates=[],
        )
    found = _availabilities(scope, case_id, policy, rules, templates)
    return DocumentsOut(
        installed=True,
        unavailable=None,
        notice=PREVIEW_NOTICE,
        bundle=_bundle_out(templates),
        templates=[
            TemplateSummaryOut(
                **_ref(a.template).model_dump(),
                available=a.available,
                reason=a.reason,
                reason_text=None if a.reason is None else REASON_TEXT[a.reason],
            )
            for a in found
        ],
    )


@router.get("/cases/{case_id}/documents/{template_key}", response_model=TemplateFormOut)
def get_document_form(
    case_id: UUID,
    template_key: TemplateKeyParam,
    scope: CompanyAdminReadOnlyDb,
    policy: ScreeningPolicy,
    rules: InstalledRules,
    templates: InstalledTemplates,
) -> TemplateFormOut:
    """An available template's form (fields, choices, employer instructions)."""
    bundle, template = _available(scope, case_id, template_key, policy, rules, templates)
    fields = [bundle.fields[key] for key in template.fields]
    return TemplateFormOut(
        template=_ref(template),
        bundle=_bundle_out(bundle),
        instructions=[_block_out(b) for b in render_instructions(template)],
        fields=[
            FieldOut(
                key=spec.key,
                label=spec.label,
                kind=spec.kind,
                help=spec.help,
                max_length=spec.max_length,
                max_items=spec.max_items,
                suggested=_suggestion(scope, case_id, spec),
                reminder=spec.reminder,
            )
            for spec in fields
        ],
        choices=[
            ChoiceOut(
                key=choice.key,
                label=choice.label,
                help=choice.help,
                multiple=choice.multiple,
                options=[OptionOut(value=o.value, label=o.label) for o in choice.options],
            )
            for choice in template.choices
        ],
        notice=PREVIEW_NOTICE,
        reminder=REMINDER,
    )


@router.post("/cases/{case_id}/documents/{template_key}/preview", response_model=PreviewOut)
def preview_document(
    case_id: UUID,
    template_key: TemplateKeyParam,
    body: PreviewIn,
    scope: CompanyAdminReadOnlyDb,
    policy: ScreeningPolicy,
    rules: InstalledRules,
    templates: InstalledTemplates,
) -> PreviewOut:
    """The template filled with the request's values: shown once, never kept."""
    bundle, template = _available(scope, case_id, template_key, policy, rules, templates)
    if body.template_version != template.version:
        raise _conflict()
    values, choices, problems = validate_values(template, bundle.fields, body.values, body.choices)
    if problems:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("body", *p.loc), "msg": p.message} for p in problems]
        )
    rendered = render(template, bundle.fields, values, choices)
    # The template and outcome only: never a value, a choice or any wording.
    logger.info(
        "Document preview rendered (company_id=%s, template=%s, missing=%d)",
        scope.company_id,
        template.key,
        len(rendered.missing),
    )
    return PreviewOut(
        template=_ref(template),
        watermark=WatermarkOut(
            title=WATERMARK_TITLE,
            body=WATERMARK_BODY,
            approval=APPROVAL_TEXT[bundle.approval],
            notice=_notice_out(bundle),
        ),
        blocks=[_block_out(b) for b in rendered.blocks],
        missing=list(rendered.missing),
    )
