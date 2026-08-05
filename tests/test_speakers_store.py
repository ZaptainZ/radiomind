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
