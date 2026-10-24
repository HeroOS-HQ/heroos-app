/**
 * When a case or conversation last changed, in the viewer's own words and time zone: "09:12" today,
 * "16 Oct" this year, "16 Oct 2025" before. Call it in the browser (its "today" is the viewer's).
 */

const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });
const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const DAY_YEAR = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

const sameDay = (a: Date, b: Date) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

export function caseWhen(iso: string, now: Date): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  if (sameDay(at, now)) return TIME.format(at);
  return at.getFullYear() === now.getFullYear() ? DAY.format(at) : DAY_YEAR.format(at);
}
