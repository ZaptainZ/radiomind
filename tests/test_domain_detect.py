"""SmallUserReadiness-1c: domain classifier — word-boundary matching (no more
'work' in 'network') + minimal technical domains. Deterministic, no LLM.
"""
from __future__ import annotations

from radiomind.core.gate import detect_domain


# ---------------- substring false-positive fixed ----------------

def test_network_not_work():
    assert detect_domain("when i build network services") != "work"


def test_workflow_not_work():
    assert detect_domain("my workflow is messy today") != "work"


def test_real_work_still_matches():
    assert detect_domain("work project deadline meeting") == "work"


def test_workout_is_health_not_work():
    # 'workout' must not trip the 'work' keyword via substring
    assert detect_domain("my morning workout routine") == "health"


# ---------------- technical domains land somewhere ----------------

def test_parsers_adapters_software():
    assert detect_domain("I write parsers by hand and prefer adapters") == "software"


def test_networking_domain():
    assert detect_domain("retry with exponential backoff and a circuit breaker") == "networking"


def test_ai_domain():
    assert detect_domain("layered fallbacks for ai inference") == "ai"


def test_rust_domain():
    assert detect_domain("the borrow checker and serde lifetimes") == "rust"


def test_ios_domain():
    assert detect_domain("swiftui views in xcode") == "ios"


# ---------------- non-technical content unaffected ----------------

def test_lifestyle_unaffected():
    assert detect_domain("I go running every morning for exercise") == "health"
    assert detect_domain("I love travel and photography") == "hobby"


def test_no_keyword_returns_empty():
    assert detect_domain("the weather is nice and calm") == ""


# ---------------- CJK keywords still substring-matched ----------------

def test_cjk_keyword_substring():
    assert detect_domain("我喜欢编程和重构代码") == "software"
    assert detect_domain("今天去医院看医生") == "health"
