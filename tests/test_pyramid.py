"""Tests for L2 pyramid search."""

import pytest

from radiomind.core.types import MemoryEntry, MemoryLevel
from radiomind.storage.database import MemoryStore
from radiomind.storage.pyramid import PyramidSearch


@pytest.fixture
def store_with_data(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    store.open()

    # Build a small pyramid
    p_id = store.add(MemoryEntry(
        content="user values autonomy and independence",
        domain="meta", level=MemoryLevel.PRINCIPLE,
    ))
    pat1_id = store.add(MemoryEntry(
        content="user prefers building own tools over using existing ones",
        domain="meta", level=MemoryLevel.PATTERN, parent_id=p_id,
    ))
    pat2_id = store.add(MemoryEntry(
        content="user dislikes being rushed by deadlines",
        domain="meta", level=MemoryLevel.PATTERN, parent_id=p_id,
    ))
    store.add(MemoryEntry(
        content="refused to use library X, wrote own parser instead",
        domain="meta", level=MemoryLevel.FACT, parent_id=pat1_id,
    ))
    store.add(MemoryEntry(
        content="complained about tight deadline on project Y",
        domain="meta", level=MemoryLevel.FACT, parent_id=pat2_id,
    ))

    # Add some health domain facts
    store.add(MemoryEntry(
        content="running every morning improves sleep quality",
        domain="health", level=MemoryLevel.FACT,
    ))
    store.add(MemoryEntry(
        content="user sleeps better after exercise",
        domain="health", level=MemoryLevel.PATTERN,
    ))

    yield store
    store.close()


def test_basic_search(store_with_data):
    ps = PyramidSearch(store_with_data)
    results = ps.search("autonomy")
    assert len(results) > 0
    assert any("autonomy" in r.entry.content for r in results)


def test_search_domain_filter(store_with_data):
    ps = PyramidSearch(store_with_data)
    results = ps.search("sleep", domain="health")
    assert all(r.entry.domain == "health" for r in results)


def test_pyramid_search_drill_down(store_with_data):
    ps = PyramidSearch(store_with_data)
    results = ps.search_pyramid("tools building")
    # Should find principle → expand to patterns → expand to facts
    levels_found = {r.entry.level for r in results}
    assert len(results) > 0


def test_drill_down(store_with_data):
    ps = PyramidSearch(store_with_data)
    # Get the principle entry
    principles = store_with_data.list_by_level(MemoryLevel.PRINCIPLE)
    assert len(principles) > 0

    children = ps.drill_down(principles[0].id)
    assert len(children) == 2  # two patterns


def test_hit_count_updated(store_with_data):
    ps = PyramidSearch(store_with_data)
    results = ps.search("autonomy")
    assert len(results) > 0

    entry = store_with_data.get(results[0].entry.id)
    assert entry.hit_count > 0


def test_search_chinese(store_with_data):
    # Add Chinese content
    store_with_data.add(MemoryEntry(
        content="用户喜欢自己造轮子",
        domain="work", level=MemoryLevel.FACT,
    ))
    ps = PyramidSearch(store_with_data)
    results = ps.search("造轮子")
    assert len(results) > 0


def test_empty_search(store_with_data):
    ps = PyramidSearch(store_with_data)
    results = ps.search("xyznonexistent12345")
    assert len(results) == 0
