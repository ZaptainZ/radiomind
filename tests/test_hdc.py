"""Tests for L3 HDC habit storage."""

import numpy as np
import pytest

from radiomind.core.types import MemoryStatus
from radiomind.storage.hdc import (
    HDCCodebook,
    HabitStore,
    bind,
    bundle,
    similarity,
)


def test_random_hv_orthogonal():
    cb = HDCCodebook(dim=10000, seed=0)
    a = cb.get("apple")
    b = cb.get("banana")
    sim = similarity(a, b)
    assert abs(sim) < 0.05  # random vectors are near-orthogonal


def test_bind_self_inverse():
    cb = HDCCodebook(dim=10000, seed=0)
    a = cb.get("concept_a")
    b = cb.get("concept_b")
    bound = bind(a, b)
    recovered = bind(bound, b)
    assert similarity(recovered, a) > 0.95


def test_bundle_preserves_components():
    cb = HDCCodebook(dim=10000, seed=0)
    a = cb.get("x")
    b = cb.get("y")
    c = cb.get("z")
    bundled = bundle(a, b, c)
    assert similarity(bundled, a) > 0.2
    assert similarity(bundled, b) > 0.2
    assert similarity(bundled, c) > 0.2

    d = cb.get("unrelated")
    assert abs(similarity(bundled, d)) < 0.1


def test_habit_store_add_and_query(tmp_path):
    store = HabitStore(tmp_path / "hdc")
    store.open()

    store.add_habit("likes apples", [("fruit", "apple")])
    store.add_habit("likes oranges", [("fruit", "orange")])
    store.add_habit("reads books", [("hobby", "reading")])

    # query with bind pair matches the encoding method
    results = store.query_by_pairs([("fruit", "apple")], top_k=3)
    assert len(results) == 3
    assert results[0][0].description == "likes apples"
    assert results[0][1] > results[1][1]

    store.close()


def test_habit_store_persistence(tmp_path):
    data_dir = tmp_path / "hdc"

    store1 = HabitStore(data_dir)
    store1.open()
    store1.add_habit("test habit", [("a", "b")])
    store1.close()

    store2 = HabitStore(data_dir)
    store2.open()
    assert store2.count == 1
    assert store2.all_habits()[0].description == "test habit"
    store2.close()


def test_habit_confirm(tmp_path):
    store = HabitStore(tmp_path / "hdc")
    store.open()
    store.add_habit("candidate", [("x", "y")])

    assert store.all_habits()[0].status == MemoryStatus.CANDIDATE
    store.confirm(0)
    assert store.all_habits()[0].status == MemoryStatus.CONFIRMED
    assert store.all_habits()[0].verified_at is not None

    store.close()


def test_habit_remove(tmp_path):
    store = HabitStore(tmp_path / "hdc")
    store.open()
    store.add_habit("keep", [("a", "b")])
    store.add_habit("remove", [("c", "d")])
    assert store.count == 2

    store.remove(1)
    assert store.count == 1
    assert store.all_habits()[0].description == "keep"

    store.close()


def test_bundle_all_habits(tmp_path):
    store = HabitStore(tmp_path / "hdc")
    store.open()
    store.add_habit("h1", [("a", "b")])
    store.add_habit("h2", [("c", "d")])

    b = store.get_bundle()
    assert b is not None
    assert len(b) == store.dim

    store.close()


def test_codebook_persistence(tmp_path):
    cb1 = HDCCodebook(dim=1000, seed=42)
    v1 = cb1.get("hello")
    cb1.save(tmp_path / "cb.json")

    cb2 = HDCCodebook(dim=1000, seed=99)
    cb2.load(tmp_path / "cb.json")
    v2 = cb2.get("hello")

    assert np.array_equal(v1, v2)
