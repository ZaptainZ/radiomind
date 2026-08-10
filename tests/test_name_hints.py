"""Name hints (称呼线索) — proposing names for unnamed speakers.

The split under test: an LLM decides which words are personal names, and the
attribution ("whose name is it?") is arithmetic done here. So these tests feed
the name list in directly — the model's half is stubbed, the counting is real.

Material mirrors the shape of the production life log: Chinese prose summaries
that mention people who are present AND people who are merely being discussed,
plus the per-chunk speaker markers that leak into summary text.
"""

import pytest

from radiomind.refinement import name_hints as nh


def ep(eid, date, summary, participants, clock="10:00"):
    return {"id": eid, "date": date, "start_clock": clock,
            "summary": summary, "participants": participants}


@pytest.fixture
def episodes():
    """明月 tracks spk_003; 庆松 is talked about but never in the room."""
    return [
        ep(1, "2026-08-03", "在家和明月讨论装修，提到庆松晚上要来", ["我", "spk_003"]),
        # 狮子头 is a dish, not a person — the kind of thing an LLM sometimes
        # returns as a name. It appears exactly once, with spk_003 present.
        ep(2, "2026-08-03", "明月说猫被吓到了，随后聊到空调和狮子头", ["我", "spk_003"]),
        ep(3, "2026-08-04", "与庆松、明月约好晚上吃烧烤", ["我", "spk_001"]),
        ep(4, "2026-08-04", "地铁站台等车，广播提醒勿倚靠站台门", ["我", "spk_001"]),
        ep(5, "2026-08-06", "讨论戒指封孔的CNC加工，发言人1D提出反向打光", ["我", "spk_001"]),
    ]


# --- the model's half: parsing and filtering ---------------------------------

def test_parse_drops_the_things_that_are_never_names():
    """Filtered here rather than trusted to the prompt — the per-chunk markers
    leak into summary prose, so the model will see them and may echo them back."""
    reply = '{"names": ["明月", "我", "发言人1D", "对方甲", "spk_003", "庆松"]}'
    assert nh.parse_response(reply) == ["明月", "庆松"]


def test_parse_survives_a_fenced_reply_and_junk():
    assert nh.parse_response('```json\n{"names": ["明月"]}\n```') == ["明月"]
    assert nh.parse_response("模型今天不想输出 JSON") == []
    assert nh.parse_response("") == []


def test_parse_deduplicates():
    assert nh.parse_response('{"names": ["明月", "明月"]}') == ["明月"]


# --- our half: attribution by co-occurrence ----------------------------------

def test_a_name_that_tracks_one_speaker_becomes_their_candidate(episodes):
    ranked = nh.rank_candidates(["明月", "庆松"], episodes, ["spk_003", "spk_001"])
    top = ranked["spk_003"][0]
    assert top["name"] == "明月" and top["support"] == 2 and top["strong"] is True


def test_someone_merely_discussed_does_not_become_a_candidate(episodes):
    """「与庆松、明月约好」 is said ABOUT people who are elsewhere. 庆松 appears
    only in spk_001's episodes at its own baseline rate, so it must not be
    offered as spk_001's name."""
    ranked = nh.rank_candidates(["明月", "庆松"], episodes, ["spk_003", "spk_001"])
    # It may still be RECORDED against whoever happened to be in the room when it
    # was said — that is honest, the owner might recognise it. What it must never
    # be is a confident guess, because that is what becomes a tap target.
    for label, cands in ranked.items():
        for c in cands:
            if c["name"] == "庆松":
                assert c["strong"] is False and c["confidence"] < 0.5, label


def test_the_one_name_worth_tapping_actually_gets_promoted(episodes):
    """Regression: an earlier rule promoted on `lift`, which is a ratio against a
    baseline and goes soft when there are few episodes — 明月 sat at lift 1.33 and
    stayed weak, so the single candidate this whole feature exists to surface would
    never have become a button. Promotion now asks the blunter question: of the
    times this name is spoken, is this speaker usually there? (2 of 3)."""
    c = nh.rank_candidates(["明月"], episodes, ["spk_003"])["spk_003"][0]
    assert c["support"] == 2 and c["precision"] == pytest.approx(0.67, abs=0.01)
    assert c["strong"] is True, "lift alone would have left this at False"


def test_one_sighting_is_never_strong_however_clean(episodes):
    """A hallucinated "name" (狮子头 is a dish) mentioned once, with the speaker
    present, scores precision 1.0. Support is what stops it becoming a button."""
    c = nh.rank_candidates(["狮子头"], episodes, ["spk_003"])["spk_003"][0]
    assert c["precision"] == 1.0 and c["support"] == 1
    assert c["strong"] is False


def test_a_name_everywhere_belongs_to_nobody():
    """A word that appears in every episode carries no information about who is
    in the room — lift ≈ 1, so it is filtered out rather than offered to all."""
    eps = [ep(i, "2026-08-03", "明月出现在每一段里", ["我", f"spk_00{i%2+1}"])
           for i in range(1, 7)]
    ranked = nh.rank_candidates(["明月"], eps, ["spk_001", "spk_002"])
    assert ranked == {}


def test_candidates_carry_their_own_provenance(episodes):
    """The owner has to be able to see what the guess rests on."""
    c = nh.rank_candidates(["明月"], episodes, ["spk_003"])["spk_003"][0]
    assert c["episodes"] == [1, 2] and c["days"] == ["2026-08-03"]
    assert c["speaker_episodes"] == 2 and c["name_episodes"] == 3
    assert 0 < c["confidence"] < 1, "a co-occurrence guess is never certain"


def test_no_names_means_no_candidates(episodes):
    assert nh.rank_candidates([], episodes, ["spk_003"]) == {}
    assert nh.rank_candidates(["明月"], [], ["spk_003"]) == {}


# --- prompt assembly ---------------------------------------------------------

def test_prompt_carries_the_material_and_the_exclusions(episodes):
    material = {"episodes": episodes, "count": len(episodes)}
    prompt = nh.build_prompt(material)
    assert "与庆松、明月约好晚上吃烧烤" in prompt
    assert "2026-08-04" in prompt
    for must_warn_about in ("四季青桥", "发言人", "我"):
        assert must_warn_about in prompt
