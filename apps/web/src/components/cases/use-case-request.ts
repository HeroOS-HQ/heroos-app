"use client";

import { useCallback, useRef, useState } from "react";

import { isWorkflowView, type WorkflowView } from "@/lib/workflows/model";

/**
 * One employer request to a Case's own controls (M2-03 progression, M2-01
 * answers), shared by the Case page and Ask HeroOS's inline Case steps
 * (M2-NEW-08): the same BFF routes, the same request keys and the same
 * answers. Every request carries the revision it was based on; a retry after
 * a lost response reuses its key, so the API applies it once. The API decides
 * everything and answers with the Case's new view.
 */

export type CaseRequestFailure = "session_expired" | "forbidden" | "invalid" | "conflict" | "unavailable" | "not_found";

export type CaseRequest =
  | { route: "pathway"; pathway: string; acknowledgedWarnings: string[] }
  | { route: "transitions"; transition: string; acknowledgedWarnings: string[] }
  | { route: "answers"; stepKey: string; answers: Record<string, string> };

export const CASE_REQUEST_FAILURES: Record<CaseRequestFailure, { title: string; body: string }> = {
  session_expired: { title: "Your session has ended", body: "Nothing was recorded. Sign in again to continue." },
  forbidden: {
    title: "Only company administrators can do this",
    body: "Your access may have changed. Reload the page to see the case as it is now.",
  },
  invalid: { title: "HeroOS couldn't accept this request", body: "Reload the case and try again." },
  conflict: {
    title: "This case has changed since you opened it",
    body: "Something was saved or recorded first, or the cautions shown no longer apply. Nothing was recorded. Reload the case to see its current state.",
  },
  not_found: { title: "This case can't be found", body: "It may not be available to you any more. Reload the page." },
  unavailable: {
    title: "Nothing was recorded",
    body: "HeroOS couldn't be reached. Try again: if your request did go through, it won't be applied twice.",
  },
};

function failureOf(status: number): CaseRequestFailure {
  switch (status) {
    case 401:
      return "session_expired";
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 409:
      return "conflict";
    case 422:
      return "invalid";
    default:
      return "unavailable";
  }
}

export function useCaseRequest({
  companyId,
  caseId,
  fetcher,
}: {
  companyId: string;
  caseId: string;
  fetcher?: typeof fetch;
}) {
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ signature: string; key: string } | null>(null);

  /** The Case's new view, or why the request failed (nothing was recorded then). */
  const send = useCallback(
    async (revision: number, request: CaseRequest): Promise<{ view: WorkflowView } | { failure: CaseRequestFailure }> => {
      const signature = JSON.stringify([revision, request]);
      if (pending.current?.signature !== signature) pending.current = { signature, key: crypto.randomUUID() };
      const key = pending.current.key;
      const [path, method, body] =
        request.route === "answers"
          ? [
              `steps/${encodeURIComponent(request.stepKey)}/answers`,
              "PUT",
              { expectedRevision: revision, submissionKey: key, answers: request.answers },
            ]
          : request.route === "pathway"
            ? [
                "progression/pathway",
                "POST",
                { expectedRevision: revision, pathway: request.pathway, acknowledgedWarnings: request.acknowledgedWarnings, requestKey: key },
              ]
            : [
                "progression/transitions",
                "POST",
                {
                  expectedRevision: revision,
                  transition: request.transition,
                  acknowledgedWarnings: request.acknowledgedWarnings,
                  requestKey: key,
                },
              ];
      setBusy(true);
      try {
        const response = await (fetcher ?? fetch)(`/bff/companies/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}/${path}`, {
          method,
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(body),
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          signal: AbortSignal.timeout(30_000),
        });
        const answer = (await response.json().catch(() => null)) as Record<string, unknown> | null;
        if (response.status === 200 && answer && isWorkflowView(answer.view, caseId)) {
          pending.current = null;
          return { view: answer.view };
        }
        const failure = failureOf(response.status);
        if (failure !== "unavailable") pending.current = null;
        return { failure };
      } catch {
        return { failure: "unavailable" };
      } finally {
        setBusy(false);
      }
    },
    [caseId, companyId, fetcher],
  );

  return { busy, send };
}
