"""LoRAFuel-1b — prepare-habits: top up the habit store before training.

The LoRAFuel-1a audit found the real fuel break is GENERATION: nothing in
the product's daily path ever mints habits (refinement is manual-CLI-only),
so `radiomind train` hits the >=MIN_HABITS guard with an empty store.
prepare_habits() closes that loop: when fuel is short, run chat refinement
over the largest domains until the live count reaches the threshold.

Deliberately conservative:
  - no-op when fuel is already sufficient (never re-refines);
  - bounded by max_domains (LLM cost cap);
  - refine_fn is injected so the gating logic is unit-testable without
    an LLM, and failures in one domain never abort the loop.

NOT here (LoRAFuel-1a ruling): wiring prune_stale (hit accounting is
still noise — expiry would archive by dice roll), mirror-hit feedback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from radiomind.core.types import MemoryStatus


@dataclass
class PrepareReport:
    triggered: bool
    before: int
    after: int
    min_needed: int
    domains_refined: list[tuple[str, int]] = field(default_factory=list)
    reached: bool = True
    reason: str = ""


def count_live_habits(habits: Any) -> int:
    """Habits that data_gen would accept (non-archived)."""
    return sum(
        1 for h in habits.all_habits() if h.status != MemoryStatus.ARCHIVED
    )


def prepare_habits(
    habits: Any,
    domains_by_size: list[str],
    refine_fn: Callable[[str], Any],
    min_count: int,
    max_domains: int = 8,
) -> PrepareReport:
    """Refine the largest domains until the live habit count reaches
    min_count. Returns a full before/after report for CLI logging."""
    before = count_live_habits(habits)
    if before >= min_count:
        return PrepareReport(
            triggered=False, before=before, after=before,
            min_needed=min_count, reached=True,
        )

    refined: list[tuple[str, int]] = []
    for dom in domains_by_size[:max_domains]:
        try:
            r = refine_fn(dom)
            n_new = len(getattr(r, "new_insights", None) or [])
        except Exception:
            n_new = 0
        refined.append((dom, n_new))
        if count_live_habits(habits) >= min_count:
            break

    after = count_live_habits(habits)
    reached = after >= min_count
    reason = "" if reached else (
        f"refined {len(refined)} domain(s) but only {after}/{min_count} "
        f"habits — the store may lack pattern-rich memories, or the "
        f"refinement LLM is unavailable/refusing"
    )
    return PrepareReport(
        triggered=True, before=before, after=after, min_needed=min_count,
        domains_refined=refined, reached=reached, reason=reason,
    )
