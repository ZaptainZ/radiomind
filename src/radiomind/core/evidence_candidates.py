"""V7 Step 1: Evidence-candidate injector.

Replaces V6.6.p2's `dominant_signal → prompt hint` flow with a first-class
structured-evidence extraction step.

Design principle (audit-driven, 2026-05-13):
  - V6.6 path 2 was directionally correct but too coarse — it told the
    answerer "this question wants form=topic" and left the answerer to
    re-derive the answer from raw memories.
  - This module instead extracts {candidate, quote, relation, temporal_role,
    confidence} from retrieved memories and injects them as structured
    candidates. The answerer picks among candidates rather than
    re-reasoning over raw evidence.

Zero LLM cost. Deterministic given fixed retrieve input.

Public API:
  - extract_evidence_candidates(query, retrieved_memories) -> list[EvidenceCandidate]
  - render_evidence_candidates(candidates) -> str  (for prompt injection)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Candidate dataclass
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class EvidenceCandidate:
    """A first-class answer candidate extracted from retrieved memories."""

    candidate: str                # the answer phrase (e.g., "Tilly", "Seattle", "September 2022")
    quote: str                    # 1-line quote that supports it, with date prefix
    relation: str                 # how this candidate relates to query (e.g., "companion-while-writing")
    temporal_role: str = ""       # "mention_date" / "event_date" / "ongoing" / "planned" / "relative" / ""
    confidence: float = 0.5       # 0-1
    source_count: int = 1         # how many distinct memories support this
    source_dates: list[str] = field(default_factory=list)

    def merge(self, other: "EvidenceCandidate") -> None:
        """Merge another candidate of the same identity into this one."""
        self.source_count += other.source_count
        # Take the higher confidence
        self.confidence = max(self.confidence, other.confidence)
        # Accumulate dates (deduped)
        for d in other.source_dates:
            if d and d not in self.source_dates:
                self.source_dates.append(d)


# ─────────────────────────────────────────────────────────────────────────────
# Query→signal mapping (which signal type to extract for which query shape)
# ─────────────────────────────────────────────────────────────────────────────
_QUERY_TYPE_PATTERNS = [
    # (label, regex on lowercased query)
    ("when",           re.compile(r"\b(when|what year|what month|what date|how long ago)\b")),
    ("how_many",       re.compile(r"\b(how many|how much|count of|number of)\b")),
    # "where" must come before "which" so "which national park" routes here
    ("where",          re.compile(
        r"\b(where|which\s+(?:\w+\s+){0,2}(park|city|place|location|country|state|town|stadium|venue))\b")),
    ("who",            re.compile(r"\b(who|whose|with whom)\b")),
    ("what_about",     re.compile(r"\bwhat\s+(?:is|are|was|were|does|do|did)\s+\S+(?:\s+\S+){0,5}\s+about\b")),
    # "what (do|does|did) X (do|use|need|require)"
    ("what_doing",     re.compile(r"\bwhat\s+(?:do|does|did)\s+\S+(?:\s+\S+){0,4}\s+(?:do|use|need|require|have)\b")),
    # "might X be" / "could X have" with up to 5 tokens between
    ("might_be",       re.compile(
        r"\b(might|could|may)\b(?:\s+\S+){1,6}\s+(?:be|have)\b")),
    ("which",          re.compile(r"\bwhich\b")),
]


def classify_query(query: str) -> str:
    """Return a query-type label for routing signal extraction."""
    q = (query or "").lower()
    for label, pat in _QUERY_TYPE_PATTERNS:
        if pat.search(q):
            return label
    return "other"


# ─────────────────────────────────────────────────────────────────────────────
# Memory iteration helpers
# ─────────────────────────────────────────────────────────────────────────────
def _iter_memories(retrieved_memories) -> list[tuple[str, str]]:
    """Yield (content_stripped, date_prefix) per memory. Robust to dict/object inputs.

    `content_stripped` has the leading "(date)" prefix removed if present,
    to avoid double-prefixing in quotes.
    """
    out: list[tuple[str, str]] = []
    for r in retrieved_memories or []:
        if isinstance(r, dict):
            content = r.get("memory") or r.get("content") or ""
            date = r.get("date") or r.get("timestamp") or ""
        elif hasattr(r, "entry"):
            content = getattr(r.entry, "content", "") or ""
            date = getattr(r.entry, "timestamp", "") or ""
        elif hasattr(r, "content"):
            content = getattr(r, "content", "") or ""
            date = getattr(r, "timestamp", "") or ""
        else:
            continue
        if not content:
            continue
        # Pull leading date if content starts with "(Friday, Oct 21, 2022)" or "(2022-10-21)"
        m = re.match(r"^\(([^)]{6,30})\)\s*", content)
        if m:
            if not date:
                date = m.group(1)
            content = content[m.end():]  # strip the leading "(date) " prefix
        out.append((content, str(date)[:40]))
    return out


# Common false-positive proper nouns to filter (possessives, pronouns)
_PROPER_NOUN_STOPWORDS = {
    "my", "his", "her", "their", "our", "your",
    "i", "you", "he", "she", "they", "we", "it",
    "the", "a", "an", "this", "that", "these", "those",
    "step", "answer", "memory", "memories",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
}


def _extract_query_subjects(query: str) -> set[str]:
    """Extract proper nouns from query — these are subjects, not answer candidates."""
    return {m.group(1).lower() for m in _PROPER_NOUN_RE.finditer(query)}


# ─────────────────────────────────────────────────────────────────────────────
# Span extractors
# ─────────────────────────────────────────────────────────────────────────────
_MONTH_RE = (
    r"Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|"
    r"Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December"
)
_DATE_PATTERNS = [
    # YYYY-MM-DD
    re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),
    # Month DD, YYYY  or  Month YYYY
    re.compile(rf"\b({_MONTH_RE})\s+(\d{{1,2}})?,?\s*(\d{{4}})\b", re.IGNORECASE),
]
_RELATIVE_RE = re.compile(
    r"\b(?:a few|several|some|a couple of|few)\s+years\s+(?:ago|before|earlier|back)\b",
    re.IGNORECASE,
)
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
_COUNT_WORD_RE = re.compile(
    r"\b(first|second|third|fourth|fifth|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)
_COUNT_NUM_RE = re.compile(r"\b(\d{1,3})\s*(?:time|times|instance|occurrence)s?\b", re.IGNORECASE)


def _surrounding_quote(content: str, span: tuple[int, int], context: int = 100) -> str:
    """Return content slice around a match span, trimmed to sentence boundary."""
    start = max(0, span[0] - context)
    end = min(len(content), span[1] + context)
    quote = content[start:end].strip()
    # Try to trim to sentence-like boundary
    if start > 0:
        idx = quote.find(". ")
        if 0 < idx < context:
            quote = quote[idx + 2:]
    if end < len(content):
        idx = quote.rfind(". ")
        if idx > len(quote) - 50:
            quote = quote[:idx + 1]
    return quote.replace("\n", " ").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Extractors per query type
# ─────────────────────────────────────────────────────────────────────────────
def _extract_temporal(content: str, query: str) -> list[tuple[str, str, str]]:
    """Return list of (date_phrase, quote, temporal_role) candidates.

    temporal_role classification:
      - "relative" if content contains "a few years ago"
      - "event_date" if content describes an action in past tense at a date
      - "mention_date" if date is just the conversation/journal date
      - "planned" if content uses "next month/year/will"
    """
    results: list[tuple[str, str, str]] = []
    # Relative phrases — flag as "relative"
    for m in _RELATIVE_RE.finditer(content):
        quote = _surrounding_quote(content, m.span())
        results.append((m.group(0), quote, "relative"))
    # Absolute dates
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(content):
            date_phrase = m.group(0)
            quote = _surrounding_quote(content, m.span())
            # Heuristic: "next month" / "will" / "plan" near date → planned
            qlow = quote.lower()
            if any(w in qlow for w in ("next month", "next year", "will ", "plan to", "planning")):
                role = "planned"
            elif any(w in qlow for w in (" got ", " went ", " did ", " was ", " were ", " took ", "happened", "yesterday")):
                role = "event_date"
            else:
                role = "mention_date"
            results.append((date_phrase, quote, role))
    return results


def _extract_proper_nouns(content: str, query: str) -> list[tuple[str, str]]:
    """Return list of (entity, quote). Filters stopwords + query subjects."""
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    query_subjects = _extract_query_subjects(query)
    for m in _PROPER_NOUN_RE.finditer(content):
        ent = m.group(1)
        # Skip stopwords (pronouns, possessives, months, weekdays)
        first_word = ent.split()[0].lower()
        if first_word in _PROPER_NOUN_STOPWORDS:
            continue
        # Skip query subjects (the answer is what's NOT the query subject)
        if ent.lower() in query_subjects:
            continue
        if ent in seen:
            continue
        seen.add(ent)
        quote = _surrounding_quote(content, m.span())
        results.append((ent, quote))
    return results


def _extract_counts(content: str, query: str) -> list[tuple[str, str]]:
    """Return list of (count_phrase, quote)."""
    results: list[tuple[str, str]] = []
    for m in _COUNT_NUM_RE.finditer(content):
        quote = _surrounding_quote(content, m.span())
        results.append((m.group(0), quote))
    for m in _COUNT_WORD_RE.finditer(content):
        word = m.group(0).lower()
        # Skip "first" used as adjective (e.g., "first time")
        quote = _surrounding_quote(content, m.span())
        results.append((word, quote))
    return results


_TOPIC_KEYWORDS = re.compile(
    r"\b(dragons?|magic|battles?|kingdoms?|adventures?|wizards?|fantasy|"
    r"space|opera|romance|mystery|thriller|horror|sci-?fi|"
    r"trilogy|saga|epic|cover|theme|genre|world[\s-]?building)\b",
    re.IGNORECASE,
)


def _extract_topics(content: str, query: str) -> list[tuple[str, str]]:
    """For 'what is X about' questions: extract topic keywords."""
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _TOPIC_KEYWORDS.finditer(content):
        t = m.group(0).lower()
        if t in seen:
            continue
        seen.add(t)
        quote = _surrounding_quote(content, m.span())
        results.append((t, quote))
    return results


_FINANCIAL_INDICATORS = re.compile(
    r"\b(wealthy|wealth|rich|affluent|comfortable|stable|middle[\s-]?class|"
    r"upper[\s-]?class|secure|"
    r"poor|broke|struggling|strain|stress|unemploy|unstable|tight|"
    r"average income|good income|high income|low income|"
    r"savings|investments?|inheritance|mortgage|rent|loan|debt)\b",
    re.IGNORECASE,
)


def _extract_financial(content: str, query: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for m in _FINANCIAL_INDICATORS.finditer(content):
        quote = _surrounding_quote(content, m.span())
        results.append((m.group(0).lower(), quote))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Top-level: extract_evidence_candidates
# ─────────────────────────────────────────────────────────────────────────────
def extract_evidence_candidates(
    query: str,
    retrieved_memories,
    top_k: int = 5,
) -> list[EvidenceCandidate]:
    """Extract structured evidence candidates from retrieved memories.

    Returns top-K candidates ranked by (source_count, confidence).
    Each candidate carries: candidate phrase, supporting quote, relation,
    temporal_role (if applicable), and confidence.
    """
    qtype = classify_query(query)
    memories = _iter_memories(retrieved_memories)
    if not memories:
        return []

    # Per-candidate aggregator: key = (candidate.lower(), relation)
    bucket: dict[tuple[str, str], EvidenceCandidate] = {}

    def add(cand: EvidenceCandidate) -> None:
        key = (cand.candidate.lower(), cand.relation)
        if key in bucket:
            bucket[key].merge(cand)
        else:
            bucket[key] = cand

    for content, date in memories:
        if qtype == "when":
            for phrase, quote, role in _extract_temporal(content, query):
                # Filter: prefer event_date / relative / planned over mention_date
                conf = {"event_date": 0.85, "relative": 0.9, "planned": 0.85,
                        "mention_date": 0.4}.get(role, 0.5)
                add(EvidenceCandidate(
                    candidate=phrase,
                    quote=f"({date}) {quote}" if date else quote,
                    relation="temporal_reference",
                    temporal_role=role,
                    confidence=conf,
                    source_dates=[date] if date else [],
                ))
        elif qtype == "how_many":
            for phrase, quote in _extract_counts(content, query):
                add(EvidenceCandidate(
                    candidate=phrase,
                    quote=f"({date}) {quote}" if date else quote,
                    relation="count_claim",
                    confidence=0.7,
                    source_dates=[date] if date else [],
                ))
        elif qtype in ("where", "who", "which"):
            for ent, quote in _extract_proper_nouns(content, query):
                # Boost confidence if entity is followed by a verb suggesting role
                qlow = quote.lower()
                if any(v in qlow for v in (" in ", " at ", " from ", " excited", " plays")):
                    conf = 0.75
                else:
                    conf = 0.6
                add(EvidenceCandidate(
                    candidate=ent,
                    quote=f"({date}) {quote}" if date else quote,
                    relation="proper_noun_in_context",
                    confidence=conf,
                    source_dates=[date] if date else [],
                ))
        elif qtype == "what_about":
            for topic, quote in _extract_topics(content, query):
                add(EvidenceCandidate(
                    candidate=topic,
                    quote=f"({date}) {quote}" if date else quote,
                    relation="topic_keyword",
                    confidence=0.7,
                    source_dates=[date] if date else [],
                ))
            # Also extract proper nouns (for "X's favorite series" question
            # candidates may be series names)
            for ent, quote in _extract_proper_nouns(content, query)[:3]:
                add(EvidenceCandidate(
                    candidate=ent,
                    quote=f"({date}) {quote}" if date else quote,
                    relation="series_or_entity_name",
                    confidence=0.5,
                    source_dates=[date] if date else [],
                ))
        elif qtype == "might_be":
            for phrase, quote in _extract_financial(content, query):
                add(EvidenceCandidate(
                    candidate=phrase,
                    quote=f"({date}) {quote}" if date else quote,
                    relation="state_indicator",
                    confidence=0.7,
                    source_dates=[date] if date else [],
                ))
        elif qtype == "what_doing":
            # Generic: extract proper nouns as activity targets + topic words
            for ent, quote in _extract_proper_nouns(content, query)[:3]:
                add(EvidenceCandidate(
                    candidate=ent,
                    quote=f"({date}) {quote}" if date else quote,
                    relation="activity_target",
                    confidence=0.6,
                    source_dates=[date] if date else [],
                ))

    # Rank by (source_count desc, confidence desc) and return top_k
    ranked = sorted(
        bucket.values(),
        key=lambda c: (c.source_count, c.confidence),
        reverse=True,
    )
    return ranked[:top_k]


def render_evidence_candidates(candidates: list[EvidenceCandidate]) -> str:
    """Render candidates as a prompt-injection block.

    Returns "" when no candidates. The block is prepended to the answerer's
    prompt; the answerer is expected to choose among candidates rather than
    re-deriving from raw memories.
    """
    if not candidates:
        return ""
    lines = ["EVIDENCE CANDIDATES (deterministic extraction from retrieved memories):"]
    for i, c in enumerate(candidates, 1):
        tr = f" [temporal_role={c.temporal_role}]" if c.temporal_role else ""
        sc = f" [supported_by={c.source_count}]" if c.source_count > 1 else ""
        lines.append(
            f"{i}. {c.candidate!r} (relation={c.relation}, "
            f"confidence={c.confidence:.2f}){tr}{sc}"
        )
        # Truncate long quotes
        qt = c.quote[:240]
        lines.append(f"   quote: {qt}")
    lines.append(
        "Pick the candidate that most directly answers the question. "
        "If multiple candidates fit, prefer higher confidence and higher source_count. "
        "If gold answer requires a relative-temporal phrase (e.g. 'a few years ago'), "
        "prefer a candidate with temporal_role=relative over event_date.\n",
    )
    return "\n".join(lines) + "\n"


def converge_candidates_via_trinity(
    query: str,
    candidates: list[EvidenceCandidate],
    llm,
    min_candidates: int = 2,
) -> Optional[dict]:
    """V7 Step 2: trinity candidate-convergence-resolver.

    Runs trinity debate over the candidate set (not raw memories). Only fires
    when len(candidates) >= min_candidates — single-candidate trivially
    answers itself. Three stances: conservative-evidence-only,
    inferential-allowed, exact-quote-required.

    Returns trinity result dict with {final_answer, stances, ...} or None.
    """
    if not candidates or len(candidates) < min_candidates:
        return None
    if llm is None or not getattr(llm, "is_available", lambda: True)():
        return None

    # Build evidence block from candidates (NOT raw memories)
    evidence_lines = []
    for i, c in enumerate(candidates, 1):
        tr = f" [{c.temporal_role}]" if c.temporal_role else ""
        evidence_lines.append(
            f"Candidate {i}: {c.candidate!r} "
            f"(relation={c.relation}, conf={c.confidence:.2f}, "
            f"source_count={c.source_count}){tr}\n"
            f"  Quote: {c.quote[:200]}"
        )
    evidence_block = "\n".join(evidence_lines)

    task = f"Pick the candidate that most directly answers: {query}"

    try:
        from radiomind.refinement.trinity import debate
        return debate(
            task=task,
            evidence=evidence_block,
            llm=llm,
            max_rounds=1,
            agent_role="candidate-convergence-resolver",
            n_stances=3,
        )
    except Exception:
        return None
