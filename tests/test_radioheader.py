"""Tests for RadioHeader adapter."""

import json
import pytest
from pathlib import Path

from radiomind.adapters.radioheader import (
    RadioHeaderAdapter,
    parse_shortwave_file,
    parse_topic_file,
)
from radiomind.core.config import Config
from radiomind.core.mind import RadioMind


@pytest.fixture
def mock_rh_home(tmp_path):
    """Create a mock RadioHeader directory structure."""
    rh = tmp_path / "radioheader"
    (rh / "topics").mkdir(parents=True)
    (rh / "shortwave").mkdir(parents=True)

    # Create topic file
    (rh / "topics" / "ios-swiftui.md").write_text(
        "# iOS SwiftUI 经验\n\n"
        "## Concurrency\n\n"
        "[source:Seee] MainActor 隔离导致 UI 更新延迟，需要在 Task 中显式切换。\n"
        "[source:DarkWriting] SwiftUI 的 onChange 在 iOS 17 中签名变了。\n"
        "\n## Performance\n\n"
        "[source:Seee] LazyVStack 在大列表中比 List 性能更好。\n",
        encoding="utf-8",
    )

    # Create shortwave file
    (rh / "shortwave" / "sw-ios-mainactor-isolation.md").write_text(
        "---\n"
        "id: sw-ios-mainactor-isolation\n"
        "domain: iOS, SwiftUI, Concurrency\n"
        "tags: MainActor | 隔离 | UI更新 | Task | 延迟\n"
        "refs: topics/ios-swiftui.md\n"
        "---\n\n"
        "### MainActor 隔离导致 UI 延迟\n\n"
        "context: SwiftUI 视图更新时使用 async/await\n"
        "symptom: UI 更新延迟或卡顿\n"
        "fix:\n"
        "  - 在 Task 中显式使用 @MainActor\n"
        "  - 避免在非主线程更新 @Published 属性\n",
        encoding="utf-8",
    )

    # Create project registry
    (rh / "project-registry.json").write_text(
        json.dumps({
            "version": 1,
            "projects": [
                {
                    "name": "Seee",
                    "tech_stack": "iOS/SwiftUI",
                    "path": "~/DarkForce/Seee",
                    "domains": ["iOS", "SwiftUI"],
                    "problems": ["白屏", "性能"],
                    "activity": 0.8,
                },
                {
                    "name": "HomeGenie",
                    "tech_stack": "Rust",
                    "path": "~/DarkForce/HomeGenie",
                    "domains": ["Rust", "NPU"],
                    "problems": ["RKLLM"],
                    "activity": 0.5,
                },
            ],
        }),
        encoding="utf-8",
    )

    return rh


@pytest.fixture
def mind(tmp_path):
    cfg = Config()
    cfg.set("general.home", str(tmp_path / ".radiomind"))
    m = RadioMind(config=cfg)
    m.initialize()
    yield m
    m.shutdown()


class TestTopicParsing:
    def test_parse_with_source_tags(self, mock_rh_home):
        entries = parse_topic_file(mock_rh_home / "topics" / "ios-swiftui.md")
        assert len(entries) == 3
        assert entries[0]["source_project"] == "Seee"
        assert "MainActor" in entries[0]["content"]
        assert entries[0]["section"] == "Concurrency"

    def test_parse_sections(self, mock_rh_home):
        entries = parse_topic_file(mock_rh_home / "topics" / "ios-swiftui.md")
        sections = {e["section"] for e in entries}
        assert "Concurrency" in sections
        assert "Performance" in sections


class TestShortwaveParsing:
    def test_parse_yaml_frontmatter(self, mock_rh_home):
        parsed = parse_shortwave_file(mock_rh_home / "shortwave" / "sw-ios-mainactor-isolation.md")
        assert parsed is not None
        assert parsed["id"] == "sw-ios-mainactor-isolation"
        assert "iOS" in parsed["domain"]
        assert "MainActor" in parsed["tags"]
        assert parsed["refs"] == "topics/ios-swiftui.md"

    def test_parse_body_fields(self, mock_rh_home):
        parsed = parse_shortwave_file(mock_rh_home / "shortwave" / "sw-ios-mainactor-isolation.md")
        assert "async/await" in parsed["context"]
        assert "延迟" in parsed["symptom"]
        assert "@MainActor" in parsed["fix"]


class TestMigration:
    def test_full_migration(self, mind, mock_rh_home):
        adapter = RadioHeaderAdapter(mind, radioheader_home=mock_rh_home)
        result = adapter.migrate()

        assert result.topics_imported == 3
        assert result.shortwave_imported == 1
        assert result.projects_imported == 2
        assert len(result.errors) == 0

    def test_dedup_on_remigrate(self, mind, mock_rh_home):
        adapter = RadioHeaderAdapter(mind, radioheader_home=mock_rh_home)
        result1 = adapter.migrate()
        result2 = adapter.migrate()

        assert result2.topics_imported == 0
        assert result2.skipped_duplicates > 0

    def test_domain_inference(self, mind, mock_rh_home):
        adapter = RadioHeaderAdapter(mind, radioheader_home=mock_rh_home)
        adapter.migrate()

        stats = mind.stats()
        domain_names = [d["name"] for d in stats["domains"]]
        assert "ios" in domain_names or "projects" in domain_names


class TestSearchBridge:
    def test_search_returns_radioheader_format(self, mind, mock_rh_home):
        adapter = RadioHeaderAdapter(mind, radioheader_home=mock_rh_home)
        adapter.migrate()

        result = adapter.search("MainActor")
        assert "query" in result
        assert "count" in result
        assert "results" in result
        assert result["backend"] == "radiomind"
        assert result["count"] > 0

    def test_search_finds_shortwave(self, mind, mock_rh_home):
        adapter = RadioHeaderAdapter(mind, radioheader_home=mock_rh_home)
        adapter.migrate()

        result = adapter.search("symptom")
        assert result["count"] > 0


class TestConsolidateBridge:
    def test_consolidate_writes_digest(self, mind, mock_rh_home):
        adapter = RadioHeaderAdapter(mind, radioheader_home=mock_rh_home)
        adapter.migrate()

        digest_path = mock_rh_home / "context-digest.md"
        result = adapter.consolidate()

        assert digest_path.exists()
        content = digest_path.read_text()
        assert "环境认知摘要" in content
        assert "RadioMind" in content
