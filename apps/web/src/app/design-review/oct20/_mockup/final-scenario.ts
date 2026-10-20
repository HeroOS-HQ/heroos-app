/**
 * Final Page 1 (Ask HeroOS), consolidated from Direction A. Content is
 * illustrative and comes from the 20 Oct Aries/JJ catch-up. There are no
 * legal rules, package limits or retention behaviour here: those are open
 * questions for JJ, listed in the review report and not shown in the UI.
 */
import { CASES, type CaseRef, type Tone } from "./scenario";

export const FINAL_STATES = [
  { key: "empty", n: "1", name: "Ask HeroOS", note: "One question, one box." },
  { key: "typing", n: "2", name: "Entering the first inquiry", note: "No category, playbook or title to choose." },
  { key: "opening", n: "2→3", name: "HeroOS opens the case", note: "The same surface becomes the case; the title arrives." },
  { key: "conversation", n: "3", name: "Active conversation", note: "Guidance: HeroOS asks only what it needs." },
  { key: "warning", n: "4", name: "Warning", note: "Amber, labelled, with a safe next step." },
  { key: "block", n: "5", name: "Block", note: "Red, labelled “Stop” for users: HeroOS can't proceed, and says what it can do instead." },
  { key: "expert", n: "6", name: "Expert Review", note: "Dark pink: needs a human expert; nothing is sent until you choose." },
  { key: "cases", n: "7", name: "Cases drawer", note: "Cases only: search, Today, Earlier." },
  { key: "status", n: "8", name: "Case status", note: "Secondary slide-over: where the case stands and what's next." },
  { key: "reopened", n: "9", name: "Previous case reopened", note: "HeroOS picks up where you stopped." },
] as const;

export type FinalState = (typeof FINAL_STATES)[number]["key"];

export function isFinalState(value: string): value is FinalState {
  return FINAL_STATES.some((state) => state.key === value);
}

export type AdviserTurn = {
  kind: "heroos";
  id: string;
  at: string;
  tone: Tone;
  /** What HeroOS understood, in one line. */
  lead?: string;
  /** The headline of a warning, block or expert review. */
  title?: string;
  body?: string[];
  steps?: { heading: string; items: string[] };
  /** The one thing HeroOS needs to know next. */
  question?: string;
  /** Quick replies (only on the latest turn). */
  chips?: string[];
  next?: { heading: string; items: string[] };
  provide?: { heading: string; items: string[] };
  actions?: { label: string; primary?: boolean }[];
  /** A short line under the actions (Expert Review: who is in control). */
  note?: string;
};

export type FinalTurn =
  | { kind: "you"; id: string; at: string; text: string }
  | AdviserTurn
  | { kind: "event"; id: string; text: string }
  | { kind: "resume"; id: string; text: string }
  | { kind: "earlier"; id: string; text: string };

export const FIRST_INQUIRY =
  "Sarah on our front desk hasn't come in for two days and isn't answering her phone. What should I do?";

const ATTENDANCE: FinalTurn[] = [
  { kind: "you", id: "a1", at: "09:12", text: FIRST_INQUIRY },
  { kind: "event", id: "a1e", text: "Case opened and named by HeroOS" },
  {
    kind: "heroos",
    id: "a2",
    at: "09:12",
    tone: "guidance",
    lead: "This is an attendance concern: two days' absence, and no contact.",
    question: "Have you or her manager been able to reach Sarah in any way since she stopped coming in?",
    chips: ["Phone calls only, no answer", "Tried several ways", "Not yet"],
  },
  {
    kind: "you",
    id: "a3",
    at: "09:14",
    text: "Only phone calls. She's been with us 8 months and there's never been a problem before.",
  },
  {
    kind: "heroos",
    id: "a4",
    at: "09:14",
    tone: "guidance",
    body: [
      "Then start with a welfare check, not discipline. With a clean record, there may be a serious reason she hasn't been in touch.",
    ],
    steps: {
      heading: "Next steps",
      items: [
        "Send Sarah a short written message today asking her to contact you, by text and to her personal email.",
        "Try the emergency contact on her file.",
        "Keep a note of each attempt: date, time and method.",
      ],
    },
    question: "Is there anything on file, such as a leave request or a medical note, that could explain the absence?",
    chips: ["Nothing on file", "Yes, there's something"],
  },
];

const WARNING: FinalTurn[] = [
  {
    kind: "you",
    id: "a5",
    at: "09:16",
    text: "Nothing on file. Honestly, I'd rather just let her go. Can I send her a termination letter today?",
  },
  {
    kind: "heroos",
    id: "a6",
    at: "09:16",
    tone: "warning",
    title: "Don't send a termination letter today.",
    body: [
      "Nobody has reached Sarah or heard her side yet. Ending her employment now leaves Bush & Bush exposed if there's a genuine reason, such as illness or an emergency.",
    ],
    steps: {
      heading: "Safe next step",
      items: ["Make the written contact attempts first. If she still hasn't responded, tell me and we'll go through the formal steps."],
    },
    question: "Will you contact her first?",
    chips: ["Yes, I'll contact her first", "Why not end it now?"],
  },
];

const BLOCK: FinalTurn[] = [
  {
    kind: "you",
    id: "a7",
    at: "09:18",
    text: "Then draft the termination letter and date it last Friday, before she stopped coming in.",
  },
  {
    kind: "heroos",
    id: "a8",
    at: "09:18",
    tone: "stop",
    title: "HeroOS can't prepare a backdated letter.",
    body: [
      "A letter dated before the decision was made would misstate what happened. If the case is ever reviewed, it would seriously weaken Bush & Bush's position.",
    ],
    actions: [{ label: "Continue with the contact steps" }, { label: "What if Sarah doesn't respond?" }],
  },
];

const STAFFING: FinalTurn[] = [
  {
    kind: "you",
    id: "s1",
    at: "10:02",
    text: "We need a staffing plan for 2027. How many people should we hire, and where might we need to cut?",
  },
  { kind: "event", id: "s1e", text: "Case opened and named by HeroOS" },
  {
    kind: "heroos",
    id: "s2",
    at: "10:02",
    tone: "expert",
    title: "This needs an HR expert.",
    body: [
      "A 2027 workforce plan is outside what HeroOS handles on its own. The right answer depends on your growth targets, budget and team structure, so it needs a consultant's review rather than general guidance.",
    ],
    next: {
      heading: "What happens next",
      items: [
        "You choose Request Expert Review. HeroOS attaches this conversation and your Company Blueprint.",
        "An HR expert reviews it and replies in this case, including whether it needs a consultancy engagement.",
        "You decide how to proceed.",
      ],
    },
    provide: {
      heading: "Useful to include",
      items: ["Headcount today, by team", "2027 revenue or growth targets", "Roles you already plan to open or close"],
    },
    actions: [{ label: "Request Expert Review", primary: true }, { label: "Not now" }],
    note: "Nothing is sent until you choose Request Expert Review.",
  },
];

const PROBATION: FinalTurn[] = [
  { kind: "earlier", id: "p0", text: "Show 6 earlier messages · 16 Oct" },
  {
    kind: "heroos",
    id: "p1",
    at: "16 Oct, 16:40",
    tone: "guidance",
    body: [
      "Hold the review meeting with Omar on Monday 19 Oct. Bring the three missed deadlines with their dates, and hear his explanation before deciding anything.",
      "Tell me how the meeting went and we'll decide the next step.",
    ],
  },
  { kind: "you", id: "p2", at: "16 Oct, 16:42", text: "Will do." },
  { kind: "resume", id: "p3", text: "You left off here · 16 Oct" },
  {
    kind: "heroos",
    id: "p4",
    at: "11:05",
    tone: "guidance",
    lead: "Welcome back, Daniel.",
    question: "Omar's probation review meeting was set for yesterday, 19 Oct. Did it go ahead?",
    chips: ["Yes, it went ahead", "It was postponed", "Something else happened"],
  },
];

/** The case each state shows (null: the Ask page itself) and its turns. */
export function finalTurns(state: FinalState): { caseRef: CaseRef | null; turns: FinalTurn[] } {
  const find = (id: string) => CASES.find((c) => c.id === id) ?? null;
  switch (state) {
    case "empty":
    case "typing":
    case "cases":
      return { caseRef: null, turns: [] };
    case "opening":
      return { caseRef: find("attendance"), turns: [ATTENDANCE[0]] };
    case "conversation":
      return { caseRef: find("attendance"), turns: ATTENDANCE };
    case "warning":
    case "status":
      return { caseRef: find("attendance"), turns: [...ATTENDANCE, ...WARNING] };
    case "block":
      return { caseRef: find("attendance"), turns: [...ATTENDANCE, ...WARNING, ...BLOCK] };
    case "expert":
      return { caseRef: find("staffing"), turns: STAFFING };
    case "reopened":
      return { caseRef: find("probation"), turns: PROBATION };
  }
}

/** Where each case in the drawer opens (closed cases stay put in this mockup). */
export const CASE_OPENS: Partial<Record<string, FinalState>> = {
  attendance: "warning",
  staffing: "expert",
  probation: "reopened",
};

/** Where the prototype's main action leads (Send, a quick reply, an action). */
export const FINAL_NEXT: Record<FinalState, FinalState> = {
  empty: "typing",
  typing: "opening",
  opening: "conversation",
  conversation: "warning",
  warning: "block",
  block: "status",
  expert: "cases",
  cases: "reopened",
  status: "warning",
  reopened: "conversation",
};

/** Case status for the attendance case (after the warning). */
export const STATUS = {
  now: "Reaching Sarah",
  summary: "Two days' absence with no contact. Phone calls went unanswered; written contact and her emergency contact come next.",
  nextStep: "Send Sarah a written message and try her emergency contact. Then tell HeroOS what happened.",
  done: ["Phoned Sarah: no answer", "Checked her file: nothing that explains the absence"],
  needed: ["A written contact attempt (text and personal email)", "A call to her emergency contact", "Sarah's response"],
  facts: [
    ["Employee", "Sarah · Front desk"],
    ["Absent since", "Mon 19 Oct (2 working days)"],
    ["Service", "8 months"],
    ["Earlier issues", "None reported"],
  ] as const,
  history: [
    { at: "09:12", text: "You described the situation", tone: "done" },
    { at: "09:12", text: "HeroOS opened and named the case", tone: "done" },
    { at: "09:14", text: "Guidance: welfare check first", tone: "guidance" },
    { at: "09:16", text: "Warning: no termination letter yet", tone: "warning" },
    { at: "Now", text: "You stopped here: waiting to reach Sarah", tone: "current" },
  ] as const,
  context: ["Company Blueprint: Bush & Bush Law Group", "Jurisdiction: DIFC", "Company policies: none on file"],
};
