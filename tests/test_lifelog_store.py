"""Life Log store (生活日志) — migration v6 + LifelogStore.

Self-contained: builds a minimal `memories` base table (created by database.py in
real use) then runs apply_migrations, so the test needs no DB fixture.
"""

import sqlite3

import pytest

from radiomind.storage.migrations import apply_migrations, CURRENT_SCHEMA_VERSION
from radiomind.storage.lifelog import LifelogStore, LifelogEpisode, DayProfile


@pytest.fixture
def store():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Base `memories` table (v1 lives in database.py, not migrations) so v2–v4 ALTERs apply.
    conn.execute(
        "CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "content TEXT NOT NULL DEFAULT '', level INTEGER DEFAULT 2, created_at REAL NOT NULL DEFAULT 0)"
    )
    assert apply_migrations(conn) == CURRENT_SCHEMA_VERSION >= 6
    return LifelogStore(conn)


def _ep(**kw):
    base = dict(date="2026-08-03", start_clock="20:15", end_clock="20:35",
               activity="找片源、订饭、观影前闲聊", participants=["我", "对方甲", "对方乙"],
               topics=["戒指样品", "哔哩哔哩付费"], media=["《复仇者联盟》"],
               summary="几人商量订饭并准备看电影", user_id="zaptain")
    base.update(kw)
    return LifelogEpisode(**base)


def test_migration_creates_lifelog_tables(store):
    tabs = {r[0] for r in store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"lifelog_episodes", "lifelog_day_profiles"} <= tabs


def test_topic_is_full_text_searchable(store):
    """The key improvement over `library`: a term that appears ONLY in topics
    (not in summary) is still found — library's FTS(title+summary) misses it."""
    store.put_episode(_ep())
    hits = store.search_episodes("戒指", user_id="zaptain")
    assert len(hits) == 1 and hits[0]["start_clock"] == "20:15"
    # sanity: summary text is searchable too
    assert store.search_episodes("订饭", user_id="zaptain")


def test_dedup_on_date_start(store):
    id1, dup1 = store.put_episode(_ep())
    id2, dup2 = store.put_episode(_ep())
    assert dup1 is False and dup2 is True and id1 == id2


def test_person_filter(store):
    store.put_episode(_ep())
    store.put_episode(_ep(start_clock="19:15", participants=["我", "对方甲"], topics=["猫"],
                          summary="到家收拾", activity="在家处理猫和食物"))
    assert [h["start_clock"] for h in store.search_episodes("", person="对方乙", user_id="zaptain")] == ["20:15"]


def test_day_profile_upsert(store):
    day = DayProfile(date="2026-08-03", narrative="居家看片马拉松", user_id="zaptain",
                     activities=["看片", "吃饭"], highlights=["看《复仇者联盟》"])
    id1, up1 = store.put_day(day)
    day.narrative = "改写后的叙述"
    id2, up2 = store.put_day(day)
    assert up1 is False and up2 is True and id1 == id2
    assert store.get_day("2026-08-03", "zaptain")["narrative"] == "改写后的叙述"


def test_stats(store):
    store.put_episode(_ep())
    assert store.stats("zaptain")["episodes"] == 1


def test_rerunning_a_rollup_does_not_repair_a_bad_episode(store):
    """Why deleting has to exist: dedup makes a re-run a no-op, so corrected
    content is silently dropped and the wrong episode survives."""
    store.put_episode(_ep(summary="模型编的内容"))
    eid, dup = store.put_episode(_ep(summary="重跑后的正确内容"))
    assert dup is True
    assert store.get_episode(eid)["summary"] == "模型编的内容"


def test_delete_episodes_is_a_dry_run_unless_told_otherwise(store):
    store.put_episode(_ep())
    out = store.delete_episodes(date="2026-08-03", user_id="zaptain")
    assert out["matched"] == 1 and out["deleted"] == 0 and out["dry_run"] is True
    assert store.stats("zaptain")["episodes"] == 1


def test_delete_episodes_keeps_search_from_returning_ghosts(store):
    """The FTS shadow table is maintained by hand — a raw SQL delete would leave
    search returning episodes that no longer exist."""
    store.put_episode(_ep())
    assert store.search_episodes("戒指", user_id="zaptain")
    out = store.delete_episodes(date="2026-08-03", user_id="zaptain", dry_run=False)
    assert out["deleted"] == 1
    assert store.search_episodes("戒指", user_id="zaptain") == []
    assert store.stats("zaptain")["episodes"] == 0


def test_delete_episodes_can_target_the_ones_whose_time_was_guessed(store):
    """`started_at = 0` is exactly the cohort of a "the clock times were made up"
    repair — production had 14 of 14 in that state."""
    store.put_episode(_ep(start_clock="不确定", end_clock="不确定"))
    store.put_episode(_ep(start_clock="09:00", started_at=1754200000.0))
    out = store.delete_episodes(only_unanchored=True, user_id="zaptain", dry_run=False)
    assert out["deleted"] == 1
    left = store.search_episodes("", user_id="zaptain")
    assert [e["start_clock"] for e in left] == ["09:00"]
