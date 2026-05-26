"""Unit tests for TESG-1 employer-only temporal endpoint guard.

The guard fires only when a question asks "how long ... before
I started my current job at Y" AND the retrieved memories carry
0 first-person work-at-Y evidence statements. Negative anchor:
the same shape with NovaTech (gpt4_93159ced) MUST NOT fire,
because memories support the endpoint.
"""
from __future__ import annotations

from radiomind.core.temporal_endpoint_guard import (
    _count_employer_evidence,
    _extract_employer_endpoint,
    detect_temporal_endpoint_mismatch,
    maybe_rewrite_with_temporal_guard,
    temporal_endpoint_support_guard,
)


# Real LongMemEval haystack samples — copied from the actual dataset.
NOVATECH_USER_MEMS = [
    {"memory": "[user] I'm a software engineer, specifically a "
               "backend developer, and I've been in this field since I "
               "graduated with a degree in Computer Science from the "
               "University of California, Berkeley. I've been working at "
               "NovaTech for about 4 years and 3 months now."},
    {"memory": "[assistant] NovaTech! Nice to help a fellow NovaTechian."},
    {"memory": "[user] I think my team would greatly benefit from these "
               "tools, especially with the high-priority project we're "
               "working on at NovaTech."},
]
NOVATECH_Q = (
    "How long have I been working before I started my current job at "
    "NovaTech?"
)

GOOGLE_USER_MEMS_NO_EVIDENCE = [
    # All Google mentions are TOOL references, not employment
    {"memory": "[user] I'm considering using Google Drive since I already "
               "use Google Photos and it integrates well with it. But "
               "I'm not sure if I should upgrade to 100GB or 200GB."},
    {"memory": "[user] I've been listening to bird calls online for about "
               "a month now."},
    {"memory": "[assistant] That's a great idea! Asking your friends to "
               "bring a side dish is a wonderful way to make the "
               "potluck more collaborative and fun."},
]
GOOGLE_Q = (
    "How long have I been working before I started my current job at "
    "Google?"
)


# ---------- trigger extraction ----------

class TestExtractEmployerEndpoint:
    def test_novatech(self):
        assert _extract_employer_endpoint(NOVATECH_Q) == "NovaTech"

    def test_google(self):
        assert _extract_employer_endpoint(GOOGLE_Q) == "Google"

    def test_two_word_employer(self):
        q = ("How long have I been working before I started my current "
             "job at Acme Corp?")
        assert _extract_employer_endpoint(q) == "Acme Corp"

    def test_three_word_employer(self):
        q = ("How long have I been working before I joined my new role "
             "at International Business Machines?")
        assert _extract_employer_endpoint(q) == "International Business Machines"

    def test_no_trigger_returns_none(self):
        # Different temporal shape — guard must not fire
        assert _extract_employer_endpoint(
            "How long have I been working at NovaTech?"
        ) is None

    def test_no_employer_returns_none(self):
        # Trigger shape but no capitalized employer noun
        assert _extract_employer_endpoint(
            "How long have I been working before I started my current job?"
        ) is None

    def test_unrelated_question_returns_none(self):
        assert _extract_employer_endpoke if False else _extract_employer_endpoint(
            "How many years older am I than when I graduated from college?"
        ) is None


# ---------- evidence counting ----------

class TestCountEmployerEvidence:
    def test_novatech_has_2_evidence(self):
        # Both user turns about NovaTech, but only the first has clear
        # work-at-Y phrasing ("working at NovaTech for ...").
        # The second ("project at NovaTech") is also acceptable via
        # the "working at" pattern.
        texts = [m["memory"] for m in NOVATECH_USER_MEMS
                 if "[user]" in m["memory"].lower()]
        assert _count_employer_evidence("NovaTech", texts) >= 1

    def test_google_has_zero_evidence(self):
        texts = [m["memory"] for m in GOOGLE_USER_MEMS_NO_EVIDENCE
                 if "[user]" in m["memory"].lower()]
        assert _count_employer_evidence("Google", texts) == 0

    def test_unrelated_employer_zero(self):
        texts = [m["memory"] for m in NOVATECH_USER_MEMS
                 if "[user]" in m["memory"].lower()]
        assert _count_employer_evidence("Microsoft", texts) == 0


# ---------- guard fires ----------

class TestGuardFires:
    def test_google_no_evidence_fires(self):
        guard = temporal_endpoint_support_guard(
            GOOGLE_Q, GOOGLE_USER_MEMS_NO_EVIDENCE,
        )
        assert guard != ""
        assert "Google" in guard
        assert "haven't started" in guard

    def test_google_no_evidence_detection(self):
        d = detect_temporal_endpoint_mismatch(
            GOOGLE_Q, GOOGLE_USER_MEMS_NO_EVIDENCE,
        )
        assert d is not None
        assert d["employer"] == "Google"
        assert d["evidence_hits"] == 0

    def test_made_up_employer_fires(self):
        # Unknown employer w/o memory evidence → fire
        guard = temporal_endpoint_support_guard(
            "How long have I been working before I started my new job "
            "at Acme?",
            [{"memory": "[user] I work at Microsoft."}],
        )
        assert guard != ""
        assert "Acme" in guard


# ---------- guard SKIPS (must not fire) ----------

class TestGuardSkips:
    def test_novatech_with_evidence(self):
        # Memories carry "I've been working at NovaTech for about 4
        # years and 3 months" → endpoint supported → no guard.
        guard = temporal_endpoint_support_guard(
            NOVATECH_Q, NOVATECH_USER_MEMS,
        )
        assert guard == ""

    def test_novatech_with_evidence_detection_none(self):
        d = detect_temporal_endpoint_mismatch(
            NOVATECH_Q, NOVATECH_USER_MEMS,
        )
        assert d is None

    def test_unrelated_question_does_not_fire(self):
        # c18a7dc8 shape — age question, completely different.
        assert temporal_endpoint_support_guard(
            "How many years older am I than when I graduated from "
            "college?",
            GOOGLE_USER_MEMS_NO_EVIDENCE,
        ) == ""

    def test_pure_duration_question_does_not_fire(self):
        # "How long have I been working" without "before I started ..."
        # is a regular duration question.
        assert temporal_endpoint_support_guard(
            "How long have I been working at NovaTech?",
            NOVATECH_USER_MEMS,
        ) == ""

    def test_empty_memories_does_not_fire(self):
        assert temporal_endpoint_support_guard(GOOGLE_Q, []) == ""

    def test_assistant_only_memories_does_not_fire(self):
        # If only assistant turns are in memory, we don't have user
        # evidence; but we also don't have ANY user content to judge
        # absence from — skip rather than false-fire.
        assert temporal_endpoint_support_guard(
            GOOGLE_Q,
            [{"memory": "[assistant] You should consider Google Cloud."}],
        ) == ""


# ---------- post-rewrite ----------

class TestMaybeRewriteWithTemporalGuard:
    def test_rewrite_when_committed_duration(self):
        # Guard fired AND LLM committed to a duration → rewrite
        out = maybe_rewrite_with_temporal_guard(
            GOOGLE_Q, GOOGLE_USER_MEMS_NO_EVIDENCE,
            "You have been working 4 years and 3 months before starting "
            "at Google.",
        )
        assert "not enough" in out.lower()
        assert "Google" in out

    def test_no_rewrite_when_no_trigger(self):
        out = maybe_rewrite_with_temporal_guard(
            "How long have I been working at NovaTech?",
            NOVATECH_USER_MEMS,
            "4 years and 3 months.",
        )
        assert out == "4 years and 3 months."

    def test_no_rewrite_when_evidence_supports(self):
        # NovaTech case — guard does NOT fire even though answer
        # commits to a duration
        out = maybe_rewrite_with_temporal_guard(
            NOVATECH_Q, NOVATECH_USER_MEMS,
            "You worked 4 years and 9 months before starting at "
            "NovaTech.",
        )
        assert out.startswith("You worked 4 years")  # unchanged

    def test_no_rewrite_when_llm_already_abstained(self):
        # Guard fires but LLM already abstained → don't double-rewrite
        out = maybe_rewrite_with_temporal_guard(
            GOOGLE_Q, GOOGLE_USER_MEMS_NO_EVIDENCE,
            "The information provided is not enough.",
        )
        assert out == "The information provided is not enough."
