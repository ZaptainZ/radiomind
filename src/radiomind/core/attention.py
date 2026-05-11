"""Query attention signature.

Every layer should answer: what is the attention focus? Rather than N
hardcoded booleans for fixed shapes, we compute one `AttentionSignature`
per query — a dict of hints that downstream modules use to decide
whether to route a query through their path.

The legacy list-of-tags API (`classify(query) -> list[str]`) is kept
for backward compatibility with callers that haven't migrated.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

_logger = logging.getLogger(__name__)


# --- Raw marker lists (used by both legacy classify and analyze) ---

AGGREGATION_MARKERS = (
    "how many", "how much", "total", "sum up", "count", "listed all",
    "list all", "list every", "enumerate", "across all", "across sessions",
    "how often", "how frequently", "in all", "altogether",
    "几个", "几条", "几次", "多少", "总共", "一共", "总和", "总数",
    "列出所有", "列举", "全部", "所有",
)

DISAMBIGUATION_MARKERS = (
    "previous", "former", "old", "original", "earlier",
    "current", "latest", "most recent", "now", "nowadays",
    "之前", "原来", "以前", "早先", "现在", "当前", "最近", "目前",
)

NARRATIVE_MARKERS = (
    "why did", "why do", "why was", "why were",
    "how did you feel", "how did it go", "trajectory",
    "thought process", "reasoning", "rationale",
    "what happened after", "what led to",
    "为什么", "怎么想的", "如何决定", "当时怎么", "心路历程",
)

COMPARISON_MARKERS = (
    "which is", "which was", "compare", "more than", "less than",
    "better than", "worse than", "versus", " vs ", "either",
    "比", "更", "相比", "哪个", "谁更", "哪一个",
)

LOOKUP_MARKERS = (
    "what is", "what was", "where is", "where did", "where was",
    "who is", "who was", "when did", "when was",
    "什么", "在哪", "哪儿", "是谁", "什么时候",
)

# Guard against aggregation false positives on temporal/duration phrasings.
_TEMPORAL_HOW_MANY = re.compile(
    r"how (?:many|much|long)\s+"
    r"(?:days?|weeks?|months?|years?|hours?|minutes?|seconds?|nights?|times?)"
    r"(?:\s+ago)?",
    re.IGNORECASE,
)
_HOW_LONG = re.compile(r"\bhow long\b", re.IGNORECASE)
_HOW_OFTEN = re.compile(r"\bhow often\b|\bhow frequently\b", re.IGNORECASE)

_CARDINAL_COUNT_RE = re.compile(
    r"\b(?:how\s+many|how\s+much|total|sum|count|altogether|in\s+all)\b",
    re.IGNORECASE,
)
_CARDINAL_CN_RE = re.compile(r"几(?:个|条|次|件|种|款|只|台|把|部)?|多少|总共|一共|总和|总数")

_TEMPORAL_RE = re.compile(
    r"\b(when|how\s+long|"
    r"for\s+how\s+many\s+(?:days|weeks|months|years)|"
    r"how\s+many\s+(?:days|weeks|months|years|hours|minutes|nights)\s+ago|"
    r"how\s+many\s+(?:days|weeks|months|years)\s+(?:passed|between|since|before|after|have))\b",
    re.IGNORECASE,
)
_OPEN_DOMAIN_RE = re.compile(
    r"\b(?:what|which|who)\b.*\b"
    r"(?:might|could|would|should|maybe|perhaps|likely|probably|possibly|"
    r"consider|enjoy|prefer|recommend|suggest)\b",
    re.IGNORECASE,
)
_SPECIFIC_DETAIL_RE = re.compile(
    r"\b(what|which|where)\s+(?:is|are|was|were|does|do|did|has|have)\s+"
    r"[a-z][a-z]+'?s?\b",
    re.IGNORECASE,
)

# Preference / advice queries — answer must anchor on user-specific
# context (tools, surfaces, prior experiences). Detection here lifts
# the regex out of mind.run_preference_context so the signal is part of
# the AttentionSignature and downstream layers (retrieval, prompt
# composition) can route off it.
_PREFERENCE_RE = re.compile(
    r"\b("
    r"any\s+tips|"
    r"do\s+you\s+think\s+.*\s+(?:good|bad|right|wise)\s+idea|"
    r"should\s+I\b|"
    r"recommend(?:ation)?|"
    r"what\s+should|how\s+(?:do|should)\s+I\b|"
    r"would\s+it\s+be\s+a\s+good|"
    r"can\s+you\s+(?:recommend|suggest|advise)|"
    r"give\s+me\s+(?:advice|tips|ideas)|"
    r"any\s+(?:advice|suggestions|ideas)|"
    r"what\s+(?:do|would)\s+you\s+(?:recommend|suggest)"
    r")\b",
    re.IGNORECASE,
)

# Temporal / scope constraint markers — second-order filter for
# aggregation queries. "Hikes I did on two consecutive weekends" should
# constrain the cardinal sum to the consecutive-weekend window, not all
# hikes ever. The exact window resolution happens downstream; here we
# only flag that a constraint is present.
_TEMPORAL_CONSTRAINT_RE = re.compile(
    r"\b("
    r"consecutive\s+(?:weekends?|days?|weeks?|months?)|"
    r"(?:two|three|four|five)\s+(?:weekends?|days?|weeks?|months?)\s+in\s+a\s+row|"
    r"between\s+\w+\s+and\s+\w+|"
    r"during\s+(?:my|the)\s+\w+|"
    r"in\s+(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)|"
    r"(?:last|past|previous|next)\s+(?:week|weekend|month|year|"
    r"\d+\s+days?|\d+\s+weeks?|\d+\s+months?)|"
    r"on\s+the\s+same\s+(?:day|weekend|trip)"
    r")\b",
    re.IGNORECASE,
)


# --- Focus entity extraction (shared) ---

_ENTITY_REGEXES = (
    re.compile(
        r"how much (?:did|do|have)\s+i\s+(?:\w+\s+){0,3}"
        r"(?:to|for|at|toward|towards|into|on)\s+"
        r"([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+){0,2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"how many (?:different |distinct |unique )?"
        r"([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+){0,2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"how much ([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+){0,2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"list (?:all |every |my )?"
        r"([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+){0,2})",
        re.IGNORECASE,
    ),
    re.compile(r"几个不同的?([^\s，。？]+)"),
    re.compile(r"多少([^\s，。？]+)"),
)

_FOCUS_TAIL_STOPWORDS = {
    "do", "did", "does", "have", "had", "has",
    "are", "were", "was", "is", "am",
    "i", "you", "we", "they", "he", "she", "it",
    "in", "on", "at", "to", "for", "by", "of", "with",
    "my", "your", "our", "their",
    "currently", "now", "already", "still", "also",
    "total", "all", "ever",
}


def extract_focus_entity(query: str) -> str | None:
    """Extract the noun phrase the query is asking about."""
    for pattern in _ENTITY_REGEXES:
        m = pattern.search(query)
        if not m:
            continue
        phrase = m.group(1).strip().lower()
        tokens = phrase.split()
        while tokens and tokens[-1] in _FOCUS_TAIL_STOPWORDS:
            tokens.pop()
        if tokens:
            return " ".join(tokens)
    return None


# --- Single analyze() — the primary API ---

@dataclass
class AttentionSignature:
    """One dict of hints per query; downstream routes off this.

    wants: query intent
      "count" / "date" / "detail" / "inference" / "lookup"

    answer_shape: the shape the *answer* should take (separate from wants
    because two count queries can expect number vs list; two date queries
    can expect absolute YYYY-MM-DD vs relative "N days ago"):
      "number"          — integer / scalar
      "amount"          — $X
      "absolute_date"   — YYYY-MM-DD style
      "relative_offset" — "N days ago", "3 weeks after X"
      "duration"        — "5 hours", "2 months"
      "named_entity"    — specific proper noun
      "list"            — enumeration
      "sentence"        — free text (default)

    aux_flags: orthogonal signals not captured by wants/shape
    (e.g. disambiguation, comparison).
    """
    focus: str | None
    wants: str
    aux_flags: dict[str, bool]
    answer_shape: str = "sentence"


# Answer-shape detectors — specific cues that a query expects a
# particular answer form beyond the generic wants bucket.
_RELATIVE_OFFSET_RE = re.compile(
    r"\b(?:how\s+long\s+(?:ago|since)|"
    r"how\s+many\s+(?:days?|weeks?|months?|years?|hours?)\s+ago|"
    r"\bago\b|\bsince\s+|\bbefore\s+|\bafter\s+)",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"\b(?:how\s+long\s+(?:did|does|have|had)|"
    r"for\s+how\s+(?:long|many)|"
    r"duration|how\s+much\s+time)\b",
    re.IGNORECASE,
)
_ABSOLUTE_DATE_RE = re.compile(r"\bwhen\s+(?:did|was|were|is|does)\b", re.IGNORECASE)
_AMOUNT_RE = re.compile(
    r"\bhow\s+much\s+(?:money|\$|did\s+i\s+(?:raise|donate|earn|save|spend|pay))"
    r"|\btotal\s+amount\b|\bhow\s+much\s+(?:in\s+total|altogether)",
    re.IGNORECASE,
)
_LIST_RE = re.compile(r"\blist\s+(?:all|every|the)\b", re.IGNORECASE)
_NAMED_ENTITY_RE = re.compile(
    r"\b(?:what\s+is\s+(?:the\s+)?name|which\s+\w+\s+(?:did|does)|who)\b",
    re.IGNORECASE,
)


def _answer_shape_for(query: str, wants: str) -> str:
    """Derive the answer-shape hint from query surface + wants bucket."""
    q = query or ""
    if wants == "count":
        if _AMOUNT_RE.search(q):
            return "amount"
        if _LIST_RE.search(q):
            return "list"
        return "number"
    if wants == "date":
        # Order matters: "how long ago" = relative_offset, not duration
        if _RELATIVE_OFFSET_RE.search(q):
            return "relative_offset"
        if _DURATION_RE.search(q):
            return "duration"
        if _ABSOLUTE_DATE_RE.search(q):
            return "absolute_date"
        return "relative_offset"  # temporal default is relative
    if wants == "inference":
        return "named_entity"
    if wants == "detail":
        if _NAMED_ENTITY_RE.search(q):
            return "named_entity"
        return "sentence"
    return "sentence"


def analyze(query: str) -> AttentionSignature:
    ql = (query or "").lower()

    # aggregation subset: count/total (must not be duration phrasing)
    is_agg = _is_aggregation(ql)
    wants_count = (
        is_agg and bool(_CARDINAL_COUNT_RE.search(query) or _CARDINAL_CN_RE.search(query))
    )

    # temporal precision
    wants_date = bool(_TEMPORAL_RE.search(query))

    # open-domain inference
    wants_inference = bool(_OPEN_DOMAIN_RE.search(query))

    # specific-detail lookup (only when not aggregation/narrative)
    wants_detail = (
        not is_agg
        and not any(m in ql for m in NARRATIVE_MARKERS)
        and bool(_SPECIFIC_DETAIL_RE.search(query))
    )

    # Pick dominant want. Order matters: count > date > inference > detail > lookup.
    # Multi-want queries pick one and record the others in aux_flags.
    if wants_count:
        wants = "count"
    elif wants_date:
        wants = "date"
    elif wants_inference:
        wants = "inference"
    elif wants_detail:
        wants = "detail"
    else:
        wants = "lookup"

    aux: dict[str, bool] = {}
    if any(m in ql for m in DISAMBIGUATION_MARKERS):
        aux["disambiguation"] = True
    if is_agg and not wants_count:
        aux["enumeration"] = True  # aggregation but not cardinal (list-all)
    if any(m in ql for m in COMPARISON_MARKERS):
        aux["comparison"] = True
    # Preference / advice anchoring (closes GAP-1: previously detected
    # only inside mind.run_preference_context via local regex; lifting
    # it here makes the signal visible to retrieval and any other layer
    # that wants to route differently for advice queries).
    if _PREFERENCE_RE.search(query or ""):
        aux["preference_anchor"] = True
    # Temporal / scope constraint (closes GAP-2: aggregation queries
    # like "hikes on two consecutive weekends" need a 2nd-order filter
    # at scope time, not just by entity_class).
    if _TEMPORAL_CONSTRAINT_RE.search(query or ""):
        aux["temporal_constraint"] = True

    return AttentionSignature(
        focus=extract_focus_entity(query),
        wants=wants,
        aux_flags=aux,
        answer_shape=_answer_shape_for(query, wants),
    )


def _is_aggregation(ql: str) -> bool:
    if not any(m in ql for m in AGGREGATION_MARKERS):
        return False
    if _HOW_OFTEN.search(ql):
        return True
    if _TEMPORAL_HOW_MANY.search(ql):
        return False
    if _HOW_LONG.search(ql):
        return False
    return True


# --- Backward-compat thin wrappers (keep old call sites green) ---

def classify(query: str) -> list[str]:
    sig = analyze(query)
    tags: list[str] = []
    if sig.wants == "count" or sig.aux_flags.get("enumeration"):
        tags.append("aggregation")
    if sig.aux_flags.get("disambiguation"):
        tags.append("disambiguation")
    if any(m in (query or "").lower() for m in NARRATIVE_MARKERS):
        tags.append("narrative")
    if sig.aux_flags.get("comparison"):
        tags.append("comparison")
    if not tags:
        tags.append("lookup")
    return tags


def is_aggregation(query: str) -> bool:
    sig = analyze(query)
    return sig.wants == "count" or sig.aux_flags.get("enumeration", False)


def is_disambiguation(query: str) -> bool:
    return analyze(query).aux_flags.get("disambiguation", False)


def is_numeric_cardinal(query: str) -> bool:
    return analyze(query).wants == "count"


def is_specific_detail_lookup(query: str) -> bool:
    return analyze(query).wants == "detail"


def is_temporal_precision(query: str) -> bool:
    return analyze(query).wants == "date"


def is_open_domain_specific(query: str) -> bool:
    return analyze(query).wants == "inference"


# --- V6.3-B: trinity-routed attention (普适性 fix) -------------------
#
# Background: regex-only `analyze()` classifies queries into wants ∈
# {count, date, inference, detail, lookup}. The lexical patterns are
# tuned on LongMemEval phrasings ("how many", "should I", "when did
# I"). LoCoMo / dialog queries with equivalent semantic intent but
# different surface form ("Which city is John excited about?" — what
# *city* attribute → entity-attribute lookup) fall to wants=lookup,
# the catch-all bucket with no specialized skill attached.
#
# `analyze_with_trinity(query, llm)` is a backward-compatible upgrade
# path: when llm is None, behaves exactly like `analyze()` (regex
# only). When llm is provided AND regex returned wants=lookup (the
# only "uncertain" bucket), three trinity stances independently judge
# the query from different cognitive angles and may upgrade wants to
# count / date / inference / detail / preference. Stance design
# (CORE_METHODOLOGY: dimension-typed naming) follows GAP-D / V6.1.1
# pattern.
#
# Robustness: V6.1.1's retry-consistency is reused — two trinity
# calls; trust only when both return the same wants. Inconsistent →
# fall back to regex result. Cost: only triggered when regex is
# uncertain; LongMemEval queries with high-confidence regex keep the
# 0-cost fast path.

# Valid `wants` categories the trinity may upgrade to. Must align
# with AttentionSignature.wants enum.
_TRINITY_UPGRADE_TARGETS = ("count", "date", "inference", "detail", "preference")


def _route_via_trinity_once(query: str, llm: Any) -> str | None:
    """Single trinity LLM call. Returns wants ∈ _TRINITY_UPGRADE_TARGETS,
    'lookup' (no upgrade), or None on parse / LLM failure."""
    from radiomind.refinement import trinity as _trinity
    result = _trinity.fast(
        task=(
            "Three independent stances analyze the query from different "
            "cognitive angles to determine what type of operation "
            "answering it requires:\n"
            "  literal-form    — analyze the grammatical/lexical form: "
            "is this a cardinal-count question (how many X), date-"
            "arithmetic (years between, since X), list/enumeration, "
            "attribute lookup (which X / what is Y's Z), preference "
            "advice (should I, recommend), or open-domain inference "
            "(what might X be)?\n"
            "  semantic-intent — what cognitive operation must the "
            "answerer perform: aggregate (sum/count/list), retrieve a "
            "specific entity attribute, infer a likely property, "
            "compute a temporal interval, give a personal recommendation?\n"
            "  answer-shape    — what shape will the correct answer "
            "take: an integer, a named entity, a date, a duration, a "
            "list, a sentence-form opinion?\n"
            "\n"
            "Output `wants` (lowercase, exactly one of: count / date / "
            "inference / detail / preference / lookup) reflecting the "
            "dominant cognitive operation across the three stances. "
            "Use 'lookup' only when no specialized category fits."
        ),
        evidence=f"Query: {query}",
        llm=llm,
        extra_schema='  "wants": str',
    )
    if not result:
        return None
    raw = result.get("wants")
    if not isinstance(raw, str):
        return None
    val = raw.strip().lower()
    if val in _TRINITY_UPGRADE_TARGETS or val == "lookup":
        return val
    return None


def analyze_with_trinity(
    query: str, llm: Any | None = None,
) -> AttentionSignature:
    """V6.3-B: regex-pass + trinity-fallback attention router.

    Behavior:
      1. Run regex `analyze()` first (V6.1.1-compatible).
      2. If llm is None OR regex locked a non-lookup wants
         (count/date/inference/detail), short-circuit and return
         the regex result. Zero LLM cost on confident classifications.
      3. If regex returned wants=lookup AND llm is provided, run
         trinity twice for retry-consistency. Both calls must agree
         on the upgraded wants for the upgrade to take effect. On
         inconsistency or parse failure, fall back to regex result
         (never worse than current behavior).

    The trinity prompt uses three dimension-typed stances
    (literal-form / semantic-intent / answer-shape) that look at
    the query from independent cognitive angles, mitigating regex
    bias toward LongMemEval phrasings.
    """
    base = analyze(query)
    if llm is None or base.wants != "lookup":
        return base

    # Trinity escalation only when regex returned lookup (no skill attached)
    idx1 = _route_via_trinity_once(query, llm)
    idx2 = _route_via_trinity_once(query, llm)

    decision = "abstain"
    upgraded_wants: str | None = None
    if idx1 is not None and idx1 == idx2:
        if idx1 in _TRINITY_UPGRADE_TARGETS:
            upgraded_wants = idx1
            decision = f"upgrade-to-{idx1}-consistent"
        else:
            decision = "no-upgrade-consistent-lookup"
    else:
        if idx1 is None and idx2 is None:
            decision = "abstain-both-parse-failed"
        elif idx1 != idx2:
            decision = f"abstain-inconsistent-{idx1}-vs-{idx2}"

    _logger.debug(
        "analyze_with_trinity: query=%r regex_wants=lookup idx1=%s idx2=%s decision=%s",
        query[:80], idx1, idx2, decision,
    )

    if upgraded_wants is None:
        return base

    # Construct upgraded signature: keep regex's focus + aux_flags;
    # update wants and recompute answer_shape based on new wants.
    return AttentionSignature(
        focus=base.focus,
        wants=upgraded_wants,
        aux_flags=base.aux_flags,
        answer_shape=_answer_shape_for(query, upgraded_wants),
    )


# --- V6.5: question-intent trinity (题干侧拆解) ---------------------
#
# Background: V6.3-B applied trinity on the question-side ROUTING
# decision (which wants bucket), but NOT on the deeper question
# understanding (granularity / answer form / latent intent). V6.3
# fails clustered as "abstract vs literal granularity mismatch"
# (LoCoMo c3_a9fddfe69b "Nate's favorite book series ABOUT?"
# gold=dragons but LLM answers book name) — the LLM never gets
# told the question wants a THEME, not a TITLE.
#
# V6.5 design — flexible trinity (NOT hardcoded 3 stances):
#   - STANCE_LIBRARY: dict of candidate stance dimensions; each entry
#     has a description and a trigger lambda. New stances → just
#     add a library entry, no main-flow change.
#   - _select_intent_stances(query, base_sig): pick stances dynamically
#     based on query features. Base 2 stances (literal + semantic)
#     always; +granularity / direction / entity-type / temporal-precision
#     as triggers fire. Result: 2-5 stances per query, sized to
#     question complexity.
#   - trinity.debate(n_stances=K) reused with retry-consistency +
#     abstain pattern (V6.1.1).
#   - Output: QuestionIntent (structured signature; NOT prose) →
#     downstream answer prompt adds form-constraint note.
#
# CRITICAL avoid-V6.4-B-self-pollution: QuestionIntent is a
# STRUCTURED signature (5 short fields), not a free-form profile.
# It tells the answer LLM "the question wants TOPIC, not TITLE";
# it does NOT tell the answer LLM "the answer might be X". The
# generator/consumer LLM sessions stay separate via the structural
# barrier of the signature.

@dataclass
class QuestionIntent:
    """V6.5: structured intent signature derived from question-side
    trinity. Conditions the answer prompt with granularity / form /
    direction hints. NOT a candidate answer — strictly a question
    decomposition.
    """
    literal_target: str        # what the query syntactically asks
    semantic_target: str       # what the user truly asks
    expected_granularity: str  # specific_entity / category / concept / direction / description
    answer_form: str           # name / topic / judgment / list / duration / date / sentence
    focus_entity_type: str | None  # entity type if applicable, else None
    stances_used: tuple[str, ...] = ()  # which dimensions fired (for telemetry)


# Stance library. Each entry: description for prompt + trigger
# predicate that decides whether to include the stance for a given
# query. New stances → add an entry; main flow unchanged.
def _trigger_always(ql: str, sig) -> bool:
    return True


def _trigger_granularity(ql: str, sig) -> bool:
    markers = ("about", "kind of", "type of", "series", "category",
               "what does", "what do", "what is")
    return any(m in ql for m in markers)


def _trigger_direction(ql: str, sig) -> bool:
    markers = ("status", "level", "condition", "might be", "is likely",
               "would be", "could be")
    return any(m in ql for m in markers)


def _trigger_entity_type(ql: str, sig) -> bool:
    return ql.startswith(("which ", "who ", "where "))


def _trigger_temporal_precision(ql: str, sig) -> bool:
    return sig.wants == "date" or "when " in ql or "how long" in ql


def _trigger_complex_inference(ql: str, sig) -> bool:
    markers = ("might", "could", "should", "would", "consider", "likely")
    word_count = len(ql.split())
    return word_count >= 10 and any(m in ql for m in markers)


_STANCE_LIBRARY: dict[str, dict] = {
    "literal-target": {
        "desc": (
            "literal-target — what does the query ASK syntactically? "
            "(subject + verb + object slot; ignore inferred intent)"
        ),
        "trigger": _trigger_always,
    },
    "semantic-target": {
        "desc": (
            "semantic-target — what is the user TRULY asking semantically? "
            "(the latent intent that an experienced reader would infer; "
            "may differ from the syntactic slot)"
        ),
        "trigger": _trigger_always,
    },
    "granularity-check": {
        "desc": (
            "granularity-check — does the user expect a SPECIFIC instance, "
            "a CATEGORY, a CONCEPT, or a THEME? 'about' / 'kind of' / "
            "'type of' / 'series about X' signal THEME or CATEGORY, not "
            "the specific item. 'What is X about' wants the THEME."
        ),
        "trigger": _trigger_granularity,
    },
    "direction-check": {
        "desc": (
            "direction-check — does the user expect a JUDGMENT direction "
            "(positive/negative, high/low, sufficient/insufficient) "
            "rather than a verbose description? 'might X's status be' / "
            "'how is X' wants a directional verdict."
        ),
        "trigger": _trigger_direction,
    },
    "entity-type-check": {
        "desc": (
            "entity-type-check — if the question expects an entity, what "
            "TYPE is it (person / location / company / dish / event / "
            "object)? Pin the type so retrieval and answer can target it."
        ),
        "trigger": _trigger_entity_type,
    },
    "temporal-precision-check": {
        "desc": (
            "temporal-precision-check — does the user expect EXACT date / "
            "approximate period / duration / relative offset? 'When did X' "
            "= exact; 'how long ago' = duration; 'around when' = approximate."
        ),
        "trigger": _trigger_temporal_precision,
    },
    "complex-inference-check": {
        "desc": (
            "complex-inference-check — does the question require "
            "multi-step or counterfactual inference (might / could / "
            "would have)? If yes, the answer may need explicit bridging."
        ),
        "trigger": _trigger_complex_inference,
    },
}


def _select_intent_stances(query: str, base_sig: AttentionSignature) -> list[str]:
    """Choose which intent stances apply to this query. 2-5 stances."""
    ql = (query or "").lower()
    selected: list[str] = []
    for name, entry in _STANCE_LIBRARY.items():
        if entry["trigger"](ql, base_sig):
            selected.append(name)
    # Hard cap at 5 to keep prompt focused; literal + semantic are always
    # included by _trigger_always so they take the first two slots.
    return selected[:5]


def _intent_trinity_once(
    query: str, base_sig: AttentionSignature,
    stances: list[str], llm: Any,
) -> QuestionIntent | None:
    """Single trinity LLM call. Returns parsed QuestionIntent or None."""
    from radiomind.refinement import trinity as _trinity
    dim_lines = []
    for name in stances:
        entry = _STANCE_LIBRARY.get(name)
        if entry:
            dim_lines.append(f"  {entry['desc']}")
    dim_block = "\n".join(dim_lines)
    task = (
        f"Multiple stances analyze this question from different intent "
        f"angles. Each stance examines a different dimension:\n"
        f"{dim_block}\n"
        f"\n"
        f"Synthesize the stances into a structured intent signature. "
        f"Be PRECISE on `expected_granularity` and `answer_form`: these "
        f"are downstream constraints on the answer LLM. If 'about' / "
        f"'kind of' is present, granularity should typically be "
        f"`category` or `concept`, NOT `specific_entity`.\n"
        f"\n"
        f"Question: {query}"
    )
    schema = (
        '  "literal_target": str,           '
        '  "semantic_target": str,          '
        '  "expected_granularity": str  (specific_entity | category | '
        'concept | direction | description),  '
        '  "answer_form": str  (name | topic | judgment | list | '
        'duration | date | sentence),  '
        '  "focus_entity_type": str | null'
    )
    result = _trinity.debate(
        task=task,
        evidence=f"(question-only analysis; no memory evidence needed)\n{query}",
        llm=llm,
        extra_schema=schema,
        n_stances=len(stances),
        max_rounds=1,
    )
    if not result:
        return None
    try:
        return QuestionIntent(
            literal_target=str(result.get("literal_target") or "").strip(),
            semantic_target=str(result.get("semantic_target") or "").strip(),
            expected_granularity=str(result.get("expected_granularity") or "").strip().lower(),
            answer_form=str(result.get("answer_form") or "").strip().lower(),
            focus_entity_type=(
                str(result.get("focus_entity_type")).strip()
                if result.get("focus_entity_type") not in (None, "null", "")
                else None
            ),
            stances_used=tuple(stances),
        )
    except (TypeError, ValueError, AttributeError):
        return None


def analyze_question_intent_with_trinity(
    query: str, llm: Any | None = None,
) -> QuestionIntent | None:
    """V6.5: question-side trinity for intent decomposition.

    Picks a query-specific set of stances from _STANCE_LIBRARY (2-5
    based on query features), runs trinity twice (retry-consistency),
    returns QuestionIntent on agreement.

    Returns None when:
      - llm unavailable
      - trinity inconsistent or parse failure
      - both calls abstain

    Callers should treat None as "no intent override" — fall back to
    pre-V6.5 behavior. Never make the answer prompt rely on a non-null
    return.
    """
    if llm is None or not getattr(llm, "is_available", lambda: True)():
        return None
    base_sig = analyze(query)
    stances = _select_intent_stances(query, base_sig)
    if len(stances) < 2:  # defensive; literal+semantic should always trigger
        return None

    intent1 = _intent_trinity_once(query, base_sig, stances, llm)
    intent2 = _intent_trinity_once(query, base_sig, stances, llm)

    decision = "abstain"
    out: QuestionIntent | None = None
    if intent1 is not None and intent2 is not None:
        # Trust only when both calls agree on the load-bearing fields:
        # expected_granularity AND answer_form. The narrative fields
        # (literal_target / semantic_target) can vary in phrasing.
        if (intent1.expected_granularity == intent2.expected_granularity
                and intent1.answer_form == intent2.answer_form):
            decision = "consistent"
            out = intent1
        else:
            decision = (
                f"inconsistent-granularity-{intent1.expected_granularity}-vs-"
                f"{intent2.expected_granularity}"
            )
    elif intent1 is None and intent2 is None:
        decision = "both-parse-failed"
    else:
        decision = "one-parse-failed"

    _logger.debug(
        "analyze_question_intent_with_trinity: query=%r stances=%s "
        "decision=%s gran=%s form=%s",
        query[:80], stances, decision,
        getattr(out, "expected_granularity", None),
        getattr(out, "answer_form", None),
    )
    return out


# --- V6.5 helper: format an intent into a prompt directive --------

def format_intent_directive(intent: QuestionIntent | None) -> str:
    """Render a QuestionIntent into a one-paragraph prompt directive.

    Returned string can be prepended to the answer prompt to bias the
    answer LLM toward the right granularity / form. Returns "" when
    intent is None or carries no non-default information.
    """
    if intent is None:
        return ""
    parts = []
    gran = (intent.expected_granularity or "").lower()
    form = (intent.answer_form or "").lower()
    if gran == "category":
        parts.append(
            "the question expects a CATEGORY-level answer (the kind/type "
            "of the thing), not a specific instance"
        )
    elif gran == "concept":
        parts.append(
            "the question expects a CONCEPT or THEME, not a specific item "
            "or proper noun"
        )
    elif gran == "direction":
        parts.append(
            "the question expects a JUDGMENT DIRECTION (e.g. high/low, "
            "positive/negative, sufficient/insufficient), not a verbose "
            "description"
        )
    if form == "topic":
        parts.append("answer should be the TOPIC the thing is about")
    elif form == "judgment":
        parts.append("answer should be the JUDGMENT VERDICT, brief")
    elif form == "list":
        parts.append("answer should be a LIST of distinct items")
    if not parts:
        return ""
    return (
        "QUESTION INTENT (V6.5 trinity-derived; honor this granularity):\n"
        "  " + "; ".join(parts) + "\n\n"
    )
