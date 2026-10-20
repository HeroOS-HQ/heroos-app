/**
 * Content for the Page 1 (Ask HeroOS) design review, 20 Oct 2026. Every name,
 * time and answer is illustrative: the scenarios come from the Aries/JJ
 * catch-up (an employee absent for two days; a 2027 staffing plan that needs
 * an expert; "Hello Daniel, welcome back"). Nothing here is a legal rule, a
 * package limit or a retention policy; those are open questions for JJ.
 */

export const DIRECTIONS = ["a", "b"] as const;
export type Direction = (typeof DIRECTIONS)[number];

export const DIRECTION_NAMES: Record<Direction, { name: string; line: string }> = {
  a: {
    name: "Quiet Desk",
    line: "Focused advisory: one question on an empty desk; navigation and history stay out of sight until asked for.",
  },
  b: {
    name: "Advisory Workspace",
    line: "Professional workspace: three top tabs, a slim case rail and a case header; case status docks beside the conversation.",
  },
};

export const STATES = [
  { key: "empty", code: "A", name: "First entry", note: "Signed in for the first time: one question, one box." },
  { key: "typing", code: "B", name: "Typing the first question", note: "No category, playbook or title to choose." },
  {
    key: "understanding",
    code: "B→C",
    name: "HeroOS opens the case",
    note: "Sent: HeroOS reads, checks the company setup, then opens and names the case.",
  },
  {
    key: "conversation",
    code: "C",
    name: "Active conversation · guidance",
    note: "The case has a title HeroOS chose; HeroOS asks only what it needs.",
  },
  { key: "warning", code: "D", name: "Warning", note: "Amber: HeroOS is warning you. Label, icon, wording and a safe next step." },
  { key: "block", code: "E", name: "Stop", note: "Red: HeroOS can't proceed with this request, and says what it can do instead." },
  {
    key: "expert",
    code: "F",
    name: "Expert Review",
    note: "Dark pink: outside the playbooks, so HeroOS raises it with a human expert instead of improvising.",
  },
  { key: "status", code: "G", name: "Case status open", note: "Where the case began, what was asked and told, where you stopped." },
  { key: "history", code: "H1", name: "Recent cases", note: "Previous cases, reachable but out of the way." },
  { key: "reopened", code: "H2", name: "Previous case reopened", note: "HeroOS picks up exactly where you stopped." },
] as const;

export type StateKey = (typeof STATES)[number]["key"];

export function isDirection(value: string): value is Direction {
  return (DIRECTIONS as readonly string[]).includes(value);
}

export function isState(value: string): value is StateKey {
  return STATES.some((state) => state.key === value);
}

export const COMPANY = {
  name: "Bush & Bush",
  legalName: "Bush & Bush Law Group",
  jurisdiction: "DIFC",
};

export const PERSON = { first: "Daniel", full: "Daniel Haddad", initials: "DH", email: "daniel@bushandbush.example", role: "Company admin" };

/** How a case stands, always in words (the dot only supports them). */
export type CaseStatus = "yours" | "reviewing" | "expert" | "closed";

export const CASE_STATUS: Record<CaseStatus, { label: string; dot: string }> = {
  yours: { label: "Waiting for you", dot: "bg-hero-blue" },
  reviewing: { label: "HeroOS is reviewing", dot: "bg-hero-control" },
  expert: { label: "Expert Review suggested", dot: "bg-[#a92f6c]" },
  closed: { label: "Closed", dot: "bg-[#b9c0cd]" },
};

export type CaseRef = { id: string; title: string; when: string; status: CaseStatus; group: "Today" | "Earlier" };

export const CASES: CaseRef[] = [
  { id: "attendance", title: "Attendance concern — Sarah", when: "09:12", status: "yours", group: "Today" },
  { id: "staffing", title: "2027 staffing plan", when: "10:02", status: "expert", group: "Today" },
  { id: "probation", title: "Probation review — Omar", when: "16 Oct", status: "yours", group: "Earlier" },
  { id: "lateness", title: "Repeated lateness — Ahmed", when: "2 Oct", status: "closed", group: "Earlier" },
  { id: "leave", title: "Annual leave carry-over", when: "28 Sep", status: "closed", group: "Earlier" },
];

/** The four response states of the same conversation (never four pages). */
export type Tone = "guidance" | "warning" | "stop" | "expert";

export type HeroTurn = {
  kind: "hero";
  id: string;
  at: string;
  tone: Tone;
  /** HeroOS restating what it understood (plain, one line). */
  lead?: string;
  /** The headline of a warning, stop or expert review. */
  title?: string;
  body?: string[];
  steps?: { heading: string; items: string[] };
  /** The one thing HeroOS needs to know next. */
  question?: string;
  /** Quick replies (only on the latest turn). */
  chips?: string[];
  /** Expert Review: what happens, what helps, what the plan covers. */
  next?: { heading: string; items: string[] };
  provide?: { heading: string; items: string[] };
  plan?: string;
  actions?: { label: string; primary?: boolean }[];
  /** Quiet trust line: what HeroOS took into account. */
  considered?: string[];
};

export type Turn =
  | { kind: "user"; id: string; at: string; text: string }
  | HeroTurn
  | { kind: "divider"; id: string; text: string }
  | { kind: "earlier"; id: string; text: string };

export const FIRST_QUESTION =
  "Sarah on our front desk hasn't come in for two days and isn't answering her phone. What should I do?";

const ATTENDANCE: Turn[] = [
  { kind: "user", id: "a1", at: "09:12", text: FIRST_QUESTION },
  { kind: "divider", id: "a1b", text: "Case opened and named by HeroOS" },
  {
    kind: "hero",
    id: "a2",
    at: "09:12",
    tone: "guidance",
    lead: "Understood. This is an attendance concern: two days absent, with no contact. I've opened a case for it.",
    question:
      "Before anything else: has anyone reached Sarah since she stopped coming in, by call, message, email or her emergency contact?",
    chips: ["Phone calls only", "Tried several ways, no reply", "Not yet"],
    considered: ["Company Blueprint", "DIFC jurisdiction"],
  },
  {
    kind: "user",
    id: "a3",
    at: "09:14",
    text: "Only phone calls. She's been with us 8 months and there's never been a problem before.",
  },
  {
    kind: "hero",
    id: "a4",
    at: "09:14",
    tone: "guidance",
    body: [
      "Then the first step is a welfare check, not discipline. With a clean record, there may be a serious reason she hasn't been in touch.",
    ],
    steps: {
      heading: "Next steps",
      items: [
        "Send Sarah a short written message today asking her to contact you: by text, and to her personal email.",
        "Try the emergency contact on her file.",
        "Note each attempt: date, time and method.",
      ],
    },
    question: "Is there anything on file, such as a leave request, a medical note or a recent conversation, that could explain the absence?",
    chips: ["Nothing on file", "Yes, there's something"],
    considered: ["Company Blueprint", "DIFC jurisdiction", "No attendance policy on file"],
  },
];

const WARNING: Turn[] = [
  {
    kind: "user",
    id: "a5",
    at: "09:16",
    text: "Nothing on file. Honestly, I'd rather just let her go. Can I send her a termination letter today?",
  },
  {
    kind: "hero",
    id: "a6",
    at: "09:16",
    tone: "warning",
    title: "Don't send a termination letter today.",
    body: [
      "Two days without contact isn't enough to act on. Nobody has reached Sarah or heard her side yet. Ending her employment now leaves Bush & Bush exposed if there's a genuine reason, such as illness or an emergency.",
    ],
    steps: {
      heading: "Safe next step",
      items: ["Make the written contact attempts first. If she still hasn't responded, come back here and HeroOS will take you through the formal steps."],
    },
    question: "Shall we go ahead with the contact steps?",
    chips: ["Yes, I'll contact her first", "Why not end it now?"],
    considered: ["Company Blueprint", "DIFC jurisdiction"],
  },
];

const BLOCK: Turn[] = [
  {
    kind: "user",
    id: "a7",
    at: "09:18",
    text: "Fine. Then draft the termination letter but date it last Friday, before she stopped coming in.",
  },
  {
    kind: "hero",
    id: "a8",
    at: "09:18",
    tone: "stop",
    title: "HeroOS can't prepare a backdated letter.",
    body: [
      "A letter dated before the decision was made would misstate what happened. If the case were ever reviewed, it would seriously weaken Bush & Bush's position. HeroOS won't draft or support it.",
    ],
    actions: [{ label: "Continue with the contact steps" }, { label: "What if Sarah doesn't respond?" }],
  },
];

export const STAFFING: Turn[] = [
  {
    kind: "user",
    id: "s1",
    at: "10:02",
    text: "We need a staffing plan for 2027. How many people should we hire, and where might we need to cut?",
  },
  {
    kind: "hero",
    id: "s2",
    at: "10:02",
    tone: "expert",
    title: "This needs an HR expert, not a quick answer.",
    body: [
      "A 2027 workforce plan, covering hiring and possible reductions, is outside the situations HeroOS handles on its own. The right answer depends on your growth targets, budget and team structure, so it needs a consultant rather than general guidance.",
    ],
    next: {
      heading: "What happens next",
      items: [
        "You send the request; HeroOS attaches this conversation and your Company Blueprint.",
        "An HR expert replies here with the scope, and an estimate if it's consultancy work.",
        "You decide whether to go ahead.",
      ],
    },
    provide: {
      heading: "Useful to include",
      items: ["Headcount today, by team", "2027 revenue or growth targets", "Roles you already plan to open or close"],
    },
    plan: "Whether this is covered by your plan or quoted separately is confirmed before any work begins.",
    actions: [{ label: "Request Expert Review", primary: true }, { label: "Not now" }],
  },
];

export const PROBATION: Turn[] = [
  { kind: "earlier", id: "p0", text: "6 earlier messages · 16 Oct" },
  {
    kind: "hero",
    id: "p1",
    at: "16 Oct, 16:40",
    tone: "guidance",
    body: [
      "Hold the review meeting with Omar on Monday 19 Oct. Bring the three missed deadlines with their dates, and hear his explanation before deciding anything.",
      "Tell me how the meeting went and we'll decide the next step.",
    ],
  },
  { kind: "user", id: "p2", at: "16 Oct, 16:42", text: "Will do." },
  { kind: "divider", id: "p3", text: "You left off here · 16 Oct" },
  {
    kind: "hero",
    id: "p4",
    at: "11:05",
    tone: "guidance",
    lead: "Welcome back, Daniel.",
    question: "Omar's probation review meeting was set for yesterday, 19 Oct. Did it go ahead?",
    chips: ["Yes, it went ahead", "It was postponed", "Something else happened"],
    considered: ["Earlier messages in this case", "Company Blueprint"],
  },
];

/** What each state shows in the conversation (null: the Ask page itself). */
export function turnsFor(state: StateKey): { caseId: string | null; turns: Turn[] } {
  switch (state) {
    case "empty":
    case "typing":
    case "history":
      return { caseId: null, turns: [] };
    case "understanding":
      return { caseId: "attendance", turns: [ATTENDANCE[0]] };
    case "conversation":
      return { caseId: "attendance", turns: ATTENDANCE };
    case "warning":
    case "status":
      return { caseId: "attendance", turns: [...ATTENDANCE, ...WARNING] };
    case "block":
      return { caseId: "attendance", turns: [...ATTENDANCE, ...WARNING, ...BLOCK] };
    case "expert":
      return { caseId: "staffing", turns: STAFFING };
    case "reopened":
      return { caseId: "probation", turns: PROBATION };
  }
}

/** Case status panel content for the attendance case (state G). */
export const ATTENDANCE_STATUS = {
  summary:
    "Sarah has been absent for two days without contact. Phone calls went unanswered; written contact and the emergency contact are next.",
  nextStep: "Send Sarah a written message and try her emergency contact, then tell HeroOS what happened.",
  journey: [
    { at: "09:12", title: "You described the situation", detail: "Two days absent, no contact.", tone: "done" },
    { at: "09:14", title: "HeroOS asked what had been tried", detail: "Phone calls only. 8 months' service, no earlier issues.", tone: "done" },
    { at: "09:14", title: "Guidance: welfare check first", detail: "Written message, emergency contact, a note of each attempt.", tone: "guidance" },
    { at: "09:16", title: "Warning: no termination letter yet", detail: "Not before Sarah has been reached or heard.", tone: "warning" },
    { at: "Now", title: "You stopped here", detail: "Waiting for: whether Sarah responds.", tone: "current" },
  ] as const,
  facts: [
    ["Employee", "Sarah · Front desk"],
    ["Absent since", "Mon 19 Oct (2 working days)"],
    ["Contact tried", "Phone calls"],
    ["Service", "8 months"],
    ["Earlier issues", "None reported"],
  ] as const,
  open: ["Has Sarah responded?", "Anything that explains the absence (leave, medical note)?"],
  context: ["Bush & Bush Law Group blueprint", "Jurisdiction: DIFC", "Company policies: none on file"],
};
