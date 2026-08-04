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
