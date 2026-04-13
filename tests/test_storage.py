"""Tests for L2 SQLite storage."""

import pytest

from radiomind.core.types import MemoryEntry, MemoryLevel, MemoryStatus
from radiomind.storage.database import MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "test.db")
    s.open()
    yield s
    s.close()


def test_add_and_get(store):
    entry = MemoryEntry(content="user likes running", domain="health")
    mid = store.add(entry)
    assert mid > 0

    got = store.get(mid)
    assert got is not None
    assert got.content == "user likes running"
    assert got.domain == "health"
    assert got.level == MemoryLevel.FACT


def test_update(store):
    entry = MemoryEntry(content="original", domain="work")
    mid = store.add(entry)

    entry.content = "updated"
    store.update(entry)

    got = store.get(mid)
    assert got.content == "updated"


def test_delete(store):
    entry = MemoryEntry(content="temporary", domain="test")
    mid = store.add(entry)
    store.delete(mid)
    assert store.get(mid) is None


def test_list_by_domain(store):
    for i in range(5):
        store.add(MemoryEntry(content=f"fact {i}", domain="work", level=MemoryLevel.FACT))
    store.add(MemoryEntry(content="pattern", domain="work", level=MemoryLevel.PATTERN))
    store.add(MemoryEntry(content="other", domain="health"))

    work = store.list_by_domain("work")
    assert len(work) == 6

    facts = store.list_by_domain("work", level=MemoryLevel.FACT)
    assert len(facts) == 5


def test_list_by_level(store):
    store.add(MemoryEntry(content="fact", domain="a", level=MemoryLevel.FACT))
    store.add(MemoryEntry(content="principle", domain="b", level=MemoryLevel.PRINCIPLE))

    principles = store.list_by_level(MemoryLevel.PRINCIPLE)
    assert len(principles) == 1
    assert principles[0].content == "principle"


def test_parent_child(store):
    parent_id = store.add(
        MemoryEntry(content="user values autonomy", domain="meta", level=MemoryLevel.PRINCIPLE)
    )
    store.add(
        MemoryEntry(
            content="prefers building own tools",
            domain="meta",
            level=MemoryLevel.PATTERN,
            parent_id=parent_id,
        )
    )
    store.add(
        MemoryEntry(
            content="refused to use library X",
            domain="meta",
            level=MemoryLevel.FACT,
            parent_id=parent_id,
        )
    )

    children = store.get_children(parent_id)
    assert len(children) == 2


def test_search_fts(store):
    store.add(MemoryEntry(content="running improves sleep quality", domain="health"))
    store.add(MemoryEntry(content="coding in rust is fast", domain="work"))

    results = store.search_fts("sleep")
    assert len(results) == 1
    assert "sleep" in results[0].entry.content
    assert results[0].method == "fts"


def test_search_like(store):
    store.add(MemoryEntry(content="用户喜欢跑步", domain="health"))

    results = store.search_like("跑步")
    assert len(results) == 1
    assert results[0].method == "like"


def test_hit_tracking(store):
    mid = store.add(MemoryEntry(content="test", domain="d"))
    store.record_hit(mid)
    store.record_hit(mid)

    got = store.get(mid)
    assert got.hit_count == 2
    assert got.last_hit_at > 0


def test_decay_and_archive(store):
    mid = store.add(MemoryEntry(content="old memory", domain="d"))
    for _ in range(3):
        store.increment_decay(mid)

    got = store.get(mid)
    assert got.decay_count == 3

    store.archive(mid)
    got = store.get(mid)
    assert got.status == MemoryStatus.ARCHIVED


def test_domains(store):
    store.add(MemoryEntry(content="a", domain="work"))
    store.add(MemoryEntry(content="b", domain="work"))
    store.add(MemoryEntry(content="c", domain="health"))

    domains = store.list_domains()
    assert len(domains) == 2
    work_domain = next(d for d in domains if d["name"] == "work")
    assert work_domain["memory_count"] == 2


def test_stats(store):
    store.add(MemoryEntry(content="f1", domain="d", level=MemoryLevel.FACT))
    store.add(MemoryEntry(content="f2", domain="d", level=MemoryLevel.FACT))
    store.add(MemoryEntry(content="p1", domain="d", level=MemoryLevel.PATTERN))

    stats = store.stats()
    assert stats["total_active"] == 3
    assert stats["by_level"]["fact"] == 2
    assert stats["by_level"]["pattern"] == 1
    assert stats["domain_count"] == 1


def test_count_by_domain_level(store):
    for i in range(12):
        store.add(MemoryEntry(content=f"fact {i}", domain="work", level=MemoryLevel.FACT))

    assert store.count_by_domain_level("work", MemoryLevel.FACT) == 12
    assert store.count_by_domain_level("work", MemoryLevel.PATTERN) == 0
