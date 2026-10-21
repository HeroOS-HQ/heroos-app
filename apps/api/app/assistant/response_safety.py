"""A deterministic check on each Hannah reply before it is shown (V1.2).

Hannah's instruction tells the model not to prescribe sanctions or claim
actions, but a live test showed an instruction alone doesn't hold: asked about
an employee late four times after two documented informal discussions, the
model answered "the next step is usually a more formal written warning". So the
API reads every reply, after the provider returns it and before the browser
gets it, for a few *clear* problems:

- ``sanction_recommendation``: a sanction presented as what to do or what comes
  next ("the next step is usually a formal written warning", "you should issue a
  written warning", "I recommend terminating the employee", "Suspend the worker
  immediately", "the appropriate penalty is dismissal", "this warrants a final
  warning", "a written warning would be appropriate").
- ``procedural_certainty``: a sanction or a disciplinary sequence presented as
  legally required or standard ("a written warning is legally required", "the
  usual process is a verbal warning, then a written warning").
- ``jurisdiction_certainty``: a law said to apply for certain ("DIFC law
  definitely governs").
- ``action_claim``: a claim that Hannah, or the conversation, did something in
  HeroOS ("I've updated the case", "I've issued the warning", "I've selected
  the serious-misconduct pathway", "the employee has been dismissed").

A reply with one of these is replaced by a fixed, neutral reply (``FALLBACKS``):
no sanction, no timeframe, nothing from the conversation, no claim of review.

How: the reply is read sentence by sentence, outside quotations, skipping
questions. Each pattern below pairs a *frame* (a recommendation, a claim, a
certainty) with what it is about (a sanction, a case record). The same words are
let through when the frame isn't there ("a written warning isn't something I can
decide for you"), when they are negated ("I can't recommend a written warning",
"you shouldn't issue..."), conditional or open ("whether dismissal is available
depends on..."), or what the user said ("you told me the employee received a
written warning").

**The Ask HeroOS gateway (M2-NEW-05)** reuses the same machinery with five more
checks (``gateway_problem``), because HeroOS may now explain an approved option
as a possibility the employer decides on, so what must never pass is sharper:

- ``authorization``: a sanction or deduction presented as allowed for this
  employer ("you can dismiss him today", "dismissal without notice is
  available", "it's fine to deduct the cost");
- ``review_promise``: a specialist review said to be requested or coming ("I've
  sent this to a HeroOS Expert", "an expert will reply shortly", "your ticket
  has been created");
- ``monitoring_promise``: HeroOS promising to watch, track or remind ("I'll
  monitor the deadline", "I'll remind you");
- ``document_claim``: a document said to be prepared ("I've drafted the
  warning letter", "here is the suspension notice");
- ``legal_certainty``: the law stated as certain ("the law clearly says...",
  "by law you must...").

Explaining an approved option stays allowed ("suspension may be one of the
options the approved process considers after the investigation"; "whether
termination without notice is available depends on the conditions and
review"): the same negation, conditional and attribution guards apply.

Limits, stated plainly: these are patterns, not understanding. A reply can be
unsafe in ways no pattern names, or worded so that a pattern misses it, and an
unusual safe phrasing can be caught. This is defence in depth behind the
instruction, not a legal classifier, and it says nothing about whether a reply
is legally accurate. It never logs or returns the text it matched.
"""

import re
from dataclasses import dataclass
from typing import Final, Literal

Check = Literal[
    "action_claim", "sanction_recommendation", "procedural_certainty", "jurisdiction_certainty"
]
GatewayCheck = Literal[
    "action_claim", "sanction_recommendation", "procedural_certainty", "jurisdiction_certainty",
    "authorization", "review_promise", "monitoring_promise", "document_claim", "legal_certainty",
]  # fmt: skip


@dataclass(frozen=True, slots=True)
class ReviewedReply:
    """What to show, and which check replaced the model's reply (None: shown unchanged)."""

    text: str
    replaced_by: Check | None


SANCTION_FALLBACK: Final = (
    "I can't recommend a specific disciplinary action from this exploratory chat: that "
    "decision stays with the employer, through the authorized process. Before anything is "
    "decided, it helps to be clear on the facts, the employee's explanation and what the "
    "company's policy and the applicable employment requirements say. What explanation has "
    "the employee given so far?"
)
JURISDICTION_FALLBACK: Final = (
    "I can't say for certain from this chat which employment law applies. That depends on "
    "facts such as which legal entity employs the person and their contract, and it may need "
    "confirming by a qualified UAE employment-law professional. Which legal entity employs "
    "the employee?"
)
ACTION_FALLBACK: Final = (
    "I can't make changes in HeroOS: this chat can't update the case, record a decision, issue "
    "a warning or choose a pathway, and nothing in the case has been changed. You can check "
    "which actions are available in the Guided case workflow. What would you like to think "
    "through next?"
)
FALLBACKS: Final[dict[Check, str]] = {
    "action_claim": ACTION_FALLBACK,
    "sanction_recommendation": SANCTION_FALLBACK,
    "procedural_certainty": SANCTION_FALLBACK,
    "jurisdiction_certainty": JURISDICTION_FALLBACK,
}
# The most misleading first: a claimed action, then a prescribed sanction.
PRIORITY: Final[tuple[Check, ...]] = (
    "action_claim",
    "sanction_recommendation",
    "procedural_certainty",
    "jurisdiction_certainty",
)

# --- vocabulary -----------------------------------------------------------------------


def _gap(words: int) -> str:
    """Up to ``words`` words in between."""
    return rf"(?:\s+[\w'-]+){{0,{words}}}"


# A disciplinary sanction, as a noun or a verb form.
SANCTION = (
    r"(?:(?:(?:formal|final|first|second|third|last|written|verbal|oral|official|disciplinary"
    r"|serious|strong)\s+)*(?:warnings?(?:\s+letters?)?|reprimands?)"
    r"|suspen(?:sions?|ds?|ding|ded)\b|terminat(?:ions?|e|es|ing|ed)\b"
    r"|dismiss(?:als?|es|ing|ed)?\b|demot(?:ions?|e|es|ing|ed)\b|penalt(?:y|ies)\b"
    r"|sanctions?\b|disciplinary\s+(?:action|measures?|proceedings?|hearing)"
    r"|(?:fir(?:e|es|ing)|sack(?:s|ing)?)\s+(?:him|her|them|the\s+(?:employee|worker|person)))"
)
# Imposing one ("issue a written warning", "proceed with termination").
IMPOSE = (
    r"(?:issu(?:e|es|ing)|giv(?:e|es|ing)|impos(?:e|es|ing)|serv(?:e|es|ing)|hand(?:s|ing)?"
    r"|deliver(?:s|ing)?|appl(?:y|ies|ying)|initiat(?:e|es|ing)|proceed(?:s|ing)?\s+with"
    r"|go(?:ing)?\s+ahead\s+with|mov(?:e|es|ing)\s+(?:on\s+)?to|escalat(?:e|es|ing)\s+to"
    r"|consider(?:ing)?\s+(?:issuing|giving|imposing))"
)
SANCTION_VERB = r"(?:suspend|terminat|dismiss|demot|fire|sack)(?:e|ing)?\b"
DOES_SANCTION = rf"(?:{IMPOSE}{_gap(4)}\s+{SANCTION}|{SANCTION_VERB})"
# The same as an instruction (base forms only: "Giving a warning now..." isn't one).
IMPOSE_NOW = (
    r"(?:issue|give|impose|serve|hand|deliver|apply|initiate|proceed\s+with|go\s+ahead\s+with"
    r"|move\s+(?:on\s+)?to|escalate\s+to|consider\s+(?:issuing|giving|imposing))"
)
# Something a claimed action would change in HeroOS.
TARGET = (
    r"(?:case|record|file|warning|notice|letter|document|pathway|route|stage|hold|status"
    r"|decision|outcome|penalty|sanction|employee|worker|hearing|investigation|review|history"
    r"|facts|answers|workflow)s?\b"
)
# What an action in HeroOS would do (not words a chat reply uses for itself: "prepared", "added").
CLAIM_DONE = (
    r"(?:updated|changed|recorded|logged|saved|issued|sent|generated|selected|chose|chosen"
    r"|cleared|lifted|closed|moved|advanced|marked|filed|submitted|approved|escalated|dismissed"
    r"|suspended|terminated|edited|finali[sz]ed|scheduled)"
)
CLAIM_TO_DO = (
    r"(?:update|change|record|log|save|issue|send|generate|select|choose|clear|lift|close|move"
    r"|advance|file|submit|approve|escalate|dismiss|suspend|terminate|edit|finali[sz]e"
    r"|schedule)"
)
SUBJECT = r"(?:you|we|the\s+employer|your\s+company|the\s+company|management|hr)"
MODAL = (
    r"(?:(?:'d|'ll|\s+would|\s+will)?\s+(?:should|must|need\s+to|needs\s+to|have\s+to|has\s+to"
    r"|ought\s+to|can\s+now|may\s+now|might\s+want\s+to|may\s+want\s+to)"
    r"|'ll\s+(?:need|want)\s+to|\s+will\s+(?:need|want)\s+to)"
)
# "is", "would be", "would usually be"...
SHOULD_BE = r"(?:is|are|(?:would|will|should)(?:\s+\w+ly)?\s+be)\b"

_FRAMES: Final[tuple[tuple[Check, str], ...]] = (
    # "The next step is usually a (more) formal written warning."
    (
        "sanction_recommendation",
        rf"\bnext\s+(?:logical\s+|appropriate\s+|natural\s+|formal\s+)?step\b{_gap(2)}"
        rf"\s+{SHOULD_BE}{_gap(5)}\s+(?:{SANCTION}|to\s+{DOES_SANCTION})",
    ),
    # "You should issue a written warning." / "You should consider suspending them."
    ("sanction_recommendation", rf"\b{SUBJECT}{MODAL}\b{_gap(3)}\s+{DOES_SANCTION}"),
    # "I recommend terminating the employee." / "My advice would be a final warning."
    (
        "sanction_recommendation",
        rf"(?:\bI(?:'d|\s+would)?\s+(?:strongly\s+)?(?:recommend|suggest|advise|propose|urge)"
        rf"|\bmy\s+(?:recommendation|advice|suggestion)\s+(?:is|would\s+be))\b{_gap(5)}"
        rf"\s+(?:{SANCTION}|{DOES_SANCTION})",
    ),
    # Imperatives: "Suspend the worker immediately." / "Proceed with termination."
    (
        "sanction_recommendation",
        rf"^(?:(?:so|then|now|next|please|simply|just)\s+)?(?:{IMPOSE_NOW}{_gap(4)}\s+{SANCTION}"
        r"|(?:suspend|terminate|dismiss|demote|fire|sack)\s+(?:him|her|them|the\s+\w+))",
    ),
    # "The appropriate penalty is dismissal."
    (
        "sanction_recommendation",
        r"\bthe\s+(?:appropriate|right|correct|best|proper|fair|proportionate|usual|standard"
        r"|natural|logical|obvious|reasonable)\s+(?:penalty|sanction|response|outcome"
        r"|course\s+of\s+action|action|consequence|step|next\s+step|option|measure)\b"
        rf"{_gap(2)}\s+{SHOULD_BE}{_gap(4)}\s+(?:{SANCTION}|to\s+{DOES_SANCTION})",
    ),
    # "A written warning would be appropriate here." / "Dismissal is the next step."
    (
        "sanction_recommendation",
        rf"{SANCTION}{_gap(4)}\s+(?:{SHOULD_BE}|seems|looks|sounds)\s+(?:now\s+"
        r"|probably\s+|likely\s+|usually\s+|generally\s+|typically\s+|clearly\s+)?"
        r"(?:appropriate|justified|warranted|necessary|reasonable|proportionate|in\s+order"
        r"|the\s+(?:(?:right|next|correct|best|logical|appropriate|natural|usual|standard"
        r"|obvious|formal)\s+){1,2}(?:step|move|course|response|option|outcome|action|thing))\b",
    ),
    # "This warrants a final written warning."
    (
        "sanction_recommendation",
        rf"\b(?:warrants?|justif(?:y|ies)|merits?|calls?\s+for|deserves?)\b{_gap(3)}"
        rf"\s+{SANCTION}",
    ),
    # "It's time to move to a formal warning." / "escalate to a written warning"
    (
        "sanction_recommendation",
        r"\b(?:escalat(?:e|es|ing)|mov(?:e|es|ing)|progress(?:es|ing)?|step(?:s|ping)?"
        rf"\s+up)\s+(?:on\s+|up\s+)?(?:to|towards)\b{_gap(3)}\s+{SANCTION}",
    ),
    # "It's best to issue a final warning now."
    (
        "sanction_recommendation",
        r"\b(?:it(?:'s|\s+is|\s+would\s+be)|now\s+is)\s+(?:probably\s+)?(?:best|time"
        r"|advisable|appropriate|wise|sensible|reasonable|right|the\s+right\s+time)\s+to\b"
        rf"{_gap(2)}\s+{DOES_SANCTION}",
    ),
    # "A written warning is legally required before dismissal."
    (
        "procedural_certainty",
        rf"{SANCTION}{_gap(4)}\s+(?:is|are)\s+(?:legally\s+|now\s+|always\s+)?(?:required"
        r"|mandatory|compulsory|obligatory)\b",
    ),
    (
        "procedural_certainty",
        r"\b(?:the\s+)?(?:law|labou?r\s+law|legislation|regulations?)\s+(?:requires?|mandates?"
        rf"|obliges?)\b{_gap(6)}\s+{SANCTION}",
    ),
    (
        "procedural_certainty",
        r"\byou\s+are\s+(?:legally\s+)?(?:required|obliged|obligated|bound)\s+to\b"
        rf"{_gap(3)}\s+{DOES_SANCTION}",
    ),
    # "The usual process is a verbal warning, then a written warning, then dismissal."
    (
        "procedural_certainty",
        r"\b(?:standard|usual|normal|typical|required|correct|proper|legal|mandatory|formal)"
        r"\s+(?:disciplinary\s+)?(?:sequence|process|procedure|progression|order|path|route"
        rf"|steps?)\b{_gap(3)}\s+(?:is|are|goes|starts|begins|would\s+be|involves|runs)\b"
        rf"{_gap(5)}\s+{SANCTION}",
    ),
    # "DIFC law definitely governs because the company is registered there."
    (
        "jurisdiction_certainty",
        r"\b(?:definitely|certainly|clearly|undoubtedly|unquestionably|automatically)\s+"
        r"(?:governs?|appl(?:y|ies)|will\s+(?:govern|apply))\b",
    ),
    (
        "jurisdiction_certainty",
        rf"\b(?:law|framework|regime|legislation)\b{_gap(3)}\s+(?:definitely|certainly)\b",
    ),
    # "I've already updated the case." / "I've issued the formal warning."
    (
        "action_claim",
        rf"\bI(?:'ve|\s+have)?(?:\s+(?:just|already|now|also))?\s+{CLAIM_DONE}\b"
        rf"(?!\s+my\b){_gap(4)}\s+{TARGET}",
    ),
    # "I'll update the case record now."
    (
        "action_claim",
        r"\bI(?:'ll|\s+will|'m\s+going\s+to|\s+am\s+going\s+to)(?:\s+(?:now|just|also|go"
        rf"\s+ahead\s+and))?\s+{CLAIM_TO_DO}\b(?!\s+my\b){_gap(4)}\s+{TARGET}",
    ),
    # "The case has been updated." / "The hold has now been cleared."
    (
        "action_claim",
        r"\b(?:case|record|file|warning|notice|letter|document|hold|pathway|route|stage"
        r"|status|decision|history|facts)\s+(?:has|have|is\s+now|are\s+now)\s+(?:now\s+"
        rf"|just\s+|already\s+)?(?:been\s+)?{CLAIM_DONE}\b",
    ),
    # "The employee has been dismissed." / "has been given a final warning"
    (
        "action_claim",
        r"\b(?:employee|worker|staff\s+member|team\s+member)\s+(?:has|have)\s+(?:now\s+"
        r"|just\s+|already\s+)?been\s+(?:dismissed|suspended|terminated|fired|demoted\b"
        rf"|(?:issued|given|served){_gap(3)}\s+{SANCTION})",
    ),
)
PATTERNS: Final[tuple[tuple[Check, re.Pattern[str]], ...]] = tuple(
    (check, re.compile(pattern, re.IGNORECASE)) for check, pattern in _FRAMES
)

# --- the Ask HeroOS gateway's additional checks -------------------------------------------

DEDUCT = r"(?:deduct(?:s|ing)?|withhold(?:s|ing)?|dock(?:s|ing)?)\b"
DEDUCTION = r"(?:(?:salary|pay|wage)\s+)?deductions?\b"
PERMISSION = (
    r"(?:can|could|may|are\s+(?:allowed|entitled|free|permitted)\s+to|is\s+(?:allowed"
    r"|entitled|permitted)\s+to|have\s+the\s+right\s+to|has\s+the\s+right\s+to)"
)
SPECIALIST = (
    r"(?:(?:HeroOS\s+)?(?:experts?|specialists?|reviewers?|lawyers?|advisers?|advisors?)"
    r"|(?:review|expert|legal)\s+team)"
)
DEADLINE = r"(?:deadlines?|dates?|timelines?|time\s+limits?|timeframes?|it)"
DOCUMENT = r"(?:letters?|notices?|documents?|memos?|warnings?|emails?\s+to\s+the\s+employee)"

_GATEWAY_FRAMES: Final[tuple[tuple[GatewayCheck, str], ...]] = (
    # "I've created the case." / "I've opened a case and added the facts."
    (
        "action_claim",
        r"\bI(?:'ve|\s+have)?(?:\s+(?:just|already|now|also))?\s+(?:created|opened|started"
        rf"|raised|added|stored|entered|registered)\b{_gap(4)}\s+{TARGET}",
    ),
    # "... and sent it to a HeroOS Expert." (the claim's subject earlier in the sentence)
    (
        "review_promise",
        r"\b(?:sent|forwarded|referred|escalated|passed|submitted)\s+(?:it|this|that|the\s+case"
        r"|your\s+case|the\s+matter|this\s+matter|your\s+question)\s+(?:on\s+)?to\s+(?:an?\s+"
        rf"|the\s+|our\s+)?{SPECIALIST}",
    ),
    # "Yes, you can dismiss her today." / "The company may deduct the repair cost."
    (
        "authorization",
        rf"\b{SUBJECT}\s+{PERMISSION}\s+(?:now\s+|still\s+|legally\s+|safely\s+|lawfully\s+"
        rf"|lawfully\s+|go\s+ahead\s+and\s+)?(?:{DOES_SANCTION}|{DEDUCT})",
    ),
    # "It's fine to deduct the cost." / "You're within your rights to terminate him."
    (
        "authorization",
        r"\b(?:it(?:'s|\s+is|\s+would\s+be|\s+will\s+be)\s+(?:fine|ok(?:ay)?|lawful|legal"
        r"|acceptable|permissible|allowed|permitted)\s+to|(?:you're|you\s+are)\s+within\s+your"
        rf"\s+rights\s+to)\s+(?:{DOES_SANCTION}|{DEDUCT})",
    ),
    # "Dismissal without notice is available here." / "A deduction is allowed."
    (
        "authorization",
        rf"(?:{SANCTION}|{DEDUCTION}){_gap(4)}\s+(?:is|are|would\s+be|will\s+be)\s+(?:now\s+"
        r"|clearly\s+|certainly\s+|definitely\s+)?(?:available|allowed|permitted|lawful|legal"
        r"|permissible|fine|ok(?:ay)?)\b",
    ),
    # "I've sent this to a HeroOS Expert." / "I've referred your case to a specialist."
    (
        "review_promise",
        r"\bI(?:'ve|\s+have)?(?:\s+(?:just|already|now|also))?\s+(?:sent|forwarded|referred"
        rf"|escalated|passed|raised|submitted|flagged){_gap(4)}\s+(?:to|with|for)\s+(?:an?\s+"
        rf"|the\s+|our\s+)?{SPECIALIST}",
    ),
    # "I'll forward this to our review team."
    (
        "review_promise",
        r"\bI(?:'ll|\s+will|'m\s+going\s+to|\s+am\s+going\s+to)\s+(?:send|forward|refer"
        r"|escalate|pass|raise|submit|flag)\b",
    ),
    # "A HeroOS Expert will reply shortly." / "The specialist will be in touch."
    (
        "review_promise",
        rf"\b(?:an?|the|our)\s+{SPECIALIST}\s+(?:will|shall|is\s+going\s+to)\s+(?:now\s+"
        r"|soon\s+|shortly\s+)?(?:reply|respond|review|contact|get\s+back|be\s+in\s+touch"
        r"|look|call|reach\s+out|follow\s+up)",
    ),
    # "Your support ticket has been created." / "I've raised a request."
    (
        "review_promise",
        r"\b(?:ticket|request|referral|review)\s+(?:has|have)\s+(?:now\s+|just\s+|already\s+)?"
        r"been\s+(?:created|raised|opened|submitted|logged|sent|requested|booked)\b",
    ),
    (
        "review_promise",
        r"\bI(?:'ve|\s+have)?\s+(?:created|raised|opened|submitted|logged|booked|requested)\s+"
        r"(?:an?\s+|the\s+|your\s+)?(?:support\s+|expert\s+|specialist\s+)?(?:ticket|request"
        r"|referral|review)\b",
    ),
    # "I'll monitor the deadline for you." / "I'll remind you before it's due."
    (
        "monitoring_promise",
        r"\b(?:I|we|HeroOS)(?:'ll|\s+will|\s+can|\s+shall)?(?:\s+(?:also|then|now))?\s+"
        r"(?:monitor|remind\s+you|send\s+you\s+(?:an?\s+)?reminders?|notify\s+you|alert\s+you"
        rf"|make\s+sure\s+you\s+(?:don't|do\s+not)\s+miss|keep\s+(?:track\s+of|an\s+eye\s+on)"
        rf"\s+(?:the\s+|your\s+|this\s+)?{DEADLINE})",
    ),
    # "I've drafted the warning letter." / "Here is the suspension notice:"
    (
        "document_claim",
        r"\bI(?:'ve|\s+have)?(?:\s+(?:just|already|now|also))?\s+(?:drafted|prepared|created"
        rf"|written|generated|attached|produced){_gap(4)}\s+{DOCUMENT}",
    ),
    (
        "document_claim",
        r"\bI(?:'ll|\s+will|'m\s+going\s+to)\s+(?:draft|prepare|generate|write|create|produce)"
        rf"{_gap(4)}\s+{DOCUMENT}",
    ),
    (
        "document_claim",
        rf"^here(?:'s|\s+is|\s+are)\s+(?:an?|the|your)\b{_gap(3)}\s+{DOCUMENT}",
    ),
    # "The law clearly says..." / "By law, you must..." / "It is definitely unlawful."
    (
        "legal_certainty",
        r"\b(?:the\s+)?(?:law|legislation|regulations?|statute)\s+(?:definitely|clearly|certainly"
        r"|always|explicitly|expressly)\s+(?:says|requires|states|allows|permits|prohibits|forbids"
        r"|provides|gives|entitles)\b",
    ),
    (
        "legal_certainty",
        r"\bit(?:'s|\s+is)\s+(?:definitely|certainly|clearly|always|absolutely)\s+(?:illegal"
        r"|unlawful|lawful|legal|required\s+by\s+law|against\s+the\s+law)\b",
    ),
    (
        "legal_certainty",
        r"\b(?:by|under\s+the|according\s+to\s+the)\s+law,?\s+(?:you|employers?|the\s+employer"
        r"|the\s+company)\s+(?:must|have\s+to|has\s+to|are\s+required|is\s+required|cannot"
        r"|can't|may\s+not)\b",
    ),
    # "Secret recording is illegal." / "You always need the employee's consent."
    (
        "legal_certainty",
        r"\b(?:is|are|would\s+be)\s+(?:always\s+)?(?:illegal|unlawful|against\s+the\s+law)\b",
    ),
    (
        "legal_certainty",
        r"\b(?:always|in\s+all\s+cases|in\s+every\s+case)\s+(?:need|needs|require|requires"
        r"|have\s+to|has\s+to|must|get|gets|are\s+entitled|is\s+entitled)\b",
    ),
)
GATEWAY_PATTERNS: Final[tuple[tuple[GatewayCheck, re.Pattern[str]], ...]] = (
    *PATTERNS,
    *((check, re.compile(pattern, re.IGNORECASE)) for check, pattern in _GATEWAY_FRAMES),
)
# The most misleading first: an action or promise HeroOS can't keep, then an outcome.
GATEWAY_PRIORITY: Final[tuple[GatewayCheck, ...]] = (
    "action_claim", "document_claim", "review_promise", "monitoring_promise", "authorization",
    "sanction_recommendation", "procedural_certainty", "legal_certainty", "jurisdiction_certainty",
)  # fmt: skip

# A frame is not a problem when it is negated, conditional or open just before it.
_GUARD = re.compile(
    r"\b(?:not|no|never|nothing|none|neither|nor|cannot|unable|without|whether|if|unless"
    r"|rather\s+than|instead\s+of|avoid(?:ing)?|against|before|until|wouldn't|shouldn't"
    r"|can't|couldn't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|haven't|hasn't)\b"
    r"|n't\b",
    re.IGNORECASE,
)
# ... or the words between its trigger and its subject turn it ("before any warning").
_BLOCKER = re.compile(
    r"\b(?:not|no|never|any|before|after|until|without|rather|instead|unless|whether|if)\b"
    r"|n't\b",
    re.IGNORECASE,
)
# What the user said, reported back: "You told me the employee received a warning."
_ATTRIBUTED = re.compile(
    r"^\W*(?:you(?:'ve|\s+have)?\s+(?:previously\s+|earlier\s+|already\s+)?(?:said|told|"
    r"mentioned|noted|wrote|described|explained|shared|asked)|as\s+you\s+(?:said|mentioned"
    r"|described|noted)|according\s+to\s+you)\b",
    re.IGNORECASE,
)
_WITHOUT_NOTICE = re.compile(r"\bwithout\s+(?:prior\s+)?notice\b", re.IGNORECASE)
_QUOTED = re.compile(r'"[^"\n]{0,400}"')
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_CLAUSE = re.compile(r"[;:]|\s[-–—]+\s")
_BULLET = re.compile(r"^[\s\-*•\d.)]+")
_WINDOW_WORDS: Final = 8


def _normalized(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'")
    return text.replace("“", '"').replace("”", '"')


def _guarded(clause: str, match: re.Match[str]) -> bool:
    # Words just before the frame, back to the previous comma.
    before = clause[: match.start()].rsplit(",", 1)[-1]
    window = " ".join(before.split()[-_WINDOW_WORDS:])
    if _GUARD.search(window):
        return True
    # Words inside the frame, after its first word (the trigger itself is never a blocker).
    # "Without notice" names a kind of dismissal, not a negation.
    inner = _WITHOUT_NOTICE.sub(" ", match.group(0)).split(None, 1)
    return len(inner) == 2 and _BLOCKER.search(inner[1]) is not None


def _problems[C: str](text: str, patterns: tuple[tuple[C, re.Pattern[str]], ...]) -> set[C]:
    found: set[C] = set()
    for sentence in _SENTENCE.split(_QUOTED.sub(" (quoted) ", _normalized(text))):
        sentence = sentence.strip()
        if not sentence or sentence.endswith("?") or _ATTRIBUTED.search(sentence):
            continue
        for part in _CLAUSE.split(sentence):
            clause = _BULLET.sub("", part).strip()
            if not clause:
                continue
            for check, pattern in patterns:
                if check in found:
                    continue
                if any(not _guarded(clause, m) for m in pattern.finditer(clause)):
                    found.add(check)
    return found


def find_problems(text: str) -> set[Check]:
    """The checks a Hannah reply fails (empty: it can be shown as it is)."""
    return _problems(text, PATTERNS)


def gateway_problem(text: str) -> GatewayCheck | None:
    """The first check an Ask HeroOS reply fails, by priority; None if it can be shown."""
    problems = _problems(text, GATEWAY_PATTERNS)
    return next((check for check in GATEWAY_PRIORITY if check in problems), None)


def review_reply(text: str) -> ReviewedReply:
    """The model's reply if no check fails; otherwise the fixed reply for the first failure."""
    problems = find_problems(text)
    for check in PRIORITY:
        if check in problems:
            return ReviewedReply(text=FALLBACKS[check], replaced_by=check)
    return ReviewedReply(text=text, replaced_by=None)
