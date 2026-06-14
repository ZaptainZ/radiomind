"""RetrievalUX-1a: retrieval tier detection + conditional reranker advice.

Positions embedding as the recommended local enhancement and the reranker as a
conditionally-recommended advanced local option. Pure functions + onboard/doctor
copy. Deterministic — env detection is monkeypatched, never the real machine.
"""
from __future__ import annotations

from click.testing import CliRunner

from radiomind.cli.main import _render_retrieval_tier, _config_template, cli
from radiomind.core.config import Config
from radiomind.core import retrieval_tier as rt


# ----------------------------- tier detection -----------------------------

def _cfg(consent=False):
    c = Config()
    if consent:
        c.set("retrieval.remote", {"consent": True})
    return c


def test_tier_fts_only():
    t = rt.detect_retrieval_tier(_cfg(), embedding_installed=False,
                                 reranker_installed=False, remote_consented=False)
    assert t["tier"] == "FTS-only (+ typed-facet fallback)"


def test_tier_local_embedding():
    t = rt.detect_retrieval_tier(_cfg(), embedding_installed=True,
                                 reranker_installed=False, remote_consented=False)
    assert t["tier"] == "local embedding"


def test_tier_embedding_plus_reranker():
    t = rt.detect_retrieval_tier(_cfg(), embedding_installed=True,
                                 reranker_installed=True, remote_consented=False)
    assert t["tier"] == "local embedding + local reranker"


def test_tier_remote_consented_wins():
    # consent classifies as remote even with local installed
    t = rt.detect_retrieval_tier(_cfg(), embedding_installed=True,
                                 reranker_installed=True, remote_consented=True)
    assert t["tier"] == "remote (consented)"


# ----------------------- reranker env recommendation -----------------------

def test_reranker_recommended_apple_silicon():
    r = rt.local_reranker_recommendation(machine="arm64", system="Darwin",
                                         free_bytes=50 * rt._GB)
    assert r["recommended"] is True
    assert r["install_command"] == rt.RERANKER_INSTALL


def test_reranker_skipped_low_disk():
    r = rt.local_reranker_recommendation(machine="arm64", system="Darwin",
                                         free_bytes=2 * rt._GB)
    assert r["recommended"] is False
    assert r["install_command"] is None
    assert "skipped for this machine" in r["reason"]


def test_reranker_nonarm_needs_generous_disk():
    low = rt.local_reranker_recommendation(machine="x86_64", system="Linux",
                                           free_bytes=6 * rt._GB)
    assert low["recommended"] is False  # 6GB > 5GB min but < 8GB non-arm bar
    high = rt.local_reranker_recommendation(machine="x86_64", system="Linux",
                                            free_bytes=20 * rt._GB)
    assert high["recommended"] is True


def test_reranker_reason_is_reassuring_not_scary():
    r = rt.local_reranker_recommendation(machine="x86_64", system="Linux",
                                         free_bytes=6 * rt._GB)
    # "skipped", not a warning/error tone
    assert "skipped" in r["reason"].lower()
    assert "error" not in r["reason"].lower() and "fail" not in r["reason"].lower()


# ----------------------------- onboard copy -----------------------------

def _state(tier, emb, rr, reco, consent=False):
    return {"retrieval_tier": tier, "embedding_installed": emb,
            "reranker_installed": rr, "reranker_reco": reco,
            "remote_retrieval_consent": consent}


def test_onboard_recommends_embedding_when_fts_only():
    reco = {"recommended": True, "install_command": rt.RERANKER_INSTALL,
            "estimated_disk": rt.RERANKER_DISK_EST, "reason": "ok"}
    body = "\n".join(_render_retrieval_tier(
        _state("FTS-only (+ typed-facet fallback)", False, False, reco)))
    assert "FTS-only" in body
    assert rt.EMBEDDING_INSTALL in body
    assert "text never leaves your machine" in body


def test_onboard_no_embedding_nudge_when_installed():
    reco = {"recommended": True, "install_command": rt.RERANKER_INSTALL,
            "estimated_disk": rt.RERANKER_DISK_EST, "reason": "ok"}
    body = "\n".join(_render_retrieval_tier(
        _state("local embedding", True, False, reco)))
    assert rt.EMBEDDING_INSTALL not in body  # already installed
    assert rt.RERANKER_INSTALL in body       # still offers advanced


def test_onboard_reranker_skip_is_quiet_when_unsuitable():
    reco = {"recommended": False, "install_command": None,
            "estimated_disk": rt.RERANKER_DISK_EST,
            "reason": "advanced reranker skipped for this machine (only ~2GB free)"}
    body = "\n".join(_render_retrieval_tier(
        _state("local embedding", True, False, reco)))
    assert "skipped for this machine" in body
    assert rt.RERANKER_INSTALL not in body  # don't push the install command


def test_onboard_remote_consented_no_local_nudges():
    body = "\n".join(_render_retrieval_tier(
        _state("remote (consented)", False, False, None, consent=True)))
    assert rt.EMBEDDING_INSTALL not in body  # consented users aren't nudged to local


# --------------------- live onboard + config template ---------------------

def test_onboard_live_shows_tier(monkeypatch, tmp_path):
    monkeypatch.setenv("RADIOMIND_HOME", str(tmp_path / ".radiomind"))
    monkeypatch.setenv("RADIOMIND_REMOTE_RETRIEVAL", "0")
    result = CliRunner().invoke(cli, ["onboard"])
    assert result.exit_code == 0
    assert "retrieval tier:" in result.output


def test_config_template_remote_off_by_default(tmp_path):
    import tomllib
    parsed = tomllib.loads(_config_template(tmp_path / "rm"))
    assert parsed["retrieval"]["remote"]["consent"] is False
