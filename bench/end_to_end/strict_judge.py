"""Deterministic strict judge for LoCoMo flip-set re-judging.

V6.5/V6.6 audit: LLM judge gives different verdicts for essentially identical
answers across versions. This judge applies rule-based criteria:

  - Refusal answers ("no specific X", "cannot determine") FAIL when gold is concrete
  - Temporal: require date / relative-phrase match
  - Count: extract claimed number, must equal gold count
  - Named-entity: gold key token must appear (case-insensitive substring)
  - Descriptive: gold key noun (or curated synonym set) must appear

Per-qid acceptance criteria are defined explicitly for the 10 flip qids.
For other qids it falls back to gold-key-token substring matching.

Usage:
    python bench/end_to_end/strict_judge.py <result.json> [<result.json> ...]

Outputs: side-by-side table of original_correct vs strict_correct for the 10 qids.
"""
import json
import re
import sys
from dataclasses import dataclass
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Refusal markers (when present + gold is concrete → strict FAIL)
# ─────────────────────────────────────────────────────────────────────────────
REFUSAL_PATTERNS = [
    r"\bno specific\s+\w+\b",
    r"\bdo(?:es)? not specify\b",
    r"\bdid not specify\b",
    r"\bdo not\s+(?:specify|mention|state|name|identify)\b",
    r"\bare not\s+specified\b",
    r"\bnever (?:mentioned|specified|named|stated)\b",
    r"\bnot\s+(?:explicitly\s+)?(?:specified|mentioned|stated|named|provided)\b",
    r"\bcannot\s+(?:determine|identify|find|conclude|infer)\b",
    r"\bunable to\s+(?:determine|find|identify|conclude)\b",
    r"\binsufficient\s+(?:evidence|information|context|data)\b",
    r"\bno (?:concrete|explicit|exact|particular)\s+\w+",
    r"\bi (?:do not|don't)\s+(?:know|have|see)\b",
    r"\bnot enough\b",
    r"\bdoes not (?:specify|mention|state|name|provide)\b",
]


def has_refusal(answer: str) -> bool:
    """Refusal detection — apply ONLY to final answer segment, not reasoning."""
    a = answer.lower()
    for pat in REFUSAL_PATTERNS:
        if re.search(pat, a):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Final answer extraction
# ─────────────────────────────────────────────────────────────────────────────
def extract_final_answer(text: str) -> tuple[str, bool]:
    """Extract the committed final answer segment.

    Returns (segment, has_explicit_marker).
    If has_explicit_marker is False, the answer was truncated mid-reasoning;
    callers should fall back to body-match (lenient).
    """
    t = text
    # Try ANSWER: marker (most explicit)
    matches = list(re.finditer(r"\bANSWER\s*:\s*", t))
    # Filter out "SELECT THE BEST ANSWER" / step headers
    valid = []
    for m in matches:
        start = max(0, m.start() - 30)
        prefix = t[start:m.start()].lower()
        if "select the best" in prefix or "best answer" in prefix:
            continue
        valid.append(m)
    if valid:
        last = valid[-1]
        tail = t[last.end():].strip()
        end = tail.find("\n\n")
        if end > 0:
            tail = tail[:end]
        return tail.strip(), True

    # No explicit marker → answer truncated mid-reasoning
    return t, False


def _is_truncated_no_commit(ans: str) -> bool:
    """Detect if answer was truncated before reaching its final ANSWER: commit.

    Signals:
      - No explicit ANSWER: marker
      - Answer ends mid-word, mid-step header, or without sentence terminator
      - Answer length is at common bench cap (2000 chars exactly)
    """
    if not ans:
        return False
    a = ans.rstrip()
    # Has ANSWER: marker → not truncated-no-commit
    if re.search(r"\bANSWER\s*:\s*\S", a):
        return False
    # Ends with sentence terminator → likely complete
    if a[-1] in ".!?\"'":
        return False
    # Ends mid step header or mid word → truncated
    if re.search(r"(Step\s*\d+\s*:?[^\n]{0,40})$", a):
        return True
    # Length suspicious (close to 2000 cap)
    if 1990 <= len(ans) <= 2010:
        return True
    return True  # any other open-ended end


def _judge_with_fallback(
    ans: str,
    final_check,  # callable(final_seg) -> (bool, str)
    body_check,   # callable(full_body) -> (bool, str)
) -> tuple[bool, str]:
    """Apply final-segment rule if explicit ANSWER: marker exists.
    For truncated-without-commit answers, be conservative — default FAIL.
    """
    final, has_marker = extract_final_answer(ans)
    if has_marker:
        if has_refusal(final):
            return False, f"refusal in final | final={final[:80]!r}"
        return final_check(final)
    # No explicit ANSWER: — check if truncated
    if _is_truncated_no_commit(ans):
        # Conservative: try body check on LAST PARAGRAPH only, not full body
        last_para = ans.rsplit("\n\n", 1)[-1].strip()
        if has_refusal(last_para):
            return False, "refusal in last paragraph (truncated)"
        # Only PASS if gold token appears in the truncated tail's last paragraph
        # — falling back to body_check on full content overcounts evidence-listing mentions
        result = body_check(last_para)
        if result[0]:
            return True, result[1] + " (truncated, last-para match)"
        return False, "truncated without commit, gold not in last paragraph"
    # Complete answer but no ANSWER: marker (rare)
    last_para = ans.rsplit("\n\n", 1)[-1].strip()
    if has_refusal(last_para):
        return False, "refusal in last paragraph"
    return body_check(ans)


# ─────────────────────────────────────────────────────────────────────────────
# Date extraction
# ─────────────────────────────────────────────────────────────────────────────
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


@dataclass
class DateMatch:
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    relative_phrase: Optional[str] = None  # e.g. "a few years ago"


RELATIVE_PHRASES = [
    # "a few years (ago|before|earlier|back|prior)"
    r"\b(?:a )?few years (?:ago|before|earlier|back|prior)\b",
    r"\bseveral years (?:ago|before|earlier|back|prior)\b",
    r"\ba couple (?:of )?years (?:ago|before|earlier|back|prior)\b",
    r"\bsome years (?:ago|before|earlier|back|prior)\b",
    r"\b\w+ years (?:ago|before|earlier|back|prior)\b",
    r"\ba few months (?:ago|before|earlier|back|prior)\b",
    r"\blast year\b",
    r"\bthis year\b",
    r"\brecently\b",
]


def extract_dates(text: str) -> list[DateMatch]:
    """Extract date claims from text. Returns list (may be empty)."""
    out: list[DateMatch] = []
    t = text.lower()

    # Relative phrases first
    for pat in RELATIVE_PHRASES:
        m = re.search(pat, t)
        if m:
            out.append(DateMatch(relative_phrase=m.group(0)))

    # Month + year patterns: "August 4, 2023" / "September 2022" / "Feb 8, 2023"
    month_alt = "|".join(MONTHS.keys())
    pat_full = rf"\b({month_alt})\b\s*(\d{{1,2}})?,?\s*(\d{{4}})"
    for m in re.finditer(pat_full, t):
        month_name, day_str, year_str = m.group(1), m.group(2), m.group(3)
        out.append(DateMatch(
            year=int(year_str),
            month=MONTHS[month_name],
            day=int(day_str) if day_str else None,
        ))

    # YYYY-MM-DD format
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        out.append(DateMatch(
            year=int(m.group(1)),
            month=int(m.group(2)),
            day=int(m.group(3)),
        ))
    # Bare year-month "2022-09"
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})(?!-)\b", t):
        out.append(DateMatch(year=int(m.group(1)), month=int(m.group(2))))
    # MM/DD/YYYY format
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t):
        out.append(DateMatch(
            year=int(m.group(3)),
            month=int(m.group(1)),
            day=int(m.group(2)),
        ))

    return out


def dates_match(gold_dates: list[DateMatch], ans_dates: list[DateMatch]) -> bool:
    """Match: relative→relative, absolute→absolute (year+month required)."""
    if not gold_dates:
        return False
    for gd in gold_dates:
        if gd.relative_phrase:
            for ad in ans_dates:
                if ad.relative_phrase:
                    return True
        else:
            for ad in ans_dates:
                if ad.year == gd.year and ad.month == gd.month:
                    return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Number extraction (for count questions)
# ─────────────────────────────────────────────────────────────────────────────
NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def extract_count(text: str) -> Optional[int]:
    """Extract the committed count claim from a (final answer) segment.

    Skips: 4-digit years, dates (YYYY-MM-DD), "Step N" patterns.
    """
    t = text.lower()
    # Strip step headers / years / dates so we don't pick them as counts
    cleaned = re.sub(r"\bstep\s*\d+\b", " ", t)
    cleaned = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b", " ", cleaned)
    cleaned = re.sub(r"\b\d{4}\b", " ", cleaned)  # drop bare years

    # number words first (more reliable for committed answers)
    for word, v in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", cleaned):
            return v
    # ordinal words
    ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
    for word, v in ORDINALS.items():
        if re.search(rf"\b{word}\b", cleaned):
            return v
    # bare 1-2 digit numbers
    nums = re.findall(r"\b(\d{1,2})\b", cleaned)
    if nums:
        return int(nums[0])  # first surviving number
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Per-qid strict acceptance rules
# ─────────────────────────────────────────────────────────────────────────────
def _has_relative_phrase(text: str) -> tuple[bool, str]:
    """Accept if a relative phrase ('a few years ago' etc) is present.

    Absolute date alongside is OK — answer like 'a few years before February 2023'
    correctly anchors a relative claim, and gold='A few years ago' should match.
    """
    dates = extract_dates(text)
    has_rel = any(d.relative_phrase for d in dates)
    has_abs = any(d.year for d in dates)
    if has_rel:
        return True, "relative phrase present"
    if has_abs:
        return False, "absolute date only, gold is relative"
    return False, "no date indicator"


def judge_c1_gina(ans: str, gold: str) -> tuple[bool, str]:
    """c1: When did Gina get her tattoo? gold='A few years ago' (relative)."""
    def final_check(final):
        return _has_relative_phrase(final)

    def body_check(body):
        # Truncated: look at last 400 chars for committed claim
        return _has_relative_phrase(body[-400:])

    return _judge_with_fallback(ans, final_check, body_check)


_POS_FIN = [
    r"\bmiddle[\s-]?class\b", r"\bwealth\w*\b", r"\bwell[\s-]?off\b",
    r"\baffluent\b", r"\bupper[\s-]?class\b",
    r"\bcomfortable\b", r"\b(?<!un)stable\b", r"\bsecure\b", r"\bsolid\b",
]
_NEG_FIN = [
    r"\bstrain\w*\b", r"\bstruggl\w*\b", r"\bunemploy\w*\b",
    r"\bunstable\b", r"\binstab\w*\b",
    r"\bjob loss\b", r"\bbroke\b", r"\bpoor\b",
    r"\bfinanciall?y? (?:strain|stress|stretch|tight)\b",
]


def judge_c2_financial(ans: str, gold: str) -> tuple[bool, str]:
    """c2: John financial status. gold='Middle-class or wealthy'."""
    def check(text):
        t = text.lower()
        pos = any(re.search(p, t) for p in _POS_FIN)
        neg = any(re.search(p, t) for p in _NEG_FIN)
        if pos and not neg:
            return True, "positive financial indicator"
        if pos and neg:
            return False, "mixed (positive and negative)"
        if neg:
            return False, "answer claims financial strain"
        return False, "no positive financial indicator"

    return _judge_with_fallback(ans, check, check)


def judge_c2_maria(ans: str, gold: str) -> tuple[bool, str]:
    """c2: When did Maria take up community work? gold='August 4, 2023'."""
    gold_dates = extract_dates(gold)

    def check(text):
        if dates_match(gold_dates, extract_dates(text)):
            return True, "date match"
        return False, "no date match"

    return _judge_with_fallback(ans, check, check)


def judge_c3_count(ans: str, gold: str) -> tuple[bool, str]:
    """c3: How many writings made big screen? gold='two'."""
    gold_count = extract_count(gold)

    def final_check(final):
        c = extract_count(final)
        if c == gold_count:
            return True, f"count match (={gold_count})"
        return False, f"count mismatch (gold={gold_count}, final={c})"

    def body_check(body):
        # Look at commit-like phrasing in body
        # Check last 3 paragraphs for committed count
        last_paras = body.lower().rsplit("\n\n", 4)[-3:]
        last_chunk = "\n".join(last_paras)
        c = extract_count(last_chunk)
        if c == gold_count:
            return True, f"count match in body tail (={gold_count})"
        return False, f"count mismatch (gold={gold_count}, body tail={c})"

    return _judge_with_fallback(ans, final_check, body_check)


def judge_c3_tilly(ans: str, gold: str) -> tuple[bool, str]:
    """c3: What does Joanna do while she writes? gold='stuffed animal dog named Tilly'."""
    def check(text):
        if "tilly" in text.lower():
            return True, "Tilly present"
        return False, "Tilly absent"

    return _judge_with_fallback(ans, check, check)


def judge_c3_nate(ans: str, gold: str) -> tuple[bool, str]:
    """c3: What is Nate's favorite book series about? gold='dragons'."""
    def final_check(final):
        if "dragon" in final.lower():
            return True, "dragon(s) in final"
        return False, "dragons absent in final"

    def body_check(body):
        # Truncated: model's "best answer" direction is at the very tail.
        # Use last 300 chars to capture the committed direction, not earlier evidence.
        tail = body.lower()[-300:]
        if "dragon" in tail:
            return True, "dragon(s) in body tail-300"
        return False, "dragons absent in tail-300 (model heading other direction)"

    return _judge_with_fallback(ans, final_check, body_check)


def judge_c4_seattle(ans: str, gold: str) -> tuple[bool, str]:
    """c4: Which city? gold='Seattle'."""
    def check(text):
        if "seattle" in text.lower():
            return True, "Seattle present"
        return False, "Seattle absent"

    return _judge_with_fallback(ans, check, check)


def judge_c5_voyageurs(ans: str, gold: str) -> tuple[bool, str]:
    """c5: Which national park? gold='Voyageurs'."""
    def check(text):
        if "voyageur" in text.lower():
            return True, "Voyageurs present"
        return False, "Voyageurs absent"

    return _judge_with_fallback(ans, check, check)


def judge_c6_meeting(ans: str, gold: str) -> tuple[bool, str]:
    """c6: When did John plan his next meeting? gold='In September, 2022'."""
    gold_dates = extract_dates(gold)

    def check(text):
        if dates_match(gold_dates, extract_dates(text)):
            return True, "Sept 2022 match"
        return False, "no Sept 2022 match"

    return _judge_with_fallback(ans, check, check)


_DET_SYNONYMS = [
    r"\bdetermin\w*\b", r"\bpersever\w*\b", r"\bpersist\w*\b",
    r"\bresolve\b", r"\bresolution\b", r"\btenacit\w*\b",
    r"\bcommitment\b", r"\bdedicat\w*\b", r"\bgrit\b",
]


def judge_c9_calvin(ans: str, gold: str) -> tuple[bool, str]:
    """c9: gold='Hard work and determination'."""
    def final_check(final):
        f = final.lower()
        hw = "hard work" in f or "hard-work" in f
        det = any(re.search(p, f) for p in _DET_SYNONYMS)
        if hw and det:
            return True, "hard work + determination in final"
        if hw:
            return False, "hard work but no determination synonym"
        if det:
            return False, "determination but no hard work"
        return False, "neither in final"

    def body_check(body):
        # Body match: require both terms to appear in last 3 paragraphs (committed area)
        last = "\n".join(body.lower().rsplit("\n\n", 4)[-3:])
        hw = "hard work" in last or "hard-work" in last
        det = any(re.search(p, last) for p in _DET_SYNONYMS)
        if hw and det:
            return True, "hard work + determination in body tail"
        return False, "missing hard work or determination in body tail"

    return _judge_with_fallback(ans, final_check, body_check)


# Per-qid dispatch
STRICT_RULES = {
    "c1_69a7c9bffe": judge_c1_gina,
    "c2_29183ecb5e": judge_c2_financial,
    "c2_b4b43181aa": judge_c2_maria,
    "c3_2656e2c771": judge_c3_count,
    "c3_94f06e1a00": judge_c3_tilly,
    "c3_a9fddfe69b": judge_c3_nate,
    "c4_5cfba98ae8": judge_c4_seattle,
    "c5_dac00a436e": judge_c5_voyageurs,
    "c6_9da9f73c2a": judge_c6_meeting,
    "c9_5ab522b5c7": judge_c9_calvin,
}


def strict_judge(qid: str, q: str, gold: str, answer: str) -> tuple[bool, str]:
    """Apply per-qid strict rule. Returns (correct, reason)."""
    rule = STRICT_RULES.get(qid)
    if rule is None:
        # Generic fallback: gold key token must appear in answer, no refusal
        if has_refusal(answer):
            return False, "refusal (fallback)"
        gold_key = gold.lower().strip().rstrip(".")
        # take longest content word from gold as key
        words = [w for w in re.findall(r"\b[a-zA-Z]{4,}\b", gold_key)
                 if w not in {"the", "and", "with", "have", "from", "that", "this", "for"}]
        if not words:
            return False, "no gold key token (fallback)"
        for w in words:
            if w in answer.lower():
                return True, f"fallback: '{w}' present"
        return False, f"no gold token from {words} present (fallback)"
    return rule(answer, gold)


# ─────────────────────────────────────────────────────────────────────────────
# Main: re-judge JSON files side-by-side
# ─────────────────────────────────────────────────────────────────────────────
def rejudge(json_path: str) -> dict:
    """Re-judge a results JSON, return summary + per-qid records."""
    with open(json_path) as f:
        data = json.load(f)
    recs = {r["question_id"]: r for r in data["per_query"]}
    out = {"file": json_path, "per_qid": {}, "strict_correct": 0, "n": 0,
           "orig_correct": 0}
    for qid, rule in STRICT_RULES.items():
        r = recs.get(qid)
        if not r:
            continue
        sc, reason = strict_judge(qid, r["q"], r["gold"], r["answer"])
        out["per_qid"][qid] = {
            "orig": r["correct"],
            "strict": sc,
            "reason": reason,
            "q": r["q"],
            "gold": r["gold"],
            "ans_head": r["answer"][:120],
            "ans_tail": r["answer"][-200:],
        }
        out["strict_correct"] += int(sc)
        out["orig_correct"] += int(r["correct"])
        out["n"] += 1
    return out


def main():
    if len(sys.argv) < 2:
        print("Usage: strict_judge.py <result.json> [...]")
        sys.exit(1)
    results = [rejudge(p) for p in sys.argv[1:]]

    # Per-qid side-by-side table
    print()
    print("=" * 100)
    print("PER-QID STRICT vs ORIGINAL JUDGE")
    print("=" * 100)
    qids = list(STRICT_RULES.keys())
    header = f"{'qid':22s}  " + "  ".join(f"{r['file'].split('/')[-1][:22]:22s}" for r in results)
    print(header)
    print("-" * len(header))
    for qid in qids:
        row = f"{qid:22s}  "
        for r in results:
            p = r["per_qid"].get(qid)
            if not p:
                row += f"{'(n/a)':22s}  "
                continue
            o = "P" if p["orig"] else "F"
            s = "P" if p["strict"] else "F"
            flag = "*" if o != s else " "
            row += f"orig={o} strict={s}{flag}     "
        print(row)

    print()
    print("=" * 100)
    print("AGGREGATE")
    print("=" * 100)
    for r in results:
        name = r["file"].split("/")[-1]
        print(f"  {name:40s}  orig={r['orig_correct']}/{r['n']}  strict={r['strict_correct']}/{r['n']}")

    # Detail of disagreements
    print()
    print("=" * 100)
    print("DISAGREEMENTS (orig != strict)")
    print("=" * 100)
    for r in results:
        for qid, p in r["per_qid"].items():
            if p["orig"] != p["strict"]:
                print()
                print(f"[{r['file'].split('/')[-1]}]  {qid}")
                print(f"  Q:    {p['q']}")
                print(f"  GOLD: {p['gold']}")
                print(f"  ANS:  ...{p['ans_tail']}")
                print(f"  ORIG: {'PASS' if p['orig'] else 'FAIL'}")
                print(f"  STRICT: {'PASS' if p['strict'] else 'FAIL'}  reason={p['reason']}")


if __name__ == "__main__":
    main()
