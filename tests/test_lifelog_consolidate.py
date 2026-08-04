"""Life-log consolidation (蒸馏升格) — context, parsing, and the write path.

Same self-contained DB approach as test_lifelog_store.py, plus a real MemoryStore
so the fact-writing path (dedup, supersede, archive) is exercised for real.
"""

import json

import pytest

from radiomind.refinement import lifelog_consolidate as lc
from radiomind.storage.database import MemoryStore
from radiomind.storage.lifelog import DayProfile, LifelogEpisode, LifelogStore


@pytest.fixture
def stores(tmp_path):
    store = MemoryStore(tmp_path / "radiomind.db")
    store.open()
    ll = LifelogStore(store.conn)
    ll.put_episode(LifelogEpisode(
        date="2026-08-03", start_clock="20:15", end_clock="20:35",
        activity="订饭、看电影", participants=["我", "对方甲"],
        topics=["复仇者联盟", "猫粮"], media=["《复仇者联盟》"],
        summary="两人订饭并商量给猫买粮", user_id="zaptain",
    ))
    ll.put_day(DayProfile(
        date="2026-08-03", narrative="晚上和同住的对方甲一起看漫威电影，顺便订了猫粮。",
        people=[{"label": "对方甲", "note": "同住"}], topics=["漫威", "猫"],
        activities=["观影"], highlights=["在追漫威系列"], user_id="zaptain",
    ))
    yield store, ll
    store.close()


RESPONSE = json.dumps({
    "facts": [
        {"content": "我和对方甲同住", "confidence": 0.8, "evidence": "2026-08-03 日画像"},
        {"content": "我养猫", "confidence": 0.9, "evidence": "订猫粮"},
        {"content": "我可能喜欢科幻", "confidence": 0.3, "evidence": "推测"},
    ],
    "habits": [{"description": "晚上看电影放松", "confidence": 0.8,
                "evidence": "8-03 晚观影", "falsifier": "连续两周晚上无观影记录"}],
    "entities": [{"subject": "我", "relation": "养", "object": "猫", "confidence": 0.9}],
}, ensure_ascii=False)


def test_context_covers_day_and_episodes(stores):
    store, ll = stores
    ctx = lc.build_context(ll, store=store, days=7, user_id="zaptain")
    assert ctx["dates"] == ["2026-08-03"]
    assert len(ctx["episodes"]) == 1
    prompt = lc.build_prompt(ctx)
    assert "同住的对方甲" in prompt and "猫粮" in prompt
    assert "(none yet)" in prompt  # nothing distilled before


def test_parse_response_tolerates_fence_and_prose():
    parsed = lc.parse_response("好的，结果如下：\n```json\n" + RESPONSE + "\n```")
    assert len(parsed["facts"]) == 3 and len(parsed["entities"]) == 1
    with pytest.raises(ValueError):
        lc.parse_response("抱歉，没有可提炼的内容。")


def test_apply_writes_facts_and_drops_low_confidence(stores):
    store, ll = stores
    summary = lc.apply_result(lc.parse_response(RESPONSE), store=store, ll=ll,
                              dates=["2026-08-03"], user_id="zaptain")
    assert summary["facts_written"] == 2      # 0.3 one dropped
    assert summary["facts_skipped"] == 1
    contents = {r[0] for r in store.conn.execute(
        "SELECT content FROM memories WHERE domain='lifelog' AND status='active'")}
    assert contents == {"我和对方甲同住", "我养猫"}


def test_consolidated_day_is_not_offered_again(stores):
    store, ll = stores
    lc.apply_result(lc.parse_response(RESPONSE), store=store, ll=ll,
                    dates=["2026-08-03"], user_id="zaptain")
    assert lc.build_context(ll, store=store, user_id="zaptain")["dates"] == []
    forced = lc.build_context(ll, store=store, user_id="zaptain", force=True)
    assert forced["dates"] == ["2026-08-03"]
    # ...and the second pass sees what the first one already wrote
    assert "我养猫" in lc.build_prompt(forced)


def test_rerun_dedups_and_supersede_archives_the_old_fact(stores):
    store, ll = stores
    lc.apply_result(lc.parse_response(RESPONSE), store=store, ll=ll,
                    dates=["2026-08-03"], user_id="zaptain")

    again = lc.apply_result(lc.parse_response(RESPONSE), store=store, ll=ll,
                            dates=["2026-08-03"], user_id="zaptain")
    assert again["facts_written"] == 0 and again["facts_duplicate"] == 2

    update = {"facts": [{"content": "我和对方甲不再同住", "confidence": 0.9,
                         "supersedes": "我和对方甲同住"}]}
    third = lc.apply_result(update, store=store, ll=ll, dates=[], user_id="zaptain")
    assert third["facts_superseded"] == 1
    status = store.conn.execute(
        "SELECT status FROM memories WHERE content='我和对方甲同住'").fetchone()[0]
    assert status == "archived"


def test_dry_run_writes_nothing(stores):
    store, ll = stores
    summary = lc.apply_result(lc.parse_response(RESPONSE), store=store, ll=ll,
                              dates=["2026-08-03"], user_id="zaptain", dry_run=True)
    assert summary["facts_written"] == 2 and summary["days_marked"] == 0
    assert store.conn.execute(
        "SELECT COUNT(*) FROM memories WHERE domain='lifelog'").fetchone()[0] == 0
