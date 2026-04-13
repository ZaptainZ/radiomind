"""Tests for core data types."""

from radiomind.core.types import (
    Habit,
    MemoryEntry,
    MemoryLevel,
    MemoryStatus,
    Message,
)


def test_memory_entry_defaults():
    entry = MemoryEntry(content="test")
    assert entry.level == MemoryLevel.FACT
    assert entry.status == MemoryStatus.ACTIVE
    assert entry.domain == ""
    assert entry.hit_count == 0


def test_memory_levels():
    assert MemoryLevel.FACT < MemoryLevel.PATTERN < MemoryLevel.PRINCIPLE
    assert int(MemoryLevel.FACT) == 0
    assert int(MemoryLevel.PRINCIPLE) == 2


def test_message():
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    assert msg.timestamp > 0


def test_habit_defaults():
    habit = Habit(description="user values autonomy")
    assert habit.status == MemoryStatus.CANDIDATE
    assert habit.confidence == 0.5
    assert habit.verified_at is None
