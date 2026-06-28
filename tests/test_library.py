"""Tests for the Knowledge Library (信息收集库) store — KnowledgeLibrary-2a."""

import pytest

from radiomind.storage.database import MemoryStore
from radiomind.storage.library import LibraryItem, LibraryStore, content_hash, normalize_url


@pytest.fixture
def lib(tmp_path):
    store = MemoryStore(tmp_path / "radiomind.db")
    store.open()  # runs migrations → library_* tables exist
    yield LibraryStore(store.conn)
    store.close()


def test_migration_created_library_tables(tmp_path):
    store = MemoryStore(tmp_path / "radiomind.db")
    store.open()
    tables = {r[0] for r in store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"library_items", "library_tags", "library_item_tags"} <= tables
    ver = store.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert ver >= 5
    store.close()


def test_normalize_url_strips_tracking_and_fragment():
    a = normalize_url("https://mp.weixin.qq.com/s/ABC?utm_source=x&id=1#ref")
    b = normalize_url("https://mp.weixin.qq.com/s/ABC?id=1")
    assert a == b
    assert "utm_source" not in a and "#" not in a


def test_put_get_roundtrip(lib):
    item = LibraryItem(title="3DGS in Apple Maps", source_url="https://e.test/a",
                       source_domain="e.test", short_summary="gaussian splatting",
                       key_points=["p1", "p2"], user_id="u1")
    iid, dup = lib.put_item(item)
    assert iid > 0 and dup is False
    got = lib.get_item(iid)
    assert got["title"] == "3DGS in Apple Maps"
    assert got["key_points"] == ["p1", "p2"]
    assert got["status"] == "active"


def test_dedup_by_url_and_hash(lib):
    lib.put_item(LibraryItem(title="A", source_url="https://e.test/x?utm_source=a",
                             content_hash=content_hash("body text here"), user_id="u1"))
    # same url with different tracking → duplicate
    iid, dup = lib.put_item(LibraryItem(title="A2", source_url="https://e.test/x?utm_source=b",
                                        user_id="u1"))
    assert dup is True
    # same content_hash, no url → duplicate
    iid2, dup2 = lib.put_item(LibraryItem(title="A3", source_url="",
                                          content_hash=content_hash("body text here"), user_id="u1"))
    assert dup2 is True
    assert lib.stats(user_id="u1")["items"] == 1


def test_faceted_tags_and_item_tags(lib):
    iid, _ = lib.put_item(LibraryItem(title="T", user_id="u1"))
    t1 = lib.upsert_tag("3D高斯泼溅", "method")
    t2 = lib.upsert_tag("Apple Maps", "product")
    lib.tag_item(iid, t1, 0.9, "llm")
    lib.tag_item(iid, t2, 1.0, "user")
    tags = lib.item_tags(iid)
    assert {t["name"] for t in tags} == {"3D高斯泼溅", "Apple Maps"}
    assert {t["facet"] for t in tags} == {"method", "product"}


def test_search_fts_and_tag_filter(lib):
    iid, _ = lib.put_item(LibraryItem(title="Gaussian Splatting", source_domain="e.test",
                                      short_summary="neural rendering at scale", user_id="u1"))
    tid = lib.upsert_tag("3DGS", "method")
    lib.tag_item(iid, tid)
    assert any(r["id"] == iid for r in lib.search_items("rendering", user_id="u1"))
    assert any(r["id"] == iid for r in lib.search_items("", tag="3DGS", user_id="u1"))
    assert lib.search_items("", tag="nonexistent", user_id="u1") == []


def test_merge_tag_repoints_and_aliases(lib):
    iid, _ = lib.put_item(LibraryItem(title="T", user_id="u1"))
    old = lib.upsert_tag("3DGS", "method")
    lib.tag_item(iid, old)
    canon = lib.merge_tag("3DGS", "3D高斯泼溅", "method")
    # item now carries the canonical tag, not the alias
    names = {t["name"] for t in lib.item_tags(iid)}
    assert "3D高斯泼溅" in names and "3DGS" not in names
    # alias resolves to canonical on future upserts
    assert lib.upsert_tag("3DGS", "method") == canon


def test_user_isolation_in_search(lib):
    a, _ = lib.put_item(LibraryItem(title="mine", short_summary="topic x", user_id="u1"))
    lib.put_item(LibraryItem(title="theirs", short_summary="topic x", user_id="u2"))
    res = lib.search_items("topic", user_id="u1")
    assert [r["id"] for r in res] == [a]
