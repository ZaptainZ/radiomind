"""Unit tests for V7 Step 3 (subset): ingest-time temporal role tagging."""
from __future__ import annotations

import pytest

from radiomind.core.temporal_provenance import (
    detect_temporal_role,
    extract_relative_phrase,
)


# ─────────────────────────────────────────────────────────────────────────────
# Relative marker detection
# ─────────────────────────────────────────────────────────────────────────────
class TestRelativeMarker:
    def test_a_few_years_ago(self):
        assert detect_temporal_role("Got the tattoo a few years ago.") == "relative_marker"

    def test_several_months_back(self):
        assert detect_temporal_role("Several months back I moved here.") == "relative_marker"

    def test_a_couple_of_years_earlier(self):
        assert detect_temporal_role("A couple of years earlier I tried that.") == "relative_marker"

    def test_few_weeks_prior(self):
        assert detect_temporal_role("Few weeks prior, we met.") == "relative_marker"

    def test_extract_relative_phrase_returns_match(self):
        assert extract_relative_phrase("Got the tattoo a few years ago.") == "a few years ago"

    def test_extract_relative_phrase_none_when_absent(self):
        assert extract_relative_phrase("Got the tattoo yesterday.") is None


# ─────────────────────────────────────────────────────────────────────────────
# Planned date detection
# ─────────────────────────────────────────────────────────────────────────────
class TestPlannedDate:
    def test_next_month(self):
        assert detect_temporal_role("Excited for the game next month!") == "planned_date"

    def test_plan_to(self):
        assert detect_temporal_role("I plan to visit next summer.") == "planned_date"

    def test_planning_to(self):
        assert detect_temporal_role("Planning to launch the album.") == "planned_date"

    def test_scheduled_for(self):
        assert detect_temporal_role("The meeting is scheduled for September.") == "planned_date"


# ─────────────────────────────────────────────────────────────────────────────
# Precedence + null cases
# ─────────────────────────────────────────────────────────────────────────────
class TestPrecedenceAndNull:
    def test_relative_takes_precedence_over_planned(self):
        # If both present, relative_marker wins (more informative)
        text = "I got the tattoo a few years ago and plan to add to it next month."
        assert detect_temporal_role(text) == "relative_marker"

    def test_no_marker_returns_none(self):
        assert detect_temporal_role("I like coffee.") is None

    def test_explicit_date_no_relative_returns_none(self):
        assert detect_temporal_role("On 2023-02-08 I got a tattoo.") is None

    def test_empty_input(self):
        assert detect_temporal_role("") is None
        assert detect_temporal_role(None) is None


# ─────────────────────────────────────────────────────────────────────────────
# Integration with _derive_fact_tags
# ─────────────────────────────────────────────────────────────────────────────
class TestFactTagIntegration:
    def test_relative_marker_yields_temporal_role_tag(self):
        from radiomind.core.mind import _derive_fact_tags

        meta = {}
        tags = _derive_fact_tags("Got the tattoo a few years ago.", meta)
        assert "temporal_role:relative_marker" in tags
        # The relative phrase should be stored in metadata for query-time use
        assert meta.get("relative_phrase") == "a few years ago"

    def test_planned_date_yields_temporal_role_tag(self):
        from radiomind.core.mind import _derive_fact_tags

        tags = _derive_fact_tags("Excited for the game next month!", {})
        assert "temporal_role:planned_date" in tags

    def test_plain_text_no_temporal_role_tag(self):
        from radiomind.core.mind import _derive_fact_tags

        tags = _derive_fact_tags("I like coffee.", {})
        assert not any(t.startswith("temporal_role:") for t in tags)
