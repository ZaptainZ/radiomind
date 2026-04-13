"""Core data types for RadioMind."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class MemoryLevel(IntEnum):
    FACT = 0
    PATTERN = 1
    PRINCIPLE = 2


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    ARCHIVED = "archived"


@dataclass
class Message:
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryEntry:
    content: str
    domain: str = ""
    level: MemoryLevel = MemoryLevel.FACT
    parent_id: int | None = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    embedding: bytes | None = None
    id: int | None = None
    hit_count: int = 0
    last_hit_at: float = 0.0
    decay_count: int = 0
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Habit:
    description: str
    status: MemoryStatus = MemoryStatus.CANDIDATE
    confidence: float = 0.5
    source_ids: list[int] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    verified_at: float | None = None


@dataclass
class SearchResult:
    entry: MemoryEntry
    score: float
    method: str  # "knn" | "fts" | "like"


@dataclass
class RefinementResult:
    new_insights: list[Habit]
    merged: int
    pruned: int
    duration_s: float
    model_used: str
    tokens_used: int


@dataclass
class UserProfile:
    who: dict[str, str] = field(default_factory=dict)
    how: dict[str, str] = field(default_factory=dict)
    what: dict[str, str] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


@dataclass
class SelfProfile:
    identity: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    capability: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)
