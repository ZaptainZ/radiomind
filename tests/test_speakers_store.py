"""Speaker identity store (声纹身份) — migration v7 + SpeakerStore.

Uses synthetic unit vectors: a "voice" is a base direction, and the same person
speaking again is that direction plus jitter (cosine ≈ 0.95), while a different
person is an independent random direction (cosine ≈ 0). That is enough to exercise
the binding tiers, the admission gate and the merge/split paths without audio.
"""

import numpy as np
import pytest

from radiomind.storage.database import MemoryStore
from radiomind.storage.speakers import (
    MatchPolicy, ModelMismatch, SpeakerStore, SpeakerTurn, normalize,
)

DIM = 192
MODEL = "3dspeaker_eres2net_base_zh-cn@testfp"


@pytest.fixture
def sp(tmp_path):
    store = MemoryStore(tmp_path / "radiomind.db")
    store.open()
    yield SpeakerStore(store.conn, policy=MatchPolicy())
    store.close()


@pytest.fixture
def rng():
    return np.random.default_rng(20260805)


def voice(rng):
    """A person's underlying voice direction."""
    return normalize(rng.normal(size=DIM))


def utterance(rng, base, jitter=0.25):
    """The same person speaking again — same direction, a bit of variation.

    The perturbation is normalized before scaling: in 192 dimensions a raw
    N(0,1) vector has norm ~13.9 and would swamp the unit base direction.
    """
    return normalize(base + jitter * normalize(rng.normal(size=DIM)))


def turn(vec, *, t=1000.0, speech_s=6.0, date="2026-08-03", region="conversation",
         src="a.wav"):
    return SpeakerTurn(started_at=t, ended_at=t + speech_s, date=date, tz="Asia/Shanghai",
                       embedding=vec, model_id=MODEL, speech_s=speech_s,
                       region_type=region, source_file=src)


def test_migration_creates_tables_and_absolute_time(sp):
    tabs = {r[0] for r in sp._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"speaker_turns", "speakers", "speaker_exemplars",
            "speaker_centroids", "speaker_merges"} <= tabs
    cols = {r[1] for r in sp._conn.execute("PRAGMA table_info(lifelog_episodes)")}
    assert {"started_at", "ended_at", "tz"} <= cols  # clock strings are no longer the only time


def test_first_voice_creates_a_pending_speaker(sp, rng):
    a = voice(rng)
    out = sp.put_turns([turn(utterance(rng, a), t=100.0)], user_id="z")
    assert out["stored"] == 1 and out["new_pending"] == 1
    people = sp.list_speakers(user_id="z")
    assert len(people) == 1 and people[0]["status"] == "pending"


def test_same_voice_binds_to_the_same_speaker(sp, rng):
    a = voice(rng)
    sp.put_turns([turn(utterance(rng, a), t=100.0)], user_id="z")
    out = sp.put_turns([turn(utterance(rng, a), t=200.0)], user_id="z")
    assert out["bound_high"] == 1 and out["new_pending"] == 0
    assert len(sp.list_speakers(user_id="z")) == 1


def test_different_voice_becomes_a_second_speaker(sp, rng):
    a, b = voice(rng), voice(rng)
    sp.put_turns([turn(utterance(rng, a), t=100.0)], user_id="z")
    sp.put_turns([turn(utterance(rng, b), t=200.0)], user_id="z")
    labels = {p["label"] for p in sp.list_speakers(user_id="z")}
    assert len(labels) == 2


def test_media_region_never_enters_the_gallery(sp, rng):
    """A voice from the TV is stored as a turn but must never create or shape an identity."""
    tv = voice(rng)
    out = sp.put_turns([turn(utterance(rng, tv), t=100.0, region="media")], user_id="z")
    assert out["media_skipped"] == 1 and out["new_pending"] == 0
    assert sp.list_speakers(user_id="z") == []
    assert sp.stats(user_id="z")["turns"] == 1


def test_short_turns_never_create_an_identity(sp, rng):
    a = voice(rng)
    out = sp.put_turns([turn(utterance(rng, a), t=100.0, speech_s=1.0)], user_id="z")
    assert out["too_short"] == 1 and out["new_pending"] == 0
    # 1.5–3s may match an existing person but still must not mint one
    out2 = sp.put_turns([turn(utterance(rng, a), t=200.0, speech_s=2.0)], user_id="z")
    assert out2["new_pending"] == 0
    assert sp.list_speakers(user_id="z") == []


def test_gray_binding_does_not_become_an_exemplar(sp, rng):
    """The admission gate, not the threshold, is what keeps a centroid clean."""
    a = voice(rng)
    sp.put_turns([turn(utterance(rng, a, jitter=0.0), t=100.0)], user_id="z")
    before = len(sp._exemplars(sp.get("spk_001", "z")["id"]))

    # Aim at the middle of the configured gray band rather than a fixed mix, so
    # the test keeps testing the band after a recalibration moves it.
    target = (sp.policy.t_low + sp.policy.t_high) / 2
    gray = normalize(target * a + np.sqrt(1 - target**2) * voice(rng))
    match, score, binding = sp.match(gray, user_id="z", speech_s=6.0)
    if binding != "gray":
        pytest.skip(f"synthetic vector landed in '{binding}' at {score:.3f}, not the gray band")
    sp.put_turns([turn(gray, t=300.0)], user_id="z")
    assert len(sp._exemplars(sp.get("spk_001", "z")["id"])) == before


def test_promotion_requires_recurring_across_days(sp, rng):
    """≥2 distinct days is what separates a person in your life from a passer-by."""
    a = voice(rng)
    for i in range(6):   # six turns, plenty of speech, but all on one day
        sp.put_turns([turn(utterance(rng, a), t=100.0 + i, speech_s=15.0,
                           date="2026-08-03")], user_id="z")
    assert sp.promote(user_id="z")["promoted"] == []

    sp.put_turns([turn(utterance(rng, a), t=500.0, speech_s=15.0, date="2026-08-04")],
                 user_id="z")
    assert sp.promote(user_id="z")["promoted"] == ["spk_001"]
    assert sp.get("spk_001", "z")["status"] == "active"


def test_pending_expires_when_it_never_grows(sp, rng):
    a = voice(rng)
    sp.put_turns([turn(utterance(rng, a), t=100.0)], user_id="z")
    out = sp.promote(user_id="z", now=9e9)   # far in the future
    assert out["expired"] == ["spk_001"] and out["promoted"] == []


def test_rerunning_the_same_recording_is_idempotent(sp, rng):
    a = voice(rng)
    t1 = turn(utterance(rng, a), t=100.0)
    sp.put_turns([t1], user_id="z")
    again = sp.put_turns([t1], user_id="z")
    assert again["duplicate"] == 1 and again["stored"] == 0


def test_model_mismatch_is_refused(sp, rng):
    a = voice(rng)
    sp.put_turns([turn(utterance(rng, a), t=100.0)], user_id="z")
    other = turn(utterance(rng, a), t=200.0)
    other.model_id = "some_other_model@v2"
    with pytest.raises(ModelMismatch):
        sp.put_turns([other], user_id="z", model_id="some_other_model@v2")


def test_exemplar_set_is_capped(sp, rng):
    sp.policy.max_exemplars = 5
    a = voice(rng)
    for i in range(12):
        sp.put_turns([turn(utterance(rng, a), t=100.0 + i)], user_id="z")
    assert len(sp._exemplars(sp.get("spk_001", "z")["id"])) == 5


def test_merge_moves_turns_and_old_label_still_resolves(sp, rng):
    a, b = voice(rng), voice(rng)
    sp.put_turns([turn(utterance(rng, a), t=100.0)], user_id="z")
    sp.put_turns([turn(utterance(rng, b), t=200.0)], user_id="z")

    out = sp.merge("spk_002", "spk_001", user_id="z", reason="same person")
    assert out["turns_moved"] == 1
    assert sp.get("spk_001", "z")["turn_count"] == 2
    assert sp.get("spk_002", "z")["status"] == "archived"
    # historical text referring to spk_002 must still land on the survivor
    assert sp.resolve_label("spk_002", "z") == "spk_001"


def test_split_separates_two_voices_wrongly_merged(sp, rng):
    """The reason turn embeddings are kept: a bad merge stays undoable."""
    a, b = voice(rng), voice(rng)
    sp.put_turns([turn(utterance(rng, a), t=100.0)], user_id="z")
    sp.put_turns([turn(utterance(rng, b), t=200.0)], user_id="z")
    for i in range(3):
        sp.put_turns([turn(utterance(rng, a), t=300.0 + i)], user_id="z")
        sp.put_turns([turn(utterance(rng, b), t=400.0 + i)], user_id="z")
    sp.merge("spk_002", "spk_001", user_id="z")
    assert sp.get("spk_001", "z")["turn_count"] == 8

    out = sp.split("spk_001", user_id="z")
    assert out["turns_moved"] == 4
    assert sp.get("spk_001", "z")["turn_count"] == 4


def test_forget_erases_every_trace(sp, rng):
    a = voice(rng)
    for i in range(3):
        sp.put_turns([turn(utterance(rng, a), t=100.0 + i)], user_id="z")
    sid = sp.get("spk_001", "z")["id"]
    out = sp.forget("spk_001", user_id="z")
    assert out["turns_deleted"] == 3
    for table in ("speaker_turns", "speaker_exemplars", "speaker_centroids"):
        n = sp._conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE speaker_id=?", (sid,)).fetchone()[0]
        assert n == 0, table
    assert sp.get("spk_001", "z") is None


def test_export_gives_the_tool_centroids_only(sp, rng):
    """What the audio tool receives: enough to route a recording, never enough to
    decide who someone is."""
    a, b = voice(rng), voice(rng)
    for i in range(3):
        sp.put_turns([turn(utterance(rng, a), t=100.0 + i)], user_id="z")
        sp.put_turns([turn(utterance(rng, b), t=200.0 + i)], user_id="z")
    sp.set_wearer("spk_001", user_id="z")
    sp.promote(user_id="z")

    payload = sp.export_known(user_id="z", status=("active", "pending"))
    assert payload["model_id"] == MODEL and payload["dim"] == DIM
    wearer = [s for s in payload["speakers"] if s["is_wearer"]]
    assert len(wearer) == 1 and wearer[0]["label"] == "spk_001"
    # centroid round-trips as a usable unit vector
    from radiomind.storage.speakers import decode_embedding
    v = decode_embedding(wearer[0]["centroid"])
    assert len(v) == DIM and abs(float(np.linalg.norm(v)) - 1.0) < 1e-5
    assert "embedding" not in wearer[0] and "turns" not in wearer[0]


def test_manual_reports_policy_and_uncalibrated_state(sp):
    m = sp.manual(user_id="z")
    assert m["namespace"] == "speakers"
    assert {"division_of_labor", "coverage", "policy", "health", "maintenance"} <= m.keys()
    assert m["calibration"]["calibrated"] is False   # shipped thresholds are placeholders
    assert "t_high" in m["policy"]


# --- asking the owner (AskIdentity) -------------------------------------------

def establish(sp, rng, base, *, src, t0):
    """Feed enough turns across two days that `promote` accepts this as a person."""
    for i in range(6):
        sp.put_turns([turn(utterance(rng, base), t=t0 + i, date="2026-08-03", src=src)],
                     user_id="z")
    for i in range(6):
        sp.put_turns([turn(utterance(rng, base), t=t0 + 500 + i, date="2026-08-04", src=src)],
                     user_id="z")


def twins(sp, rng):
    """Two ACTIVE identities that sound like the same person.

    This state is reachable in production when each was minted at a moment the
    other was not in the matching pool — how spk_008 and spk_001 ended up 0.888
    apart on the real gallery. Here the first is parked while the second forms,
    so every turn still travels the real matching path.
    """
    base = voice(rng)
    establish(sp, rng, base, src="a.wav", t0=100.0)
    park(sp, "spk_001")
    establish(sp, rng, base, src="b.wav", t0=9000.0)
    sp._conn.execute("UPDATE speakers SET status='pending' WHERE user_id='z' AND label='spk_001'")
    sp.promote(user_id="z")
    return base, "spk_001", "spk_002"


def park(sp, label, status="archived"):
    """Hide one identity from the matching pool so turns land on the other."""
    sp._conn.execute(
        "UPDATE speakers SET status=? WHERE user_id='z' AND label=?", (status, label))


def test_twins_are_proposed_as_a_merge(sp, rng):
    """The fixture itself must reproduce the real situation, or the rest proves nothing."""
    _base, a, b = twins(sp, rng)
    for label in (a, b):
        assert sp.get(label, "z")["status"] == "active"
    cands = sp.merge_candidates(user_id="z")
    assert len(cands) == 1 and {cands[0]["a"], cands[0]["b"]} == {a, b}


def test_mark_distinct_stops_the_pair_coming_back(sp, rng):
    """Without this the owner is asked the same question every scan."""
    _base, a, b = twins(sp, rng)
    assert sp.merge_candidates(user_id="z")

    out = sp.mark_distinct(b, a, user_id="z")          # answered in either order
    assert out["distinct"] is True
    assert sp.merge_candidates(user_id="z") == []
    assert not [q for q in sp.pending_questions(user_id="z")["questions"]
                if q["kind"] == "merge"]


def test_mark_distinct_rejects_nonsense(sp, rng):
    _base, a, _ = twins(sp, rng)
    assert "error" in sp.mark_distinct(a, a, user_id="z")
    assert "error" in sp.mark_distinct(a, "spk_404", user_id="z")


def test_questions_never_reach_into_the_pending_pool(sp, rng):
    """Pending is where strangers land; asking the owner to name one is harassment."""
    _base, a, _ = twins(sp, rng)
    stranger = voice(rng)
    sp.put_turns([turn(utterance(rng, stranger), t=70000.0, src="c.wav")], user_id="z")
    passer_by = "spk_003"
    assert sp.get(passer_by, "z")["status"] == "pending"

    qs = sp.pending_questions(user_id="z")["questions"]
    assert qs, "the twins should still raise questions"
    assert all(passer_by not in q["subjects"] for q in qs)


def test_questions_carry_coordinates_not_audio(sp, rng):
    """Recordings stay on the capture machine; a question says where to listen."""
    twins(sp, rng)
    q = next(q for q in sp.pending_questions(user_id="z")["questions"] if q["kind"] == "merge")
    assert q["clips"], "a merge question without a listenable moment is unanswerable"
    for clip in q["clips"]:
        assert {"label", "source_file", "started_at", "ended_at"} <= clip.keys()
        assert "embedding" not in clip and "audio" not in clip
        assert isinstance(clip["started_at"], float)
    assert q["evidence"]["contexts"], "the owner needs wall-clock context to answer"


def test_question_ids_are_stable_so_a_restart_re_asks_nothing(sp, rng):
    twins(sp, rng)
    first = [q["id"] for q in sp.pending_questions(user_id="z")["questions"]]
    second = [q["id"] for q in sp.pending_questions(user_id="z")["questions"]]
    assert first == second and len(set(first)) == len(first)


def test_merge_question_applies_into_the_established_identity(sp, rng):
    """The label already used in generated text must be the one that survives."""
    base, a, b = twins(sp, rng)
    park(sp, a)                       # so the extra speech lands on b, not on a
    for i in range(4):
        sp.put_turns([turn(utterance(rng, base), t=20000.0 + i, date="2026-08-05",
                           src="c.wav")], user_id="z")
    park(sp, a, status="active")
    assert sp.get(b, "z")["total_speech_s"] > sp.get(a, "z")["total_speech_s"]

    q = next(q for q in sp.pending_questions(user_id="z")["questions"] if q["kind"] == "merge")
    assert q["subjects"] == [a, b]    # the quieter identity is the one that gets absorbed
    assert q["apply"]["same"] == f"speakers merge {a} {b}"
    assert q["apply"]["diff"] == f"speakers mark-distinct {a} {b}"
    assert q["id"] == f"merge:{a}:{b}"


def test_the_wearer_survives_a_merge_however_little_they_said(sp, rng):
    """The wearer is an anchor the owner set by hand and the audio pipeline reads:
    with no wearer centroid in the exported gallery, conversation and ambient media
    stop being separable and the owner vanishes from every future participants list.
    Direction must not be decided by a speech-time tally."""
    base, a, b = twins(sp, rng)
    park(sp, a)                        # the extra speech lands on b, so a is quieter
    for i in range(4):
        sp.put_turns([turn(utterance(rng, base), t=30000.0 + i, date="2026-08-05",
                           src="d.wav")], user_id="z")
    park(sp, a, status="active")
    sp.set_wearer(a, user_id="z")      # ...and the quieter one is the wearer
    assert sp.get(a, "z")["total_speech_s"] < sp.get(b, "z")["total_speech_s"]

    q = next(q for q in sp.pending_questions(user_id="z")["questions"] if q["kind"] == "merge")
    assert q["apply"]["same"] == f"speakers merge {b} {a}", "the wearer must be the survivor"

    out = sp.merge(b, a, user_id="z")
    assert out["turns_moved"] > 0
    assert sp.get(a, "z")["is_wearer"] == 1


def test_merging_the_wearer_away_still_keeps_a_wearer(sp, rng):
    """Belt to the direction rule's braces: whatever a caller asks for, the flag
    must not evaporate — `speakers merge` is executed straight off a button press,
    with no confirmation step in between."""
    _base, a, b = twins(sp, rng)
    sp.set_wearer(a, user_id="z")
    out = sp.merge(a, b, user_id="z")          # absorb the wearer on purpose
    assert out["wearer_moved_to"] == b
    assert sp.get(b, "z")["is_wearer"] == 1
    assert sp.get(a, "z")["is_wearer"] == 0
    wearers = [s for s in sp.list_speakers(user_id="z") if s["is_wearer"]]
    assert len(wearers) == 1 and wearers[0]["label"] == b


def test_named_people_are_not_asked_about_again(sp, rng):
    _base, a, b = twins(sp, rng)
    assert {q["id"] for q in sp.pending_questions(user_id="z")["questions"]} >= {
        f"name:{a}", f"name:{b}"}
    sp.name(a, "明月", user_id="z")
    assert f"name:{a}" not in {q["id"] for q in sp.pending_questions(user_id="z")["questions"]}


def test_name_candidates_turn_the_question_into_a_tap(sp, rng):
    """The point of harvesting names: an open question costs a keyboard, a
    yes/no one costs a tap."""
    _base, a, _b = twins(sp, rng)
    sp.set_name_candidates(a, [
        {"name": "明月", "confidence": 0.6, "strong": True, "support": 2,
         "episodes": [1, 2], "days": ["2026-08-03"]},
    ], user_id="z")

    q = next(q for q in sp.pending_questions(user_id="z")["questions"]
             if q["id"] == f"name:{a}")
    assert [o["key"] for o in q["options"]] == ["明月", "other", "skip"]
    assert q["apply"]["明月"] == f"speakers name {a} 明月"
    assert q["apply"]["skip"] == f"speakers ignore {a}"
    assert "{answer}" in q["apply"]["other"], "free text must still be possible"
    assert q["answer_type"] == "choice_or_text"
    assert q["evidence"]["name_candidates"][0]["episodes"] == [1, 2]


def test_a_weak_candidate_is_recorded_but_never_a_button(sp, rng):
    """Someone merely discussed while this speaker happened to be around. Offering
    them as a tap target invites a mis-tap that writes the wrong name — but the
    owner may still recognise the name, so the evidence keeps it."""
    _base, a, _b = twins(sp, rng)
    sp.set_name_candidates(a, [
        {"name": "庆松", "confidence": 0.3, "strong": False, "support": 1,
         "episodes": [3], "days": ["2026-08-04"]},
    ], user_id="z")

    q = next(q for q in sp.pending_questions(user_id="z")["questions"]
             if q["id"] == f"name:{a}")
    assert [o["key"] for o in q["options"]] == ["skip"]   # no name button, no "都不是"
    assert "庆松" not in q["apply"]
    assert q["answer_type"] == "text"
    assert q["evidence"]["name_candidates"][0]["name"] == "庆松"


def test_naming_someone_retires_their_question(sp, rng):
    _base, a, _b = twins(sp, rng)
    sp.set_name_candidates(a, [{"name": "明月", "confidence": 0.6, "strong": True}], user_id="z")
    sp.name(a, "明月", user_id="z")
    assert f"name:{a}" not in {q["id"] for q in sp.pending_questions(user_id="z")["questions"]}


def test_ignored_people_are_never_asked_about_or_promoted(sp, rng):
    _base, a, b = twins(sp, rng)
    sp.ignore(b, user_id="z")
    qs = sp.pending_questions(user_id="z")["questions"]
    assert all(b not in q["subjects"] for q in qs)
    assert sp.merge_candidates(user_id="z") == []
    assert sp.get(b, "z")["status"] == "ignored"


def test_ignoring_someone_still_recognises_them(sp, rng):
    """The point of `ignore` is silence, not amnesia. If an ignored voice stopped
    matching, their next turn would mint a fresh identity and the nagging would
    start over under a new label."""
    base = voice(rng)
    establish(sp, rng, base, src="a.wav", t0=100.0)
    sp.promote(user_id="z")
    sp.ignore("spk_001", user_id="z")
    before = sp.get("spk_001", "z")["turn_count"]

    sp.put_turns([turn(utterance(rng, base), t=60000.0, src="d.wav")], user_id="z")
    assert sp.get("spk_001", "z")["turn_count"] == before + 1
    assert sp.get("spk_002", "z") is None, "an ignored person must not respawn as a new id"


def test_ignore_refuses_the_wearer(sp, rng):
    establish(sp, rng, voice(rng), src="a.wav", t0=100.0)
    sp.set_wearer("spk_001", user_id="z")
    assert "error" in sp.ignore("spk_001", user_id="z")
    assert sp.get("spk_001", "z")["status"] == "active"


def test_present_between_answers_who_was_in_the_room(sp, rng):
    """Where an episode's participants should come from — voice identity survives
    across transcript chunks, invented speaker names do not."""
    a, b = voice(rng), voice(rng)
    for i in range(6):
        sp.put_turns([turn(utterance(rng, a), t=1000.0 + i * 30, src="m.wav")], user_id="z")
    for i in range(6):
        sp.put_turns([turn(utterance(rng, b), t=5000.0 + i * 30, src="m.wav")], user_id="z")
    sp._conn.execute("UPDATE speakers SET status='active' WHERE user_id='z'")

    early = sp.present_between(900.0, 1300.0, user_id="z")
    assert [p["label"] for p in early["present"]] == ["spk_001"]
    both = sp.present_between(900.0, 6000.0, user_id="z")
    assert {p["label"] for p in both["present"]} == {"spk_001", "spk_002"}
    assert both["present"][0]["speech_s"] >= both["present"][-1]["speech_s"]  # loudest first


def test_present_between_falls_back_to_a_whole_day(sp, rng):
    """Real episodes carry the clock string "不确定" and started_at = 0, so an
    epoch-only query would answer nothing for exactly the ones that need it."""
    for i in range(4):
        sp.put_turns([turn(utterance(rng, voice(rng)), t=1000.0 + i * 30,
                           date="2026-08-06", src="m.wav")], user_id="z")
    sp._conn.execute("UPDATE speakers SET status='active' WHERE user_id='z'")
    assert sp.present_between(user_id="z", date="2026-08-06")["present"]
    assert sp.present_between(user_id="z", date="2026-08-07")["present"] == []


def test_present_between_counts_what_it_could_not_attribute(sp, rng):
    """A caller must be able to tell "nobody else was there" from "I couldn't tell"."""
    a = voice(rng)
    sp.put_turns([turn(utterance(rng, a), t=1000.0, src="m.wav")], user_id="z")
    sp._conn.execute("UPDATE speakers SET status='active' WHERE user_id='z'")
    # a turn too short to bind to anyone still happened in the room
    sp.put_turns([turn(utterance(rng, voice(rng)), t=1100.0, speech_s=1.0, src="m.wav")],
                 user_id="z")
    out = sp.present_between(900.0, 2000.0, user_id="z")
    assert [p["label"] for p in out["present"]] == ["spk_001"]
    assert out["unbound_turns"] == 1


def test_present_between_leaves_the_television_out(sp, rng):
    tv = voice(rng)
    sp.put_turns([turn(utterance(rng, tv), t=1000.0, region="media", src="m.wav")], user_id="z")
    out = sp.present_between(900.0, 2000.0, user_id="z")
    assert out["present"] == [] and out["unbound_turns"] == 0


def test_a_schema_7_database_upgrades_in_place(sp, rng):
    """Production is already living at v7 with real turns in it, so v8 has to be an
    addition on top of existing data — not something that only works on a fresh DB."""
    from radiomind.storage.migrations import CURRENT_SCHEMA_VERSION, apply_migrations

    establish(sp, rng, voice(rng), src="a.wav", t0=100.0)
    before = sp.stats(user_id="z")["turns"]

    # Rewind to the shape a v7 deployment is in, then migrate forward again.
    sp._conn.execute("DROP TABLE speaker_distinct")
    sp._conn.execute("UPDATE schema_version SET version=7")
    sp._conn.commit()

    assert apply_migrations(sp._conn) == CURRENT_SCHEMA_VERSION >= 8
    assert sp.stats(user_id="z")["turns"] == before, "migration must not touch the turns"
    assert sp.mark_distinct("spk_001", "spk_001", user_id="z")["error"]  # table is usable


def test_forget_also_drops_the_distinct_pairs(sp, rng):
    _base, a, b = twins(sp, rng)
    sp.mark_distinct(a, b, user_id="z")
    sp.forget(a, user_id="z")
    assert sp._conn.execute("SELECT COUNT(*) FROM speaker_distinct").fetchone()[0] == 0


def test_merging_into_an_already_merged_label_follows_the_tombstone(sp, rng):
    """Two questions can share a subject, and a button press executes a command
    composed before the other one was answered. If spk_008 was already absorbed,
    "merge spk_001 into spk_008" must land on whoever spk_008 became — otherwise
    a thousand turns get repointed onto an archived identity and vanish from the
    gallery."""
    a, b, c = voice(rng), voice(rng), voice(rng)
    for i in range(3):
        sp.put_turns([turn(utterance(rng, a), t=100.0 + i, src="a.wav")], user_id="z")
        sp.put_turns([turn(utterance(rng, b), t=200.0 + i, src="b.wav")], user_id="z")
        sp.put_turns([turn(utterance(rng, c), t=300.0 + i, src="c.wav")], user_id="z")
    sp._conn.execute("UPDATE speakers SET status='active' WHERE user_id='z'")

    sp.merge("spk_002", "spk_003", user_id="z")        # spk_002 becomes spk_003
    out = sp.merge("spk_001", "spk_002", user_id="z")  # a stale question fires

    assert sp.get("spk_003", "z")["turn_count"] == 9, "everything must land on the survivor"
    assert out["into"] == "spk_003"
    assert sp.get("spk_001", "z")["status"] == "archived"


def test_answering_the_same_merge_twice_is_not_an_error(sp, rng):
    """A duplicate tap, or two questions that turn out to say the same thing,
    should report "already done" rather than fail — the owner pressed a button."""
    a, b = voice(rng), voice(rng)
    for i in range(3):
        sp.put_turns([turn(utterance(rng, a), t=100.0 + i, src="a.wav")], user_id="z")
        sp.put_turns([turn(utterance(rng, b), t=200.0 + i, src="b.wav")], user_id="z")
    sp.merge("spk_002", "spk_001", user_id="z")
    out = sp.merge("spk_002", "spk_001", user_id="z")
    assert out["already_merged"] is True and out["turns_moved"] == 0
    assert sp.get("spk_001", "z")["turn_count"] == 6
