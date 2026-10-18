"use client";

import { useEffect, useRef, useState } from "react";

import { ShieldIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { StatusBadge } from "@/components/ui/status-badge";
import { buttonPrimary, buttonSecondary } from "@/components/ui/styles";
import { formatDay, formatDayTime } from "@/lib/workflows/copy";
import { draftFromRecord, emptyDraft } from "@/lib/workflows/decision-draft";
import { chains, type DecisionRecord, RELATION_COPY, responsibleText } from "@/lib/workflows/decisions";
import type { WorkflowView } from "@/lib/workflows/model";

import { CaseTimeline } from "./case-timeline";
import { DecisionForm, type FormMode } from "./decision-form";

/**
 * "Decisions & history" (M2-04): the employer's own records of what it did or
 * decided, their corrections, the holds and limits that still apply, and the
 * unified case history. Records are the employer's account, never a workflow
 * authorization: saving one changes no stage, hold or outcome, and the
 * screen says so. Everything shown comes from the API's view.
 */

const EVIDENCE_STATUS: Record<DecisionRecord["evidenceStatus"], string> = {
  held: "Held by your company",
  none: "None available",
  not_sure: "Not sure yet",
};
const subheading = "text-base font-extrabold tracking-[-0.01em] text-hero-navy";

type Hold = { key: string; title: string; body: string; specialist: boolean };

/** What still holds the case back: the API's own hold, escalations and gate. */
function holdsAndLimits(view: WorkflowView): Hold[] {
  const holds: Hold[] = [];
  const hold = view.intake.hold;
  if (hold) {
    holds.push({
      key: `hold-${hold.reason}`,
      title: hold.title,
      body:
        hold.action === "escalate"
          ? "Held for specialist review. A record doesn't release it: no release exists in HeroOS yet."
          : "Paused until the jurisdiction is confirmed. A record doesn't change that.",
      specialist: hold.action === "escalate",
    });
  }
  for (const escalation of view.progression?.escalations ?? []) {
    holds.push({
      key: `escalation-${escalation.transition}`,
      title: `Specialist review needed: ${escalation.label}`,
      body: `Recorded ${formatDayTime(escalation.since)}. Not resolved, and a record doesn't resolve it.`,
      specialist: true,
    });
  }
  const gate = view.progression?.gate;
  if (gate && gate.code !== "case_held") {
    holds.push({
      key: `gate-${gate.code}`,
      title: gate.title,
      body: "Next steps can't move on until this changes. A record doesn't change it.",
      specialist: false,
    });
  }
  return holds;
}

function RecordDetails({ record }: { record: DecisionRecord }) {
  return (
    <>
      <p className="mt-2 break-words text-[0.9375rem] font-bold leading-snug text-hero-navy">{record.summary}</p>
      <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1.5 text-sm text-hero-navy sm:grid-cols-[9rem_minmax(0,1fr)]">
        <dt className="font-bold">Date</dt>
        <dd>
          <time dateTime={record.occurredOn}>{formatDay(`${record.occurredOn}T00:00:00Z`)}</time>
        </dd>
        <dt className="font-bold">Responsible</dt>
        <dd className="break-words">{responsibleText(record)}</dd>
        <dt className="font-bold">Evidence</dt>
        <dd>
          {EVIDENCE_STATUS[record.evidenceStatus]}
          {record.evidence.length > 0 ? (
            <ul className="mt-1 list-disc pl-5">
              {record.evidence.map((item, index) => (
                <li className="break-words" key={index}>
                  {item.kindLabel}: {item.description}
                  {item.reference ? ` (kept at: ${item.reference})` : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </dd>
        {record.changeReason ? (
          <>
            <dt className="font-bold">{record.relation === "clarification" ? "Clarification" : "Why it changed"}</dt>
            <dd className="whitespace-pre-wrap break-words">{record.changeReason}</dd>
          </>
        ) : null}
        <dt className="font-bold">Recorded</dt>
        <dd>
          <time dateTime={record.recordedAt}>{formatDayTime(record.recordedAt)}</time>
          {record.recordedByViewer ? " by you" : " by another administrator"}
        </dd>
      </dl>
      <p className="mt-2 whitespace-pre-wrap break-words text-[0.9375rem] leading-relaxed text-hero-navy/85">{record.explanation}</p>
    </>
  );
}

export function DecisionsPanel({
  companyId,
  caseId,
  view,
  onUpdated,
  fetcher,
}: {
  companyId: string;
  caseId: string;
  view: WorkflowView;
  onUpdated: (view: WorkflowView) => void;
  fetcher?: typeof fetch;
}) {
  const [mode, setMode] = useState<FormMode | null>(null);
  const [saved, setSaved] = useState<"new" | "correction" | "clarification" | null>(null);
  const outcomeRef = useRef<HTMLDivElement>(null);
  const decisions = view.decisions;

  useEffect(() => {
    if (saved !== null) outcomeRef.current?.focus();
  }, [saved]);

  if (decisions === null) {
    return (
      <div className="flex flex-col gap-4">
        <h2 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy" id="decisions-heading">
          Decisions &amp; history
        </h2>
        <Notice title="Decision records aren't available yet" tone="caution">
          This version of HeroOS can&apos;t record employer decisions yet. The case history is under “Case details”.
        </Notice>
      </div>
    );
  }

  const holds = holdsAndLimits(view);
  const grouped = chains(decisions.records);
  const canRecord = view.canEdit && decisions.canRecord;
  const formFor = (record: DecisionRecord) =>
    mode !== null && mode.kind !== "new" && mode.record.id === record.id ? mode : null;
  const form = (current: FormMode) => (
    <DecisionForm
      caseId={caseId}
      companyId={companyId}
      fetcher={fetcher}
      initial={current.kind === "new" ? emptyDraft() : draftFromRecord(current.record)}
      key={current.kind === "new" ? "new" : `${current.kind}-${current.record.id}`}
      mode={current}
      onCancel={() => setMode(null)}
      onSaved={(next) => {
        setSaved(current.kind === "new" ? "new" : current.kind);
        setMode(null);
        onUpdated(next);
      }}
      options={decisions.options}
      revision={view.workflow.revision}
    />
  );

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy" id="decisions-heading">
          Decisions &amp; history
        </h2>
        <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-navy/85">
          Keep a factual record of what your company did or decided about this case, and see everything that has happened to
          it in one place.
        </p>
      </div>

      <Notice title="What a record is, and isn't">
        <p>{decisions.options.notice}</p>
        <p className="mt-2">{decisions.options.notRecordable}</p>
      </Notice>

      <section aria-labelledby="holds-heading" className="rounded-2xl border border-hero-border bg-white p-4 sm:p-5">
        <h3 className={subheading} id="holds-heading">
          Holds and limits on this case
        </h3>
        {holds.length === 0 ? (
          <p className="mt-2 text-[0.9375rem] text-hero-navy/85">No hold applies to this case right now.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {holds.map((hold) => (
              <li
                className={`rounded-xl border px-3.5 py-3 text-hero-navy ${
                  hold.specialist ? "border-[#e9b4c0] bg-hero-danger-tint" : "border-[#f1df8d] bg-hero-yellow-tint"
                }`}
                key={hold.key}
              >
                <p className="flex items-start gap-2 font-bold">
                  {hold.specialist ? <ShieldIcon className="mt-0.5 size-4 shrink-0 text-hero-danger" /> : null}
                  <span>{hold.title}</span>
                </p>
                <p className="mt-0.5 text-sm leading-relaxed">{hold.body}</p>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-sm leading-relaxed text-hero-muted">
          Records don&apos;t start or complete stages, release holds, or count as a warning or any other outcome. Stages move
          on only under “Next steps”, when the rules allow it.
        </p>
      </section>

      <div aria-live="polite" className="outline-none" ref={outcomeRef} role="status" tabIndex={-1}>
        {saved !== null ? (
          <Notice
            title={saved === "new" ? "Record saved" : saved === "correction" ? "Correction saved" : "Clarification saved"}
            tone="success"
          >
            {saved === "new"
              ? "It's in the case history below as your company's record."
              : "It's now the current version. The earlier version stays in the case history, marked as replaced."}{" "}
            The workflow hasn&apos;t changed: holds, stages and next steps are as they were.
          </Notice>
        ) : null}
      </div>

      <section aria-labelledby="records-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className={subheading} id="records-heading">
            Employer records
          </h3>
          {canRecord && mode === null ? (
            <button
              className={buttonPrimary}
              onClick={() => {
                setSaved(null);
                setMode({ kind: "new" });
              }}
              type="button"
            >
              Add a record
            </button>
          ) : null}
        </div>
        {!canRecord ? (
          <p className="mt-2 text-sm text-hero-muted">Only company administrators can add or correct records.</p>
        ) : null}
        {mode?.kind === "new" ? <div className="mt-4">{form(mode)}</div> : null}
        {grouped.length === 0 ? (
          <p className="mt-3 text-[0.9375rem] text-hero-muted">No records yet.</p>
        ) : (
          <ul className="mt-4 flex flex-col gap-4">
            {grouped.map(({ current, earlier }) => {
              const editing = formFor(current);
              return (
                <li className="rounded-2xl border border-hero-border bg-white p-4 sm:p-5" key={current.chainId}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-bold uppercase tracking-[0.08em] text-hero-blue-ink">{current.categoryLabel}</span>
                    <StatusBadge tone="positive">Current</StatusBadge>
                    {current.relation !== "original" ? (
                      <StatusBadge tone="neutral">{`${RELATION_COPY[current.relation]} · version ${current.version}`}</StatusBadge>
                    ) : null}
                    <StatusBadge tone="muted">Employer record</StatusBadge>
                  </div>
                  <RecordDetails record={current} />
                  <p className="mt-2 text-xs text-hero-muted">Your company&apos;s account. HeroOS hasn&apos;t verified it.</p>
                  {canRecord && mode === null ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        className={buttonSecondary}
                        onClick={() => {
                          setSaved(null);
                          setMode({ kind: "correction", record: current });
                        }}
                        type="button"
                      >
                        Correct
                      </button>
                      <button
                        className={buttonSecondary}
                        onClick={() => {
                          setSaved(null);
                          setMode({ kind: "clarification", record: current });
                        }}
                        type="button"
                      >
                        Add clarification
                      </button>
                    </div>
                  ) : null}
                  {editing ? <div className="mt-4">{form(editing)}</div> : null}
                  {earlier.length > 0 ? (
                    <details className="mt-4 rounded-xl border border-hero-border bg-hero-bg px-3.5 py-2.5">
                      <summary className="cursor-pointer text-sm font-bold text-hero-navy">
                        Earlier versions ({earlier.length}), kept in the history
                      </summary>
                      <ol className="mt-2 flex flex-col gap-3">
                        {earlier.map((record) => (
                          <li className="border-t border-hero-border pt-3 first:border-t-0 first:pt-0" key={record.id}>
                            <div className="flex flex-wrap items-center gap-2">
                              <StatusBadge tone="muted">Replaced</StatusBadge>
                              <span className="text-sm text-hero-muted">
                                {RELATION_COPY[record.relation]} · version {record.version} · {record.categoryLabel}
                              </span>
                            </div>
                            <RecordDetails record={record} />
                          </li>
                        ))}
                      </ol>
                    </details>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {view.timeline ? (
        <section aria-labelledby="history-heading" className="scroll-mt-24" id="case-history">
          <h3 className={subheading} id="history-heading">
            Case history
          </h3>
          <CaseTimeline caseId={caseId} companyId={companyId} fetcher={fetcher} page={view.timeline} />
        </section>
      ) : null}
    </div>
  );
}
