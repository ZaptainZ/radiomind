"""V7 Step 3 (subset): ingest-time temporal role tagging.

Audit insight (2026-05-13):
  c1 Gina "When did Gina get her tattoo?" — LoCoMo memory says
  "(2023-02-08) Got the tattoo a few years ago, ..."  The LLM saw the
  date 2023-02-08 and committed it as the event date, but 2023-02-08 is
  the MENTION date (when the user discussed the tattoo). The actual
  event happened "a few years ago" relative to 2023-02-08.

  This module pre-annotates memories at ingest time with a
  `temporal_role` field distinguishing:
    - mention_date: the date when the content was uttered (default)
    - event_date: a date that names when an event happened
    - relative_marker: presence of a relative-temporal expression
                      ("a few years ago", "last year")
    - planned_date: a date mentioned as a future plan ("next month")

  Detection is regex-only (zero LLM cost). evidence_candidates.py reads
  these tags at query time to render candidates with provenance.

  Scope: ONLY the relative-marker case (V7 Step 3 subset). Full
  mention/event/planned classification needs LLM-level NER per turn,
  which is out of scope here. The goal is to nail the c1 Gina case.
"""
from __future__ import annotations

import re
from typing import Optional


# Relative-temporal markers ("a few years ago", "several months back")
_RELATIVE_MARKER_RE = re.compile(
    r"\b(?:a few|several|some|a couple of|few)\s+"
    r"(?:year|month|week|day)s?\s+"
    r"(?:ago|before|earlier|back|prior)\b",
    re.IGNORECASE,
)

# Strong "planned" markers
_PLANNED_RE = re.compile(
    r"\b(?:next\s+(?:month|year|week|day|monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday)|"
    r"will\s+\w+|"
    r"plan(?:ning)?\s+to|"
    r"going\s+to|"
    r"scheduled\s+for)\b",
    re.IGNORECASE,
)


def detect_temporal_role(content: str) -> Optional[str]:
    """Detect the dominant temporal role for a memory content.

    Returns one of:
      - 'relative_marker': content contains a relative-temporal expression
      - 'planned_date': content describes a planned/future event
      - None: no special temporal marker (default mention_date semantics)

    Multiple markers: relative_marker takes precedence (it's the more
    informative signal — explicit relative reference).
    """
    if not content:
        return None
    if _RELATIVE_MARKER_RE.search(content):
        return "relative_marker"
    if _PLANNED_RE.search(content):
        return "planned_date"
    return None


def extract_relative_phrase(content: str) -> Optional[str]:
    """If a relative-temporal phrase exists, return its surface form."""
    if not content:
        return None
    m = _RELATIVE_MARKER_RE.search(content)
    return m.group(0) if m else None
