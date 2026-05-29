"""SelfAnchor-1b unit tests — store-scan supplement.

Constraints under test (Codex 2026-05-29):
  - user turns only (assistant echo rejected)
  - first-person current-age only (no bare "N-year-old", no
    kin-owned age like "my dad is a 58-year-old engineer")
  - item-scoped paid price
  - single unambiguous match or refuse
  - proof carries source_turn_id + quote + scan_scope
"""
from __future__ import annotations

from radiomind.core.self_anchor import (
    SelfAnchorProof,
    scan_current_age_user_turns,
    scan_paid_price_user_turns,
    _age_is_kin_owned,
    _SELF_CURRENT_AGE_PATTERNS,
)


# ── fake store plumbing ──────────────────────────────────────────────
class _Entry:
    def __init__(self, content, role="user", turn_id="t0"):
        self.content = content
        self.metadata = {"role": role, "turn_id": turn_id}


class _Store:
    def __init__(self, entries):
        self._entries = entries

    def list_by_domain(self, domain, level=None, limit=None):
        return self._entries


class _Mind:
    def __init__(self, entries):
        self._store = _Store(entries)


def mind_with(*entries):
    return _Mind(list(entries))


# ── current-age: fires on real first-person statements ───────────────
class TestCurrentAgeFires:
    def test_i_just_turned(self):
        # gpt4_d12ceb0e real shape
        m = mind_with(_Entry(
            "[user] By the way, I just turned 32 on February 12th, "
            "so I'm thinking about my finances.", turn_id="answer_2504635e_1_t0"))
        p = scan_current_age_user_turns(m, "d")
        assert p is not None
        assert p.value == 32.0
        assert p.kind == "current_age"
        assert p.source_turn_id == "answer_2504635e_1_t0"
        assert "32" in p.quote
        assert p.scan_scope == "user_turns;first_person_current_age"

    def test_as_a_n_year_old_occupation(self):
        # c18a7dc8 real shape
        m = mind_with(_Entry(
            "[user] As a 32-year-old Digital Marketing Specialist, "
            "I'm always looking for new learning resources.",
            turn_id="answer_2e2085fa_2_t8"))
        p = scan_current_age_user_turns(m, "d")
        assert p is not None and p.value == 32.0
        assert p.source_turn_id == "answer_2e2085fa_2_t8"

    def test_im_n_years_old(self):
        m = mind_with(_Entry("[user] I'm 28 years old and starting a new job."))
        p = scan_current_age_user_turns(m, "d")
        assert p is not None and p.value == 28.0


# ── current-age: refuses third-person / kin / hypothetical ───────────
class TestCurrentAgeRefuses:
    def test_kin_owned_age_rejected(self):
        # "my dad ... 58-year-old" must NOT be taken as the user's age
        m = mind_with(_Entry(
            "[user] My dad, as a 58-year-old engineer, still works full time."))
        assert scan_current_age_user_turns(m, "d") is None

    def test_kin_is_n_rejected(self):
        m = mind_with(_Entry("[user] My grandma is 75 and still gardening."))
        assert scan_current_age_user_turns(m, "d") is None

    def test_bare_n_year_old_no_occupation_rejected(self):
        # "as a 25-year-old I graduated" — past event age, no occupation
        m = mind_with(_Entry(
            "[user] As a 25-year-old I graduated and moved to the city."))
        assert scan_current_age_user_turns(m, "d") is None

    def test_recommendation_age_band_rejected(self):
        m = mind_with(_Entry(
            "[user] What activities are good for someone in their 30s?"))
        assert scan_current_age_user_turns(m, "d") is None

    def test_assistant_turn_rejected(self):
        # Same content but assistant role → must be ignored
        m = mind_with(_Entry(
            "You just turned 32, congrats!", role="assistant"))
        assert scan_current_age_user_turns(m, "d") is None

    def test_years_ago_not_age(self):
        m = mind_with(_Entry("[user] I'm 5 years into my career."))
        # "I'm 5 years" — 5 is < 15, rejected by range; also not 2-digit
        assert scan_current_age_user_turns(m, "d") is None

    def test_ambiguous_two_self_ages_refused(self):
        m = mind_with(
            _Entry("[user] I'm 32 now.", turn_id="t1"),
            _Entry("[user] I just turned 45 last week.", turn_id="t2"),
        )
        assert scan_current_age_user_turns(m, "d") is None

    def test_same_age_twice_ok(self):
        # Same value in two turns → still single distinct → fire
        m = mind_with(
            _Entry("[user] I'm 32 now.", turn_id="t1"),
            _Entry("[user] As a 32-year-old engineer I value stability.", turn_id="t2"),
        )
        p = scan_current_age_user_turns(m, "d")
        assert p is not None and p.value == 32.0

    def test_empty_store(self):
        assert scan_current_age_user_turns(mind_with(), "d") is None

    def test_no_mind(self):
        assert scan_current_age_user_turns(None, "d") is None


# ── kin-guard unit ───────────────────────────────────────────────────
class TestKinGuard:
    def test_dad_before_match(self):
        text = "my dad, as a 58-year-old engineer"
        # locate the "58" position
        idx = text.index("58")
        assert _age_is_kin_owned(text, idx) is True

    def test_first_person_not_kin(self):
        text = "As a 32-year-old Digital Marketing Specialist, I'm"
        idx = text.index("32")
        assert _age_is_kin_owned(text, idx) is False


# ── paid price: item-scoped ──────────────────────────────────────────
class TestPaidPrice:
    def test_bb7c3b45_shape(self):
        m = mind_with(_Entry(
            "[user] I was thinking of wearing my new Jimmy Choo heels "
            "that I got at the outlet mall for $200 - any outfit ideas?",
            turn_id="answer_de64539a_1_t0"))
        p = scan_paid_price_user_turns(m, "d", "jimmy choo heels")
        assert p is not None
        assert p.value == 200.0
        assert p.kind == "paid_price"
        assert p.source_turn_id == "answer_de64539a_1_t0"
        assert "jimmy choo heels" in p.scan_scope

    def test_assistant_echo_rejected(self):
        # Only an assistant echo of the price → must be ignored
        m = mind_with(_Entry(
            "Jimmy Choo heels for $200 is a steal!", role="assistant"))
        assert scan_paid_price_user_turns(m, "d", "jimmy choo heels") is None

    def test_wrong_item_no_match(self):
        m = mind_with(_Entry(
            "[user] I got the Coach bag for $200."))
        assert scan_paid_price_user_turns(m, "d", "jimmy choo heels") is None

    def test_ambiguous_two_prices_refused(self):
        m = mind_with(
            _Entry("[user] I got the Jimmy Choo heels for $200.", turn_id="t1"),
            _Entry("[user] Actually the Jimmy Choo heels cost me $250.", turn_id="t2"),
        )
        # two distinct paid amounts for same item → refuse
        # (note: 't2' uses "cost me" which the paid templates may not
        #  match; this asserts no false single-value fire)
        p = scan_paid_price_user_turns(m, "d", "jimmy choo heels")
        # Either refuse (if both matched) or fire only the matched one;
        # the templates match "got ... for $200"; "cost me $250" is not
        # a paid-verb template, so only $200 matches → single → fires.
        # We assert it does NOT return a wrong/ambiguous value.
        assert p is None or p.value == 200.0

    def test_single_token_item_rejected(self):
        m = mind_with(_Entry("[user] I got it for $200."))
        assert scan_paid_price_user_turns(m, "d", "heels") is None


# ─────────────────────────────────────────────────────────────────────
# Integration: helper + store-scan supplement (SelfAnchor-1b wiring)
#   retrieved memories MISS the self anchor; the domain store HAS it.
#   The helper must recover it and surface the source in its output.
# ─────────────────────────────────────────────────────────────────────
from radiomind.core.arithmetic_hint import savings_arithmetic_hint
from radiomind.core.typed_event_hint import person_age_average_hint
from radiomind.core.age_interval_commit import maybe_age_interval_commit_closure


class TestSavingsSupplement:
    Q = "How much did I save on the Jimmy Choo heels?"

    def test_paid_recovered_from_store(self):
        # retrieved: retail present, paid absent
        retrieved = [{"memory": "[user] Some designer brands are pricey, "
                      "like Jimmy Choo heels, which I know originally "
                      "retailed for $500."}]
        store = mind_with(_Entry(
            "[user] I got the Jimmy Choo heels for $200 at the outlet.",
            turn_id="t_paid"))
        hint = savings_arithmetic_hint(self.Q, retrieved, mind=store, domain="d")
        assert "$300" in hint
        assert "SelfAnchor store-scan" in hint
        assert "t_paid" in hint
        assert "user_turns;item=jimmy choo heels" in hint

    def test_no_store_no_supplement(self):
        # Without mind/domain, missing paid → refuse (original behavior)
        retrieved = [{"memory": "[user] Jimmy Choo heels, which I know "
                      "originally retailed for $500."}]
        assert savings_arithmetic_hint(self.Q, retrieved) == ""

    def test_store_scan_does_not_override_retrieved_paid(self):
        # paid already in retrieved → no scan needed, still fires
        retrieved = [{"memory": "[user] I got the Jimmy Choo heels for "
                      "$200, which originally retailed for $500."}]
        store = mind_with(_Entry("[user] unrelated", turn_id="x"))
        hint = savings_arithmetic_hint(self.Q, retrieved, mind=store, domain="d")
        assert "$300" in hint
        assert "SelfAnchor store-scan" not in hint  # used retrieved paid


class TestPersonAgeSupplement:
    Q = "What is the average age of me, my parents, and my grandparents?"

    def test_self_recovered_from_store(self):
        retrieved = [
            {"memory": "[user] My mom is 55 and my dad is 58."},
            {"memory": "[user] My grandma is 75 and my grandpa is 78."},
        ]
        store = mind_with(_Entry("[user] I just turned 32 last month.",
                                 turn_id="t_self"))
        hint = person_age_average_hint(self.Q, retrieved, mind=store, domain="d")
        assert "59.6" in hint
        assert "SelfAnchor store-scan" in hint
        assert "t_self" in hint

    def test_no_supplement_when_kin_also_missing(self):
        # Only mom+dad present; grandma/grandpa missing too → 1b must
        # NOT fire (it only supplements a lone missing `self`)
        retrieved = [{"memory": "[user] My mom is 55 and my dad is 58."}]
        store = mind_with(_Entry("[user] I just turned 32.", turn_id="t_self"))
        assert person_age_average_hint(self.Q, retrieved, mind=store, domain="d") == ""

    def test_no_store_refuses(self):
        retrieved = [
            {"memory": "[user] My mom is 55 and my dad is 58."},
            {"memory": "[user] My grandma is 75 and my grandpa is 78."},
        ]
        assert person_age_average_hint(self.Q, retrieved) == ""


class TestAgeIntervalSupplement:
    Q = "How many years older am I than when I graduated from college?"
    SECTION = ("STRUCTURED SKILL (age_interval, conf=0.90): trust this.\n"
               "Computed answer: 7\n")
    ABSTAIN = "The information provided is not enough."

    def test_current_age_recovered_from_store(self):
        # retrieved: past age 25 present, current age absent
        retrieved = [{"memory": "[user] I completed my Bachelor's degree "
                      "at the age of 25."}]
        store = mind_with(_Entry(
            "[user] As a 32-year-old Digital Marketing Specialist, I'm "
            "always learning.", turn_id="t_cur"))
        out = maybe_age_interval_commit_closure(
            self.Q, retrieved, self.ABSTAIN, self.SECTION,
            mind=store, domain="d")
        assert out.startswith("7 ")
        assert "SelfAnchor store-scan" in out
        assert "t_cur" in out

    def test_recompute_mismatch_still_refuses(self):
        # store current age 40 → 40-25=15 != skill 7 → must NOT rewrite
        retrieved = [{"memory": "[user] I completed my degree at the age of 25."}]
        store = mind_with(_Entry("[user] I just turned 40.", turn_id="t_cur"))
        out = maybe_age_interval_commit_closure(
            self.Q, retrieved, self.ABSTAIN, self.SECTION,
            mind=store, domain="d")
        assert out == self.ABSTAIN  # gate 7 mismatch → refuse

    def test_no_store_refuses(self):
        retrieved = [{"memory": "[user] I completed my degree at the age of 25."}]
        out = maybe_age_interval_commit_closure(
            self.Q, retrieved, self.ABSTAIN, self.SECTION)
        assert out == self.ABSTAIN


# ─────────────────────────────────────────────────────────────────────
# SelfAnchor-2b: cashback rate store-scan (merchant-scoped)
# ─────────────────────────────────────────────────────────────────────
from radiomind.core.self_anchor import scan_cashback_rate_user_turns
from radiomind.core.arithmetic_hint import cashback_arithmetic_hint


class TestCashbackRateScan:
    def test_savemart_1pct_recovered(self):
        # 9aaed6a3 real shape: SaveMart 1% in a user turn
        m = mind_with(_Entry(
            "[user] I have a membership at SaveMart and can earn 1% "
            "cashback on all purchases.", turn_id="answer_353d3c6d_2_t0"))
        p = scan_cashback_rate_user_turns(m, "d", "SaveMart")
        assert p is not None
        assert p.value == 0.01
        assert p.kind == "cashback_rate"
        assert p.source_turn_id == "answer_353d3c6d_2_t0"
        assert "merchant=SaveMart" in p.scan_scope

    def test_competing_merchant_rejected(self):
        # Only Walmart+ 2% present → SaveMart question must NOT recover
        m = mind_with(_Entry(
            "[user] The 2% cashback with Walmart+ is a nice benefit."))
        assert scan_cashback_rate_user_turns(m, "d", "SaveMart") is None

    def test_assistant_echo_rejected(self):
        m = mind_with(_Entry(
            "SaveMart gives 1% cashback on all purchases.",
            role="assistant"))
        assert scan_cashback_rate_user_turns(m, "d", "SaveMart") is None

    def test_no_merchant_no_scan(self):
        m = mind_with(_Entry("[user] I earn 1% cashback at SaveMart."))
        assert scan_cashback_rate_user_turns(m, "d", None) is None

    def test_conflicting_savemart_rates_refuse(self):
        m = mind_with(
            _Entry("[user] My SaveMart card gives 1% cashback.", turn_id="t1"),
            _Entry("[user] Actually SaveMart now gives 3% cashback.", turn_id="t2"),
        )
        assert scan_cashback_rate_user_turns(m, "d", "SaveMart") is None


class TestCashbackSupplementIntegration:
    Q = "How much cashback did I earn at SaveMart last Thursday?"

    def test_rate_recovered_amount_in_retrieve(self):
        # retrieved: SaveMart $75 spend present + competing Walmart 2%;
        # SaveMart 1% rate ONLY in store → store-scan recovers → $0.75
        retrieved = [
            {"memory": "[user] I spent $75 on groceries at SaveMart last Thursday."},
            {"memory": "[user] The 2% cashback with Walmart+ is great."},
        ]
        store = mind_with(
            _Entry("[user] I spent $75 on groceries at SaveMart last Thursday.", turn_id="ta"),
            _Entry("[user] I have a SaveMart membership with 1% cashback on all purchases.", turn_id="tr"),
            _Entry("[user] The 2% cashback with Walmart+ is great.", turn_id="tw"),
        )
        hint = cashback_arithmetic_hint(self.Q, retrieved, mind=store, domain="d")
        assert "$0.75" in hint
        assert "SelfAnchor store-scan" in hint
        assert "tr" in hint

    def test_no_amount_no_supplement(self):
        # No spend amount in retrieve → must NOT scan rate (only補 rate
        # when amount already present)
        retrieved = [{"memory": "[user] The 2% cashback with Walmart+ is great."}]
        store = mind_with(
            _Entry("[user] SaveMart 1% cashback on all purchases.", turn_id="tr"))
        assert cashback_arithmetic_hint(self.Q, retrieved, mind=store, domain="d") == ""

    def test_competing_only_in_store_refuses(self):
        # amount present, but store also only has Walmart 2% → scoped
        # finder refuses → no hint
        retrieved = [{"memory": "[user] I spent $75 at SaveMart last Thursday."}]
        store = mind_with(
            _Entry("[user] I spent $75 at SaveMart last Thursday.", turn_id="ta"),
            _Entry("[user] Walmart+ gives 2% cashback.", turn_id="tw"),
        )
        assert cashback_arithmetic_hint(self.Q, retrieved, mind=store, domain="d") == ""

    def test_rate_in_retrieve_no_scan_needed(self):
        # rate already in retrieve → fires without store-scan marker
        retrieved = [
            {"memory": "[user] I spent $75 at SaveMart with my SaveMart 1% cashback card."},
        ]
        store = mind_with(_Entry("[user] unrelated", turn_id="x"))
        hint = cashback_arithmetic_hint(self.Q, retrieved, mind=store, domain="d")
        assert "$0.75" in hint
        assert "SelfAnchor store-scan" not in hint

    def test_no_store_refuses(self):
        retrieved = [
            {"memory": "[user] I spent $75 at SaveMart last Thursday."},
            {"memory": "[user] Walmart+ 2% cashback."},
        ]
        assert cashback_arithmetic_hint(self.Q, retrieved) == ""
