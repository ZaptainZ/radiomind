"""Tests for knowledge graph."""

import time
import pytest

from radiomind.storage.knowledge_graph import KnowledgeGraph


@pytest.fixture
def kg(tmp_path):
    g = KnowledgeGraph(tmp_path / "kg.db")
    g.open()
    yield g
    g.close()


def test_add_and_query(kg):
    kg.add_triple("user", "likes", "running")
    results = kg.query_entity("user")
    assert len(results) == 1
    assert results[0].object == "running"


def test_unique_relation_invalidates(kg):
    kg.add_triple("user", "works_at", "CompanyA")
    kg.add_triple("user", "works_at", "CompanyB")

    current = kg.query_entity("user")
    works = [t for t in current if t.relation == "works_at"]
    assert len(works) == 1
    # Canonicalization lowercases ASCII entity names
    assert works[0].object == "companyb"


def test_timeline(kg):
    kg.add_triple("user", "works_at", "CompanyA", valid_from=1000.0)
    time.sleep(0.01)
    kg.add_triple("user", "works_at", "CompanyB", valid_from=2000.0)

    timeline = kg.timeline("user")
    assert len(timeline) == 2
    assert timeline[0].object == "companya"
    assert timeline[1].object == "companyb"
    assert timeline[0].valid_until is not None  # invalidated


def test_query_at_time(kg):
    kg.add_triple("user", "works_at", "CompanyA", valid_from=1000.0)
    time.sleep(0.01)
    kg.add_triple("user", "works_at", "CompanyB", valid_from=2000.0)

    past = kg.query_entity("user", as_of=1500.0)
    assert len(past) == 1
    assert past[0].object == "companya"


def test_canonicalize_cn_suffixes(kg):
    kg.add_triple("user", "located_in", "杭州市")
    kg.add_triple("user", "works_at", "阿里巴巴公司")
    facts = kg.query_entity("user")
    objs = {t.object for t in facts}
    assert "杭州" in objs
    assert "阿里巴巴" in objs


def test_alias_rewrites_graph(kg):
    kg.add_triple("user", "likes", "apple")
    kg.add_alias("apple", "苹果公司")  # 苹果公司 → canonical "苹果"
    facts = kg.query_relation("user", "likes")
    assert any(t.object == "苹果" for t in facts)


def test_non_unique_relation(kg):
    kg.add_triple("user", "likes", "running")
    kg.add_triple("user", "likes", "reading")

    results = kg.query_entity("user")
    likes = [t for t in results if t.relation == "likes"]
    assert len(likes) == 2


def test_invalidate(kg):
    kg.add_triple("user", "likes", "coffee")
    kg.invalidate("user", "likes", "coffee")

    results = kg.query_entity("user")
    assert len(results) == 0


def test_extract_triples(kg):
    triples = kg.extract_triples_from_text("我叫小明")
    assert len(triples) >= 1
    assert triples[0] == ("user", "name_is", "小明")


def test_extract_work(kg):
    triples = kg.extract_triples_from_text("我在谷歌工作")
    assert any(t[1] == "works_at" for t in triples)


def test_extract_likes(kg):
    triples = kg.extract_triples_from_text("我喜欢跑步和游泳")
    assert any(t[1] == "likes" for t in triples)


def test_count(kg):
    kg.add_triple("a", "r", "b")
    kg.add_triple("c", "r", "d")
    assert kg.count() == 2
