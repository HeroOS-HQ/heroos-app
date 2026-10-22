import "server-only";

import { ASK_QUESTION, ASK_STEP, ASK_WORKFLOW, isGreeting } from "@/lib/ask/model";
import { CONVERSATION_CURSOR, parseGatewayRequest, parseNotedRequest, parseSequence } from "@/lib/ask/conversation";
import { parseAssistantRequest } from "@/lib/assistant/model";
import { TEMPLATE_KEY } from "@/lib/documents/model";
import { parsePreviewRequest } from "@/lib/documents/requests";
import { type FieldName, parseBlueprintPatch, parseRegistrationRequest } from "@/lib/onboarding/model";
import { ENTRY_ID } from "@/lib/workflows/decisions";
import { KEY } from "@/lib/workflows/model";
import {
  parseAnswersSave,
  parseAskStart,
  parseCaseCreate,
  parseCorrectionRequest,
  parseDecisionRequest,
  parsePathwayRequest,
  parseTransitionRequest,
} from "@/lib/workflows/requests";

import { isSameOriginRequest, sessionFromRequest } from "./auth-flow";
import type { AuthConfig } from "./config";
import {
  type ApiFailure,
  type AssistantFailure,
  correctDecision,
  createWorkflowCase,
  getAssistantStatus,
  getCaseDocuments,
  getCaseWorkflow,
  getCaseHistory,
  getConversation,
  getConversationMessages,
  saveNotedFacts,
  getDocumentForm,
  listConversations,
  previewDocument,
  recordDecision,
  registerCompany,
  requestTransition,
  saveStepAnswers,
  selectPathway,
  sendAskChat,
  sendAssistantMessage,
  sendGatewayMessage,
  updateBlueprint,
  UUID,
} from "./heroos-api";

/**
 * Backend-for-frontend mutations (M1-10D). The browser posts JSON to these
 * same-origin endpoints; the web server checks the request, attaches the
 * session's access token and calls the HeroOS API. The browser never holds a
 * token and never calls the API.
 *
 * Every request must:
 * 1. come from this web app's own pages (`Origin`, or `Sec-Fetch-Site` when the
 *    browser sends `Origin: null`): CSRF;
 * 2. be `application/json` (a cross-site HTML form cannot send it without a
 *    CORS preflight, which this app never grants), at most 16 KiB (32 KiB for
 *    a document preview, which carries a whole letter's details);
 * 3. carry a valid session.
 *
 * The body is re-validated and rebuilt field by field (unknown keys refused)
 * before it reaches the API. Responses carry fixed codes only: never an API
 * or provider error text.
 */

export type BffDeps = { fetch: typeof fetch; now: () => number };

/** Error codes the browser maps to fixed copy. */
export type BffError =
  | "forbidden_origin"
  | "unsupported_media_type"
  | "payload_too_large"
  | "invalid_request"
  | "session_expired"
  | "invalid"
  | "refused"
  | "registration_unavailable"
  | "not_found"
  | "conflict"
  | "unavailable"
  | "rate_limited"
  | "timeout"
  | "not_configured"
  | "knowledge_unavailable"
  | "greeting";

export const MAX_BODY_BYTES = 16 * 1024;
export const MAX_PREVIEW_BYTES = 32 * 1024;
// A Hannah message, or an Ask HeroOS message, with its bounded recent history
// (lib/assistant/model.ts, lib/ask/conversation.ts).
export const MAX_ASSISTANT_BYTES = 48 * 1024;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

const error = (status: number, code: BffError, fields?: readonly string[]) =>
  json(status, fields ? { error: code, fields } : { error: code });

type Guarded = { ok: true; accessToken: string; body: unknown } | { ok: false; response: Response };

async function guard(request: Request, config: AuthConfig, deps: BffDeps, maxBytes = MAX_BODY_BYTES): Promise<Guarded> {
  if (!isSameOriginRequest(request, config)) return { ok: false, response: error(403, "forbidden_origin") };
  const type = (request.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (type !== "application/json") return { ok: false, response: error(415, "unsupported_media_type") };
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > maxBytes) return { ok: false, response: error(413, "payload_too_large") };

  const session = sessionFromRequest(request, config, Math.floor(deps.now() / 1000));
  if (session === null) return { ok: false, response: error(401, "session_expired") };

  let text: string;
  try {
    text = await request.text();
  } catch {
    return { ok: false, response: error(400, "invalid_request") };
  }
  if (new TextEncoder().encode(text).length > maxBytes) {
    return { ok: false, response: error(413, "payload_too_large") };
  }
  try {
    return { ok: true, accessToken: session.accessToken, body: JSON.parse(text) as unknown };
  } catch {
    return { ok: false, response: error(400, "invalid_request") };
  }
}

function apiFailure(failure: ApiFailure, fields: FieldName[] | undefined, refusal: BffError): Response {
  switch (failure) {
    case "unauthenticated":
      return error(401, "session_expired");
    case "forbidden":
      return error(403, refusal);
    case "invalid":
      return error(422, "invalid", fields ?? []);
    case "not_found":
      return error(404, refusal === "refused" ? "registration_unavailable" : "not_found");
    default:
      return error(503, "unavailable");
  }
}

/**
 * POST /bff/registrations → `POST /company-registrations`.
 *
 * 201 `{outcome: "created", companyId}`; 200 `{outcome: "existing", companyId}`
 * (this person registered before: the submitted details were NOT applied).
 * The API decides eligibility; nothing here infers it.
 */
export async function handleRegistration(request: Request, config: AuthConfig, deps: BffDeps): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  const parsed = parseRegistrationRequest(guarded.body);
  if (!parsed.ok) return error(422, "invalid", parsed.fields);

  const result = await registerCompany(guarded.accessToken, config, parsed.value, deps.fetch);
  if (!result.ok) return apiFailure(result.failure, result.fields, "refused");
  const { outcome, companyId } = result.data;
  return json(outcome === "created" ? 201 : 200, { outcome, companyId });
}

/**
 * PATCH /bff/companies/{id}/blueprint → `PATCH /companies/{id}/blueprint`.
 * Only administrators succeed (the API enforces it in the write transaction).
 */
export async function handleBlueprintUpdate(
  request: Request,
  config: AuthConfig,
  companyId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  // Never sent to the API unless it is a well-formed id; any other value looks
  // like a Company the user cannot reach.
  if (!UUID.test(companyId)) return error(403, "refused");
  const parsed = parseBlueprintPatch(guarded.body);
  if (!parsed.ok) return error(422, "invalid", parsed.fields);

  const result = await updateBlueprint(guarded.accessToken, config, companyId, parsed.value, deps.fetch);
  if (!result.ok) return apiFailure(result.failure, result.fields, "refused");
  return json(200, { blueprint: result.data });
}

/** Failures of the workflow routes: fixed codes; a 422 names the questions only. */
function workflowFailure(failure: ApiFailure, answerKeys: string[] | undefined): Response {
  switch (failure) {
    case "unauthenticated":
      return error(401, "session_expired");
    case "forbidden":
      return error(403, "refused");
    case "not_found":
      return error(404, "not_found");
    case "conflict":
      return error(409, "conflict");
    case "invalid":
      return error(422, "invalid", answerKeys ?? []);
    default:
      return error(503, "unavailable");
  }
}

/**
 * POST /bff/companies/{id}/workflows/{key}/cases → `POST /companies/{id}/workflows/{key}/cases`.
 *
 * 200 `{case}` for a new Case and for a retry of the same request (`requestKey`);
 * 409 `conflict` if the key was used for different details. Only administrators
 * succeed (the API enforces it in the write transaction).
 */
export async function handleCaseCreate(
  request: Request,
  config: AuthConfig,
  companyId: string,
  workflowKey: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!KEY.test(workflowKey)) return error(404, "not_found");
  const parsed = parseCaseCreate(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);

  const result = await createWorkflowCase(guarded.accessToken, config, companyId, workflowKey, parsed.value, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, result.answerKeys);
  return json(200, { case: result.data });
}

/**
 * POST /bff/companies/{id}/ask: Ask HeroOS (lib/ask/model.ts). The one seam
 * between the Ask page and HeroOS; M2-NEW-05/06 repoint it at the AI gateway.
 * Today it opens a case of the reference workflow and saves the founder's
 * words as its first answer, through the existing workflow API:
 *
 * 1. `POST /companies/{id}/workflows/disciplinary/cases` (`requestKey`: a
 *    retry opens the same case once);
 * 2. `GET …/cases/{caseId}/workflow` for the revision to save against;
 * 3. `PUT …/workflow/steps/initial_facts/answers` with the words exactly as
 *    written (`submissionKey`: applied once).
 *
 * 200 `{caseId, narrativeSaved}`. A case that opened but couldn't take the
 * words (a changed definition, a lost save) is still a case: the page says so
 * and the founder adds them in the case. Failures to open one map like every
 * workflow write; the API enforces the administrator role.
 */
export async function handleAskStart(
  request: Request,
  config: AuthConfig,
  companyId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  const parsed = parseAskStart(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);
  const { text, title, requestKey, submissionKey } = parsed.value;
  // A greeting is no situation: never a case, and never "Hi" saved as what happened (M2-NEW-08).
  if (isGreeting(text)) return error(422, "greeting", []);
  const token = guarded.accessToken;

  const created = await createWorkflowCase(
    token,
    config,
    companyId,
    ASK_WORKFLOW,
    { title, request_key: requestKey },
    deps.fetch,
  );
  if (!created.ok) return workflowFailure(created.failure, created.answerKeys);
  const caseId = created.data.id;

  const view = await getCaseWorkflow(token, config, companyId, caseId, deps.fetch);
  const step = view.ok
    ? view.data.steps.find(
        (item) => item.key === ASK_STEP && item.available && item.questions.some((question) => question.key === ASK_QUESTION),
      )
    : undefined;
  if (!view.ok || step === undefined) return json(200, { caseId, narrativeSaved: false });

  const saved = await saveStepAnswers(
    token,
    config,
    companyId,
    caseId,
    ASK_STEP,
    { expected_revision: view.data.workflow.revision, submission_key: submissionKey, answers: { [ASK_QUESTION]: text } },
    deps.fetch,
  );
  return json(200, { caseId, narrativeSaved: saved.ok });
}

/**
 * PUT /bff/companies/{id}/cases/{caseId}/steps/{step}/answers →
 * `PUT /companies/{id}/cases/{caseId}/workflow/steps/{step}/answers`.
 *
 * 200 `{view}` (the Case after the save); 409 `conflict` when the answers
 * changed since they were read (`expectedRevision`); a retry with the same
 * `submissionKey` is applied once.
 */
export async function handleAnswersSave(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  stepKey: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId) || !KEY.test(stepKey)) return error(404, "not_found");
  const parsed = parseAnswersSave(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);

  const result = await saveStepAnswers(guarded.accessToken, config, companyId, caseId, stepKey, parsed.value, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, result.answerKeys);
  return json(200, { view: result.data });
}

/**
 * POST /bff/companies/{id}/cases/{caseId}/progression/pathway →
 * `POST /companies/{id}/cases/{caseId}/workflow/progression/pathway` (M2-03).
 *
 * 200 `{view}` whether the choice was recorded or refused (the view's
 * `progression.attempt` says which); 409 `conflict` when the case changed
 * since it was read, the acknowledgments don't match or no rules are installed.
 */
export async function handlePathwaySelect(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId)) return error(404, "not_found");
  const parsed = parsePathwayRequest(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);

  const result = await selectPathway(guarded.accessToken, config, companyId, caseId, parsed.value, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, []);
  return json(200, { view: result.data });
}

/**
 * POST /bff/companies/{id}/cases/{caseId}/progression/transitions →
 * `POST /companies/{id}/cases/{caseId}/workflow/progression/transitions` (M2-03).
 * Same answers as the pathway choice; only stage transitions are accepted.
 */
export async function handleTransitionRequest(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId)) return error(404, "not_found");
  const parsed = parseTransitionRequest(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);

  const result = await requestTransition(guarded.accessToken, config, companyId, caseId, parsed.value, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, []);
  return json(200, { view: result.data });
}

/**
 * POST /bff/companies/{id}/cases/{caseId}/decisions →
 * `POST /companies/{id}/cases/{caseId}/decisions` (M2-04).
 *
 * 200 `{view}` with the record saved (a retry with the same `requestKey` is
 * applied once); 409 `conflict` when the case changed since it was read; 422
 * names the fields only. A record never moves the case on.
 */
export async function handleDecisionRecord(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId)) return error(404, "not_found");
  const parsed = parseDecisionRequest(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);

  const result = await recordDecision(guarded.accessToken, config, companyId, caseId, parsed.value, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, result.decisionFields);
  return json(200, { view: result.data });
}

/**
 * POST /bff/companies/{id}/cases/{caseId}/decisions/{recordId}/corrections →
 * `POST /companies/{id}/cases/{caseId}/decisions/{recordId}/corrections` (M2-04).
 * Same answers as a new record; 409 also when that version was already replaced.
 */
export async function handleDecisionCorrection(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  recordId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId) || !UUID.test(recordId)) return error(404, "not_found");
  const parsed = parseCorrectionRequest(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);

  const result = await correctDecision(guarded.accessToken, config, companyId, caseId, recordId, parsed.value, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, result.decisionFields);
  return json(200, { view: result.data });
}

/**
 * GET /bff/companies/{id}/cases/{caseId}/history?before=… →
 * `GET /companies/{id}/cases/{caseId}/history` (M2-04): an older page of the
 * unified case history. A read: same-origin and a valid session, no body.
 */
export async function handleHistoryPage(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  deps: BffDeps,
): Promise<Response> {
  if (!isSameOriginRequest(request, config)) return error(403, "forbidden_origin");
  const session = sessionFromRequest(request, config, Math.floor(deps.now() / 1000));
  if (session === null) return error(401, "session_expired");
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId)) return error(404, "not_found");
  const params = new URL(request.url).searchParams;
  const before = params.get("before");
  if ([...params.keys()].some((key) => key !== "before") || (before !== null && (before.length > 200 || !ENTRY_ID.test(before)))) {
    return error(422, "invalid", []);
  }

  const result = await getCaseHistory(session.accessToken, config, companyId, caseId, before, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, []);
  return json(200, { page: result.data });
}

/**
 * GET /bff/companies/{id}/cases/{caseId}/workflow →
 * `GET /companies/{id}/cases/{caseId}/workflow` (M2-NEW-08): the Case's view as
 * the API has it now, so Ask HeroOS can offer the Case's own formal steps
 * inline (each one then goes through the existing pathway, transition and
 * answers routes). A read: no body, no query.
 */
export async function handleCaseWorkflow(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  deps: BffDeps,
): Promise<Response> {
  const read = guardRead(request, config, deps);
  if (!read.ok) return read.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId)) return error(404, "not_found");
  const result = await getCaseWorkflow(read.accessToken, config, companyId, caseId, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, []);
  return json(200, { view: result.data });
}

// --- document templates and previews (M2-04C) -----------------------------------------

type ReadGuard = { ok: true; accessToken: string; params: URLSearchParams } | { ok: false; response: Response };

/** A read: same-origin and a valid session, no body, and no query but the named parameters (once each). */
function guardRead(request: Request, config: AuthConfig, deps: BffDeps, allowed: readonly string[] = []): ReadGuard {
  if (!isSameOriginRequest(request, config)) return { ok: false, response: error(403, "forbidden_origin") };
  const session = sessionFromRequest(request, config, Math.floor(deps.now() / 1000));
  if (session === null) return { ok: false, response: error(401, "session_expired") };
  const params = new URL(request.url).searchParams;
  const keys = [...params.keys()];
  if (keys.some((key) => !allowed.includes(key)) || new Set(keys).size !== keys.length) {
    return { ok: false, response: error(422, "invalid", []) };
  }
  return { ok: true, accessToken: session.accessToken, params };
}

/**
 * GET /bff/companies/{id}/cases/{caseId}/documents →
 * `GET /companies/{id}/cases/{caseId}/documents` (M2-04C): every template and
 * whether this Case can preview it now (the API decides).
 */
export async function handleDocumentsList(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = guardRead(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId)) return error(404, "not_found");
  const result = await getCaseDocuments(guarded.accessToken, config, companyId, caseId, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, []);
  return json(200, { documents: result.data });
}

/**
 * GET /bff/companies/{id}/cases/{caseId}/documents/{template} →
 * `GET /companies/{id}/cases/{caseId}/documents/{template}` (M2-04C): an
 * available template's form; 409 `conflict` when it can't be previewed now.
 */
export async function handleDocumentForm(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  templateKey: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = guardRead(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId) || !TEMPLATE_KEY.test(templateKey)) return error(404, "not_found");
  const result = await getDocumentForm(guarded.accessToken, config, companyId, caseId, templateKey, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, []);
  return json(200, { form: result.data });
}

/**
 * POST /bff/companies/{id}/cases/{caseId}/documents/{template}/preview →
 * `POST /companies/{id}/cases/{caseId}/documents/{template}/preview` (M2-04C).
 *
 * 200 `{preview}`: structured text with a watermark, never stored anywhere
 * (the response is `no-store`, and nothing here logs the body). 409
 * `conflict` when the template can't be previewed now or changed; 422 names
 * the fields only.
 */
export async function handleDocumentPreview(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  templateKey: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps, MAX_PREVIEW_BYTES);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId) || !TEMPLATE_KEY.test(templateKey)) return error(404, "not_found");
  const parsed = parsePreviewRequest(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);

  const result = await previewDocument(guarded.accessToken, config, companyId, caseId, templateKey, parsed.value, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, result.documentFields);
  return json(200, { preview: result.data });
}

// --- the Hannah AI demo ---------------------------------------------------------------

/**
 * GET /bff/companies/{id}/cases/{caseId}/assistant →
 * `GET /companies/{id}/cases/{caseId}/assistant`: whether the signed-in
 * administrator can talk to Hannah in this Case (the API decides: the demo
 * switch, the administrator role and the Case's Company).
 */
export async function handleAssistantStatus(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = guardRead(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId)) return error(404, "not_found");
  const result = await getAssistantStatus(guarded.accessToken, config, companyId, caseId, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, []);
  return json(200, { status: result.data });
}

/**
 * POST /bff/companies/{id}/cases/{caseId}/assistant/messages →
 * `POST /companies/{id}/cases/{caseId}/assistant/messages`.
 *
 * 200 `{reply}`. Nothing is stored or logged here and the Case doesn't
 * change, so the browser may retry. 429 `rate_limited` (with `Retry-After`),
 * 504 `timeout`, 503 `not_configured` or `unavailable`; never the provider's
 * own error text.
 */
export async function handleAssistantMessage(
  request: Request,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps, MAX_ASSISTANT_BYTES);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(caseId)) return error(404, "not_found");
  const parsed = parseAssistantRequest(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);

  const result = await sendAssistantMessage(guarded.accessToken, config, companyId, caseId, parsed.value, deps.fetch);
  return result.ok ? json(200, { reply: result.data }) : chatFailure(result.failure, result.retryAfter);
}

function chatFailure(failure: AssistantFailure, retryAfter?: number): Response {
  switch (failure) {
    case "rate_limited": {
      const response = error(429, "rate_limited");
      response.headers.set("Retry-After", String(retryAfter ?? 60));
      return response;
    }
    case "timeout":
      return error(504, "timeout");
    case "not_configured":
      return error(503, "not_configured");
    default:
      return workflowFailure(failure, []);
  }
}

/**
 * POST /bff/companies/{id}/assistant/chat → `POST /companies/{id}/assistant/chat`:
 * Ask HeroOS's staging chat-only demo. The message and the recent turns
 * (browser memory only), rebuilt field by field as for Hannah; 200 `{reply}`,
 * the text alone. Nothing is stored or logged here, and nothing opens a Case.
 * Failures as Hannah's; 404 `not_found` when the demo is off.
 */
export async function handleAskChat(
  request: Request,
  config: AuthConfig,
  companyId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps, MAX_ASSISTANT_BYTES);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  const parsed = parseAssistantRequest(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);

  const result = await sendAskChat(guarded.accessToken, config, companyId, parsed.value, deps.fetch);
  return result.ok ? json(200, { reply: result.data.reply }) : chatFailure(result.failure, result.retryAfter);
}

// --- Ask HeroOS's AI gateway (M2-NEW-05) ------------------------------------------------

/**
 * POST /bff/companies/{id}/assistant/messages →
 * `POST /companies/{id}/assistant/messages` (M2-NEW-07): the founder's words,
 * a turn key, the conversation id (none for a new one) and the revision the
 * browser last saw, rebuilt field by field; nothing else is accepted (no
 * history, facts, Case, outcome or continuation: the API holds those).
 *
 * 200 `{conversation, messages, replayed}`, rebuilt field by field. A retry
 * with the same turn key replays the stored turn; 409 `conflict` when the
 * conversation moved on or the key was used for another message. 429
 * `rate_limited` (with `Retry-After`), 504 `timeout`, 503 `not_configured` /
 * `knowledge_unavailable` / `unavailable`; never the API's or the provider's
 * own text. Nothing is logged here. The API decides who may ask (Company
 * administrators) and what HeroOS knows; nothing here chooses either.
 */
export async function handleGatewayMessage(
  request: Request,
  config: AuthConfig,
  companyId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps, MAX_ASSISTANT_BYTES);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  const parsed = parseGatewayRequest(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);

  const result = await sendGatewayMessage(guarded.accessToken, config, companyId, parsed.value, deps.fetch);
  if (result.ok) return json(200, result.data);
  switch (result.failure) {
    case "rate_limited": {
      const response = error(429, "rate_limited");
      response.headers.set("Retry-After", String(result.retryAfter ?? 60));
      return response;
    }
    case "timeout":
      return error(504, "timeout");
    case "not_configured":
    case "knowledge_unavailable":
      return error(503, result.failure);
    default:
      return workflowFailure(result.failure, []);
  }
}

/**
 * GET /bff/companies/{id}/assistant/conversations?before=…|caseId=… →
 * `GET /companies/{id}/assistant/conversations` (M2-NEW-07): the Company's
 * conversations, most recently active first, or the one a Case is attached
 * to. A read: same-origin and a valid session; the only queries are the API's
 * own cursor and a Case id.
 */
export async function handleConversationList(
  request: Request,
  config: AuthConfig,
  companyId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = guardRead(request, config, deps, ["before", "caseId"]);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  const before = guarded.params.get("before");
  const caseId = guarded.params.get("caseId");
  if (before !== null && !CONVERSATION_CURSOR.test(before)) return error(422, "invalid", []);
  // One Case's conversation is a single page.
  if (caseId !== null && (!UUID.test(caseId) || before !== null)) return error(422, "invalid", []);
  const result = await listConversations(guarded.accessToken, config, companyId, { before, caseId }, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, []);
  return json(200, result.data);
}

/**
 * GET /bff/companies/{id}/assistant/conversations/{conversationId} →
 * `GET .../assistant/conversations/{conversationId}`: one conversation, its
 * current status and its latest messages (authors relative to the viewer).
 */
export async function handleConversationDetail(
  request: Request,
  config: AuthConfig,
  companyId: string,
  conversationId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = guardRead(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(conversationId)) return error(404, "not_found");
  const result = await getConversation(guarded.accessToken, config, companyId, conversationId, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, []);
  return json(200, result.data);
}

/**
 * GET /bff/companies/{id}/assistant/conversations/{conversationId}/messages?before=… →
 * `GET .../messages`: older messages (``before`` a message sequence).
 */
export async function handleConversationMessages(
  request: Request,
  config: AuthConfig,
  companyId: string,
  conversationId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = guardRead(request, config, deps, ["before"]);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(conversationId)) return error(404, "not_found");
  const before = parseSequence(guarded.params.get("before"));
  if (before === undefined) return error(422, "invalid", []);
  const result = await getConversationMessages(guarded.accessToken, config, companyId, conversationId, before, deps.fetch);
  if (!result.ok) return workflowFailure(result.failure, []);
  return json(200, result.data);
}

/**
 * POST /bff/companies/{id}/assistant/conversations/{conversationId}/noted →
 * `POST .../noted`: the employer saves what HeroOS noted from the conversation
 * to its Case (the chat-first Case). The browser sends only the revision it
 * saw and the labels of the items the employer ticked; the API holds the values. Answers the
 * conversation as it is now.
 */
export async function handleNotedSave(
  request: Request,
  config: AuthConfig,
  companyId: string,
  conversationId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  if (!UUID.test(companyId)) return error(403, "refused");
  if (!UUID.test(conversationId)) return error(404, "not_found");
  const parsed = parseNotedRequest(guarded.body);
  if (!parsed.ok) return error(422, "invalid", []);
  const result = await saveNotedFacts(
    guarded.accessToken,
    config,
    companyId,
    conversationId,
    parsed.expectedRevision,
    parsed.confirmed,
    deps.fetch,
  );
  if (!result.ok) return workflowFailure(result.failure, []);
  return json(200, { conversation: result.data });
}
