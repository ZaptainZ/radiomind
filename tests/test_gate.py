"""Tests for L1 attention gate."""

from radiomind.core.gate import detect_domain, extract_from_message, gate
from radiomind.core.types import Message


def test_extract_identity_chinese():
    msg = Message(role="user", content="我叫张三")
    results = extract_from_message(msg)
    assert len(results) == 1
    assert results[0][1] == "identity"


def test_extract_identity_english():
    msg = Message(role="user", content="my name is Alice")
    results = extract_from_message(msg)
    assert len(results) == 1
    assert results[0][1] == "identity"


def test_extract_preference():
    msg = Message(role="user", content="我喜欢跑步")
    results = extract_from_message(msg)
    assert len(results) == 1
    assert results[0][1] == "preference"


def test_extract_aversion():
    msg = Message(role="user", content="我讨厌加班")
    results = extract_from_message(msg)
    assert len(results) == 1
    assert results[0][1] == "aversion"


def test_extract_explicit_memory():
    msg = Message(role="user", content="请记住：我的密码提示是蓝色大象")
    results = extract_from_message(msg)
    assert len(results) == 1
    assert results[0][1] == "explicit"


def test_extract_goal():
    msg = Message(role="user", content="我打算明年学日语")
    results = extract_from_message(msg)
    assert len(results) == 1
    assert results[0][1] == "goal"


def test_extract_routine():
    msg = Message(role="user", content="我每天早上跑步5公里")
    results = extract_from_message(msg)
    assert len(results) == 1
    assert results[0][1] == "routine"


def test_ignore_assistant_messages():
    msg = Message(role="assistant", content="我叫AI助手")
    results = extract_from_message(msg)
    assert len(results) == 0


def test_ignore_noise():
    msg = Message(role="user", content="你好")
    results = extract_from_message(msg)
    assert len(results) == 0


def test_detect_domain_health():
    assert detect_domain("我每天跑步锻炼身体") == "health"


def test_detect_domain_work():
    assert detect_domain("今天项目会议讨论了新方案") == "work"


def test_detect_domain_empty():
    assert detect_domain("随便聊聊") == ""


def test_gate_full_conversation():
    messages = [
        Message(role="user", content="你好"),
        Message(role="assistant", content="你好！有什么可以帮你的？"),
        Message(role="user", content="我叫小明"),
        Message(role="user", content="我喜欢跑步和游泳"),
        Message(role="user", content="今天天气真好"),
        Message(role="user", content="请记住我的生日是3月15日"),
        Message(role="user", content="我每天早上6点起床"),
    ]

    result = gate(messages)
    assert result.messages_processed == 7
    assert result.patterns_matched >= 3  # identity + preference + explicit + routine
    assert all(e.level.value == 0 for e in result.entries)  # all facts


def test_gate_deduplication():
    messages = [
        Message(role="user", content="我喜欢跑步"),
        Message(role="user", content="我喜欢跑步"),
    ]
    result = gate(messages)
    assert len(result.entries) == 1


def test_gate_domain_detection():
    messages = [
        Message(role="user", content="我喜欢每天跑步锻炼"),
        Message(role="user", content="我打算学习Python编程"),
    ]
    result = gate(messages)
    assert "health" in result.domains_detected or "learning" in result.domains_detected
