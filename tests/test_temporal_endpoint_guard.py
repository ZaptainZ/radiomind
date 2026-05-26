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
        assert _extract_employer_endpoint(
            "How many years older am I than when I graduated from college?"
        ) is None

    # ---- TESG-1b: lowercase / generic noun negative tests ----

    def test_lowercase_generic_somewhere(self):
        # Codex P1.1: pre-fix, `... at somewhere` triggered. Must NOT.
        assert _extract_employer_endpoint(
            "How long have I been working before I started my current "
            "job at somewhere?"
        ) is None

    def test_lowercase_generic_the_company(self):
        # Codex P1.1 second example.
        assert _extract_employer_endpoint(
            "How long have I been working before I started my current "
            "job at the company?"
        ) is None

    def test_lowercase_brand(self):
        # `acme corp` (lowercase) MUST NOT trigger — only Title-Cased
        # brand names.
        assert _extract_employer_endpoint(
            "How long have I been working before I joined my new job "
            "at acme corp?"
        ) is None

    def test_lowercase_a_friend(self):
        assert _extract_employer_endpoint(
            "How long have I been working before I started my new job "
            "at a friend?"
        ) is None

    def test_lowercase_my_friend(self):
        assert _extract_employer_endpoint(
            "How long have I been working before I started my new job "
            "at my friend?"
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
        # TESG-1c: default is evidence-insufficient wording.
        # "haven't started" assertion requires explicit-negative
        # /future-plan textual evidence, which the canned Google
        # memories don't carry (only "considering Google Drive"
        # tool mention).
        guard = temporal_endpoint_support_guard(
            GOOGLE_Q, GOOGLE_USER_MEMS_NO_EVIDENCE,
        )
        assert guard != ""
        assert "Google" in guard
        assert "evidence" in guard.lower()
        # Default branch must NOT assert "haven't started"
        assert "haven't started" not in guard.lower()

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

    # ---- TESG-1b: store-scan fallback negative tests ----

    def test_store_supports_endpoint_does_not_fire(self):
        """Codex P1.2: retrieval miss must NOT be treated as negative
        evidence. When the full domain store carries first-person
        work-at-Y, the guard must NOT fire even if retrieved memories
        miss it."""

        # Fake `mind` with a populated store; retrieved is empty of
        # the relevant turn (e.g. ranked out of top-K) but the store
        # has the actual user statement.
        class _FakeEntry:
            def __init__(self, content):
                self.content = content
                self.metadata = {}

        class _FakeStore:
            def list_by_domain(self, domain, level=None, limit=None):
                return [
                    _FakeEntry("[user] I've been working at NovaTech "
                               "for about 4 years and 3 months."),
                    _FakeEntry("[user] Random unrelated turn."),
                ]

        class _FakeMind:
            _store = _FakeStore()

        # Retrieved memories miss the NovaTech evidence (e.g. all
        # ranked turns are unrelated chatter):
        retrieved_missing = [
            {"memory": "[user] Looking for marketing course advice."},
            {"memory": "[user] Could you recommend a book?"},
        ]
        # Without mind+domain: retrieved-only mode fires with
        # default evidence-insufficient wording (TESG-1c).
        retrieved_only_guard = temporal_endpoint_support_guard(
            NOVATECH_Q, retrieved_missing,
        )
        assert retrieved_only_guard != ""
        assert "haven't started" not in retrieved_only_guard.lower()
        assert "available evidence" in retrieved_only_guard.lower()

        # With mind+domain: store-scan finds the evidence → no fire.
        store_guard = temporal_endpoint_support_guard(
            NOVATECH_Q, retrieved_missing,
            mind=_FakeMind(), domain="lme_novatech",
        )
        assert store_guard == ""

    def test_store_misses_endpoint_uses_evidence_insufficient_wording(self):
        """TESG-1c: even when retrieved + store both miss, default
        wording stays evidence-insufficient. Absence of FACT is NOT
        proof of factual absence (extraction can miss raw turns)."""

        class _FakeStore:
            def list_by_domain(self, domain, level=None, limit=None):
                return []  # empty store

        class _FakeMind:
            _store = _FakeStore()

        guard = temporal_endpoint_support_guard(
            GOOGLE_Q, GOOGLE_USER_MEMS_NO_EVIDENCE,
            mind=_FakeMind(), domain="lme_google",
        )
        assert guard != ""
        # Default branch must NOT assert "haven't started"
        assert "haven't started" not in guard.lower()
        # Default branch SHOULD warn that absence of evidence is not
        # proof of absence
        assert "absence" in guard.lower() or "available evidence" in guard.lower()

    def test_explicit_negative_evidence_unlocks_assertive_wording(self):
        """TESG-1c: when memories contain explicit not-yet / planning
        / interviewing language about the employer, the assertive
        'haven\\'t started' branch fires (we now have textual support)."""
        retrieved_with_plan = [
            {"memory": "[user] I have an upcoming interview at Google "
                       "next week and I'm hoping to join the team."},
        ]
        guard = temporal_endpoint_support_guard(
            GOOGLE_Q, retrieved_with_plan,
        )
        assert guard != ""
        assert "haven't started" in guard.lower()
        assert "explicit-negative" in guard.lower()

    def test_explicit_negative_planning_to_join(self):
        retrieved = [
            {"memory": "[user] I'm planning to join Acme next month "
                       "after my current role wraps up."},
        ]
        guard = temporal_endpoint_support_guard(
            "How long have I been working before I started my new job "
            "at Acme?",
            retrieved,
        )
        assert guard != ""
        assert "haven't started" in guard.lower()


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

    def test_rewrite_default_uses_evidence_insufficient_wording(self):
        """TESG-1c: no positive support + no explicit negative →
        default rewrite uses 'available evidence does not establish'
        wording. Even with mind+domain, the rewrite stays soft."""

        class _FakeStore:
            def list_by_domain(self, domain, level=None, limit=None):
                return []

        class _FakeMind:
            _store = _FakeStore()

        out = maybe_rewrite_with_temporal_guard(
            GOOGLE_Q, GOOGLE_USER_MEMS_NO_EVIDENCE,
            "You worked 4 years before starting at Google.",
            mind=_FakeMind(), domain="lme_google",
        )
        # TESG-1c: absent explicit negative, must use soft wording
        assert "haven't started" not in out.lower()
        assert "available evidence" in out.lower()

    def test_rewrite_explicit_negative_uses_assertive_wording(self):
        """TESG-1c: explicit negative/future-plan evidence in memories
        unlocks the 'haven\\'t started' rewrite."""
        retrieved_with_plan = [
            {"memory": "[user] I'm planning to join Google next month."},
        ]
        out = maybe_rewrite_with_temporal_guard(
            GOOGLE_Q, retrieved_with_plan,
            "You worked 4 years before starting at Google.",
        )
        assert "haven't started working at Google" in out

    def test_fact_extraction_miss_does_not_falsely_assert(self):
        """Codex P1: a raw user turn saying 'I started at Google last
        week' may fail to be promoted to FACT. If retrieved misses
        it AND FACT store misses it (extraction gap), the guard
        should still fire (rewrite path is purely guarded by
        absence) BUT must NOT assert 'haven\\'t started' — because
        the user DID say it in the raw turn."""

        class _FakeStore:
            def list_by_domain(self, domain, level=None, limit=None):
                # Simulating FACT extraction MISSING the relevant
                # turn — store has unrelated facts only.
                class E:
                    def __init__(self, c):
                        self.content = c
                        self.metadata = {}
                return [
                    E("[user] I love pizza."),
                    E("[user] My favorite color is blue."),
                ]

        class _FakeMind:
            _store = _FakeStore()

        # Retrieved memories also miss the Google work-at turn (e.g.
        # ranked out of top-K).
        out = maybe_rewrite_with_temporal_guard(
            GOOGLE_Q,
            [{"memory": "[user] Tell me about pizza recipes."}],
            "You worked 4 years before starting at Google.",
            mind=_FakeMind(), domain="lme_google",
        )
        # Soft wording — we have NOT verified the user hasn't started
        # at Google; we have only verified the pipeline's extracted
        # records don't show it. Cannot assert "haven't started".
        assert "haven't started" not in out.lower()
        assert "available evidence" in out.lower()
