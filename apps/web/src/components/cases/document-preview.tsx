import type { ReactNode } from "react";

import { DocumentIcon } from "@/components/site/icons";
import type { Block, Preview, Segment } from "@/lib/documents/model";

/**
 * A document preview (M2-04C): the API's structured text blocks, rendered as
 * text nodes only. There is no HTML string anywhere: a value that looks like
 * markup, a script or a link is shown as the characters typed, never parsed or
 * linked. Values the employer typed are highlighted; anything not given is a
 * visible gap. The watermark is at the top and bottom of the preview and on
 * every printed page: a preview is a draft for review, never an issued letter.
 */

function SegmentView({ segment }: { segment: Segment }): ReactNode {
  switch (segment.kind) {
    case "text":
      return segment.text;
    case "value":
      return (
        <mark className="rounded-sm bg-hero-blue-tint px-0.5 text-hero-navy" data-field={segment.field ?? undefined}>
          {segment.text}
        </mark>
      );
    case "missing":
      return (
        <span
          className="rounded-sm border border-dashed border-hero-danger px-1 font-semibold text-hero-danger"
          data-missing={segment.field ?? undefined}
        >
          [{segment.label}: not provided]
        </span>
      );
    case "blank":
      return (
        <span className="inline-flex items-end gap-1.5">
          <span className="text-hero-muted">{segment.label}:</span>
          <span aria-hidden="true" className="inline-block w-40 border-b border-hero-navy" />
          <span className="sr-only">(left blank)</span>
        </span>
      );
    default:
      return <br />;
  }
}

function Segments({ segments }: { segments: Segment[] }) {
  return (
    <>
      {segments.map((segment, index) => (
        <SegmentView key={index} segment={segment} />
      ))}
    </>
  );
}

function BlockView({ block }: { block: Block }) {
  if (block.type === "heading") {
    return (
      <p className="mt-4 text-base font-extrabold text-hero-navy first:mt-0">
        <Segments segments={block.segments} />
      </p>
    );
  }
  if (block.type === "table") {
    return (
      <div className="mt-3 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <tbody>
            {block.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td className="border border-hero-border px-2.5 py-1.5 align-top whitespace-pre-wrap break-words" key={c}>
                    <Segments segments={cell} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <p className="mt-3 whitespace-pre-wrap break-words first:mt-0">
      <Segments segments={block.segments} />
    </p>
  );
}

/** Consecutive list items become one list. */
function group(blocks: Block[]): (Block | Block[])[] {
  const out: (Block | Block[])[] = [];
  for (const block of blocks) {
    const last = out.at(-1);
    if (block.type === "item" && Array.isArray(last)) last.push(block);
    else out.push(block.type === "item" ? [block] : block);
  }
  return out;
}

export function DocumentBlocks({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {group(blocks).map((item, index) =>
        Array.isArray(item) ? (
          <ul className="mt-3 list-disc pl-6" key={index}>
            {item.map((block, i) => (
              <li className="mt-1 whitespace-pre-wrap break-words" key={i}>
                <Segments segments={block.segments} />
              </li>
            ))}
          </ul>
        ) : (
          <BlockView block={item} key={index} />
        ),
      )}
    </>
  );
}

function WatermarkBanner({ preview, position }: { preview: Preview; position: "top" | "bottom" }) {
  return (
    <div
      className="rounded-xl border-2 border-dashed border-hero-danger bg-hero-danger-tint px-3.5 py-2.5 text-sm text-hero-navy"
      data-watermark={position}
      role="note"
    >
      <p className="font-extrabold uppercase tracking-[0.08em] text-hero-danger">{preview.watermark.title}</p>
      {position === "top" ? (
        <>
          <p className="mt-1 leading-relaxed">{preview.watermark.body}</p>
          <p className="mt-1 font-semibold">{preview.watermark.approval}</p>
          {preview.watermark.notice ? (
            <p className="mt-1">
              <strong>{preview.watermark.notice.title}.</strong> {preview.watermark.notice.body}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

export function DocumentPreview({ preview, headingId }: { preview: Preview; headingId: string }) {
  return (
    <article aria-labelledby={headingId} className="flex flex-col gap-4 rounded-2xl border border-hero-border bg-white p-4 sm:p-6">
      {/* Printed: on every page (fixed elements repeat on each printed page). */}
      <p
        aria-hidden="true"
        className="hidden text-center text-xs font-extrabold uppercase tracking-[0.2em] text-hero-danger print:fixed print:inset-x-0 print:top-0 print:block"
        data-watermark="print"
      >
        {preview.watermark.title}
      </p>
      <h4 className="flex items-center gap-2 text-base font-extrabold text-hero-navy outline-none" id={headingId} tabIndex={-1}>
        <DocumentIcon className="size-5 shrink-0" />
        Preview: {preview.template.code} {preview.template.title}
      </h4>
      <WatermarkBanner position="top" preview={preview} />
      {preview.missing.length > 0 ? (
        <p className="text-sm font-semibold text-hero-danger">
          {preview.missing.length === 1
            ? "1 detail isn't provided yet: it shows as a gap below."
            : `${preview.missing.length} details aren't provided yet: they show as gaps below.`}
        </p>
      ) : null}
      <div className="rounded-xl border border-hero-border bg-hero-bg px-4 py-4 text-[0.9375rem] leading-relaxed text-hero-navy sm:px-6">
        <DocumentBlocks blocks={preview.blocks} />
      </div>
      <WatermarkBanner position="bottom" preview={preview} />
    </article>
  );
}
