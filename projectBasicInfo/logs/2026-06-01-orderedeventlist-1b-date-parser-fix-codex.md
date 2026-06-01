# OrderedEventList-1b — Shared Event Date Parser Fix

**Date**: 2026-06-01
**Author**: Codex
**Status**: Complete. Fixed the deterministic date parser bug that made the
existing `ListOrderingSkill` silently dead on LongMemEval's session-date
format, and fixed the copied parser in `event_interval`.

---

## Background

OrderedEventList-1a found this was not a greenfield capability gap:
`src/radiomind/skills/list_ordering.py` already implements extract → sort →
render for "order of X from earliest to latest" questions. It failed because
its `_parse_date` could not parse LongMemEval session dates like:

```text
2022/12/19 (Mon) 19:53
```

`event_interval.py` carried a copied parser with the same failure mode in its
FACT-store tier.

## Change

Added a shared parser:

- `src/radiomind/skills/date_utils.py`
  - `parse_event_date(value) -> datetime | None`
  - supports `YYYY-MM-DD`, `YYYY/MM/DD`, `YYYY/MM/DD (Dow) HH:MM`, and
    month-name forms such as `March 5, 2023` / `Mar 5, 2023`.

Updated:

- `src/radiomind/skills/list_ordering.py`
- `src/radiomind/skills/event_interval.py`

Both local `_parse_date` functions now delegate to `parse_event_date`, avoiding
another copy-paste parser split.

## Tests

Added `tests/test_event_date_parse.py`:

- LongMemEval slash + weekday + time shape parses.
- Existing slash / dash / month-name shapes still parse.
- Invalid dates return `None`.
- Both `list_ordering._parse_date` and `event_interval._parse_date` use the
  shared fix.

Added the test file to `bench/end_to_end/regression_pack.py` as:

```text
skill:event-date-parse
```

## Verification

```text
tests/test_event_date_parse.py: 5 passed
regression_pack.py: 12 categories ALL PASS
```

Direct smoke:

```text
list_ordering._parse_date("2022/12/19 (Mon) 19:53") -> 2022-12-19
event_interval._parse_date("2022/12/19 (Mon) 19:53") -> 2022-12-19
```

No benchmark or ingest/LLM run was performed. This slice is a pure deterministic
bug fix.

## Remaining Work

OrderedEventList-1c, if opened, should address completeness: feed
`ListOrderingSkill` a complete enough event set (likely FACT enumeration /
category expansion) before its existing extract → dedup → sort → render
pipeline. That is separate from this date parser fix.
