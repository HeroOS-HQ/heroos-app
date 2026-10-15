"use client";

import { useRef, useState } from "react";

import { Notice } from "@/components/ui/notice";
import { buttonPrimary, buttonQuiet, card } from "@/components/ui/styles";
import { TextField } from "@/components/ui/text-field";
import { type CaseSummary, TITLE_MAX, UUID, WORKFLOW_DISCIPLINARY } from "@/lib/workflows/model";

/**
 * New Disciplinary case. The server sets the case type; this form sends a
 * title and a request key. The key belongs to one title: retrying after a
 * timeout resends the same key (the API returns the same Case, never a second
 * one), and editing the title starts a new key. Only administrators succeed;
 * the API enforces it whatever this form shows.
 */

type Status =
  | { kind: "idle" }
  | { kind: "creating" }
  | { kind: "failed"; reason: "session_expired" | "forbidden" | "invalid" | "conflict" | "unavailable" };

const MESSAGES: Record<Exclude<Status, { kind: "idle" } | { kind: "creating" }>["reason"], string> = {
  session_expired: "Your session has ended. Sign in again, then create the case.",
  forbidden: "Only company administrators can create cases.",
  invalid: "HeroOS couldn't accept this title. Please check it and try again.",
  conflict: "Something changed while the case was being created. Please try again.",
  unavailable: "HeroOS couldn't be reached. Your case may not have been created yet; try again and it won't be created twice.",
};

function isCase(value: unknown): value is CaseSummary {
  return typeof value === "object" && value !== null && UUID.test(String((value as { id?: unknown }).id));
}

export function NewCaseForm({
  companyId,
  fetcher,
  navigate,
}: {
  companyId: string;
  fetcher?: typeof fetch;
  navigate?: (url: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const key = useRef<{ title: string; value: string } | null>(null);
  const inFlight = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const casesHref = `/workspaces/${encodeURIComponent(companyId)}/cases`;

  async function create() {
    if (inFlight.current) return;
    const value = title.trim();
    if (value === "") {
      setError("Please give the case a short title.");
      inputRef.current?.focus();
      return;
    }
    if (value.length > TITLE_MAX) {
      setError(`Please keep the title to ${TITLE_MAX} characters or fewer.`);
      inputRef.current?.focus();
      return;
    }
    if (key.current?.title !== value) key.current = { title: value, value: crypto.randomUUID() };
    inFlight.current = true;
    setStatus({ kind: "creating" });
    try {
      const response = await (fetcher ?? fetch)(
        `/bff/companies/${encodeURIComponent(companyId)}/workflows/${WORKFLOW_DISCIPLINARY}/cases`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ title: value, requestKey: key.current.value }),
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          signal: AbortSignal.timeout(30_000),
        },
      );
      const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
      if (response.status === 200 && body && isCase(body.case)) {
        (navigate ?? ((url: string) => window.location.assign(url)))(`${casesHref}/${encodeURIComponent(body.case.id)}`);
        return; // stays "creating" while the browser navigates
      }
      const reason =
        response.status === 401
          ? "session_expired"
          : response.status === 403
            ? "forbidden"
            : response.status === 422
              ? "invalid"
              : response.status === 409
                ? "conflict"
                : "unavailable";
      if (reason === "conflict") key.current = null;
      setStatus({ kind: "failed", reason });
    } catch {
      setStatus({ kind: "failed", reason: "unavailable" });
    } finally {
      inFlight.current = false;
    }
  }

  const creating = status.kind === "creating";
  return (
    <form
      className={`${card} flex flex-col gap-6 p-5 sm:p-8`}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void create();
      }}
    >
      <TextField
        error={error}
        hint="A short, neutral title, for example “Attendance concern – October”. Please don't include the employee's full name."
        id="case-title"
        inputRef={inputRef}
        label="Case title"
        maxLength={TITLE_MAX}
        onChange={(value) => {
          setTitle(value);
          setError(undefined);
          if (status.kind === "failed") setStatus({ kind: "idle" });
        }}
        required
        value={title}
      />

      <div className="rounded-2xl border border-hero-border bg-hero-bg/60 px-4 py-3.5 sm:px-5">
        <p className="text-[0.9375rem] font-bold text-hero-navy">Employee</p>
        <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-muted">
          Linking the case to an employee record comes later. For now, the case is created without one.
        </p>
      </div>

      {status.kind === "failed" ? (
        <Notice role="alert" title="The case wasn't created" tone="danger">
          {MESSAGES[status.reason]}
          {status.reason === "session_expired" ? (
            <>
              {" "}
              <a className="font-bold underline" href="/auth/login">
                Sign in
              </a>
            </>
          ) : null}
        </Notice>
      ) : null}

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
        <a className={buttonQuiet} href={casesHref}>
          Cancel
        </a>
        <button aria-disabled={creating} className={buttonPrimary} disabled={creating} type="submit">
          {creating ? "Creating case…" : "Create case"}
        </button>
      </div>
      <p aria-live="polite" className="sr-only" role="status">
        {creating ? "Creating the case" : ""}
      </p>
    </form>
  );
}
