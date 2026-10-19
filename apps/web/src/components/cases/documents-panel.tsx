"use client";

import { useEffect, useState } from "react";

import { DocumentIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { StatusBadge } from "@/components/ui/status-badge";
import { buttonSecondary } from "@/components/ui/styles";
import { type DocumentsList, isDocumentsList, isTemplateForm, KIND_LABEL, type TemplateForm } from "@/lib/documents/model";

import { DocumentForm } from "./document-form";

/**
 * "Documents" (M2-04C): the letter and email templates for this Case, whether
 * each can be previewed now and, if not, why. The API decides availability
 * from the Case's stage, jurisdiction, holds and checklist answers on every
 * request; the list is read again whenever the Case changes (its revision).
 * Previews are drafts for the employer's own review: nothing is saved, sent,
 * downloaded or issued, and nothing here changes the Case.
 */

type Load =
  | { state: "loading" }
  | { state: "ready"; list: DocumentsList }
  | { state: "absent" }
  | { state: "forbidden" }
  | { state: "failed" };

type Open = { state: "loading"; key: string } | { state: "open"; form: TemplateForm } | { state: "failed"; key: string; status: number };

const request = (url: string, fetcher: typeof fetch) =>
  fetcher(url, { headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin", redirect: "error" });

export function DocumentsPanel({
  companyId,
  caseId,
  revision,
  fetcher,
}: {
  companyId: string;
  caseId: string;
  /** The Case's revision: availability is read again whenever it changes. */
  revision: number;
  fetcher?: typeof fetch;
}) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [open, setOpen] = useState<Open | null>(null);
  const base = `/bff/companies/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}/documents`;

  useEffect(() => {
    let current = true;
    void (async () => {
      try {
        const response = await request(base, fetcher ?? fetch);
        const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
        if (!current) return;
        if (response.status === 200 && body && isDocumentsList(body.documents)) setLoad({ state: "ready", list: body.documents });
        // An API without document routes (an older version) answers 404.
        else if (response.status === 404) setLoad({ state: "absent" });
        else if (response.status === 403) setLoad({ state: "forbidden" });
        else setLoad({ state: "failed" });
      } catch {
        if (current) setLoad({ state: "failed" });
      }
    })();
    return () => {
      current = false;
    };
  }, [base, revision, fetcher]);

  async function openTemplate(key: string) {
    setOpen({ state: "loading", key });
    try {
      const response = await request(`${base}/${encodeURIComponent(key)}`, fetcher ?? fetch);
      const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
      if (response.status === 200 && body && isTemplateForm(body.form)) setOpen({ state: "open", form: body.form });
      else setOpen({ state: "failed", key, status: response.status });
    } catch {
      setOpen({ state: "failed", key, status: 0 });
    }
  }

  const heading = (
    <div>
      <h2 className="flex items-center gap-2 text-lg font-extrabold tracking-[-0.01em] text-hero-navy" id="documents-heading">
        <DocumentIcon className="size-5" />
        Documents
      </h2>
      <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-navy/85">
        Preview a letter or email for this case, filled with the details you type. Previews are drafts for your own review:
        HeroOS doesn&apos;t save, send or issue them.
      </p>
    </div>
  );

  if (load.state !== "ready") {
    const message =
      load.state === "loading"
        ? null
        : load.state === "absent"
          ? { title: "Documents aren't available yet", body: "This version of HeroOS can't show document previews yet.", tone: "caution" as const }
          : load.state === "forbidden"
            ? { title: "Only company administrators can preview documents", body: "Reload the page to see the case as it is now.", tone: "caution" as const }
            : { title: "Documents couldn't be loaded", body: "Reload the case to try again.", tone: "caution" as const };
    return (
      <div className="flex flex-col gap-4">
        {heading}
        {message === null ? (
          <p className="text-sm text-hero-muted" role="status">
            Loading documents…
          </p>
        ) : (
          <Notice title={message.title} tone={message.tone}>
            {message.body}
          </Notice>
        )}
      </div>
    );
  }

  const list = load.list;
  if (!list.installed) {
    return (
      <div className="flex flex-col gap-4">
        {heading}
        <Notice title="Not available here">{list.unavailable ?? "Document templates aren't available in this environment."}</Notice>
      </div>
    );
  }

  const available = list.templates.filter((template) => template.available);
  const unavailable = list.templates.filter((template) => !template.available);
  const openKey = open === null ? null : open.state === "open" ? open.form.template.key : open.key;

  return (
    <div className="flex flex-col gap-5">
      {heading}
      {list.bundle?.notice ? (
        <Notice title={list.bundle.notice.title} tone="caution">
          {list.bundle.notice.body}
        </Notice>
      ) : null}
      {list.bundle?.approval === "provisional" ? (
        <p className="text-sm font-semibold text-hero-navy">Template wording here is provisional: not approved for use.</p>
      ) : null}

      <section aria-labelledby="documents-available-heading">
        <h3 className="text-base font-extrabold tracking-[-0.01em] text-hero-navy" id="documents-available-heading">
          Available at this stage
        </h3>
        {available.length === 0 ? (
          <p className="mt-2 text-[0.9375rem] text-hero-muted">No template can be previewed at this point of the case.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-3">
            {available.map((template) => (
              <li className="rounded-2xl border border-hero-border bg-white p-4" key={template.key}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-bold uppercase tracking-[0.08em] text-hero-blue-ink">{template.code}</span>
                      <StatusBadge tone="muted">{KIND_LABEL[template.kind] ?? "Document"}</StatusBadge>
                    </p>
                    <p className="mt-1 break-words font-bold text-hero-navy">{template.title}</p>
                  </div>
                  {openKey !== template.key ? (
                    <button className={buttonSecondary} onClick={() => void openTemplate(template.key)} type="button">
                      Open<span className="sr-only"> {template.title}</span>
                    </button>
                  ) : null}
                </div>
                {openKey === template.key && open?.state === "loading" ? (
                  <p className="mt-3 text-sm text-hero-muted" role="status">
                    Opening…
                  </p>
                ) : null}
                {openKey === template.key && open?.state === "failed" ? (
                  <Notice className="mt-3" title="This template can't be opened now" tone="caution">
                    {open.status === 409
                      ? "The case changed since the list was loaded. Reload the case to see what's available."
                      : "Reload the case and try again."}
                  </Notice>
                ) : null}
                {openKey === template.key && open?.state === "open" ? (
                  <div className="mt-4">
                    <DocumentForm caseId={caseId} companyId={companyId} fetcher={fetcher} form={open.form} key={open.form.template.key} onClose={() => setOpen(null)} />
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      {unavailable.length > 0 ? (
        <details className="rounded-2xl border border-hero-border bg-white px-4 py-3">
          <summary className="cursor-pointer text-sm font-bold text-hero-navy">Not available now ({unavailable.length})</summary>
          <ul className="mt-2 flex flex-col">
            {unavailable.map((template) => (
              <li className="border-t border-hero-border py-2.5 first:border-t-0" data-template={template.key} key={template.key}>
                <p className="text-sm font-semibold text-hero-navy">
                  {template.code} · {template.title}
                </p>
                <p className="mt-0.5 text-sm leading-relaxed text-hero-muted">{template.reasonText}</p>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
