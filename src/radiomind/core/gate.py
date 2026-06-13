"""L1 Attention Gate — filter conversations into memory-worthy entries.

Like the prefrontal cortex deciding "is this worth remembering?"
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from radiomind.core.types import MemoryEntry, MemoryLevel, Message, PrivacyLevel

GUARDED_DOMAINS = {"health", "finance"}

# Patterns that signal memory-worthy content (inspired by HomeGenie's 15 rules)
EXTRACTION_PATTERNS: list[tuple[str, str]] = [
    # Identity
    (r"我(?:叫|是|名字是)\s*(.+)", "identity"),
    (r"(?:my name is|i'm|i am)\s+(.+)", "identity"),
    # Preferences
    (r"我(?:喜欢|爱|偏好|倾向于)\s*(.+)", "preference"),
    (r"我(?:不喜欢|讨厌|不想|拒绝)\s*(.+)", "aversion"),
    (r"(?:i (?:like|love|prefer|enjoy))\s+(.+)", "preference"),
    (r"(?:i (?:don't like|hate|dislike|avoid))\s+(.+)", "aversion"),
    # Explicit memory requests
    (r"(?:请?记住|记一下|帮我记|remember)\s*[:：]?\s*(.+)", "explicit"),
    # Facts about self
    (r"我(?:在|住在|来自)\s*(.+)", "location"),
    (r"我(?:做|从事|工作是)\s*(.+)", "occupation"),
    (r"我(?:有|养了)\s*(.+)", "possession"),
    # Goals and plans
    (r"我(?:想要|打算|计划|准备)\s*(.+)", "goal"),
    (r"(?:i (?:want to|plan to|intend to|need to))\s+(.+)", "goal"),
    # Habits and routines
    (r"我(?:每天|通常|一般|经常|总是)\s*(.+)", "routine"),
    (r"(?:i (?:usually|always|often|every day))\s+(.+)", "routine"),
    # Experiences and events
    (r"(?:今天|昨天|上周|最近)我?\s*(.{10,})", "event"),
    # Opinions and beliefs
    (r"我(?:认为|觉得|相信)\s*(.+)", "opinion"),
    (r"(?:i (?:think|believe|feel that))\s+(.+)", "opinion"),
]

# Domain detection keywords
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "health": [
        "运动", "跑步", "健身", "睡眠", "失眠", "饮食", "体重", "医生", "药",
        "exercise", "sleep", "health", "diet", "workout", "doctor",
    ],
    "work": [
        "工作", "公司", "项目", "会议", "同事", "老板", "加班", "deadline",
        "work", "project", "meeting", "office", "boss", "colleague",
    ],
    "learning": [
        "学习", "课程", "考试", "读书", "教程", "知识",
        "learn", "study", "course", "exam", "book", "tutorial",
    ],
    "finance": [
        "理财", "投资", "存款", "工资", "花费", "预算",
        "money", "invest", "budget", "salary", "saving",
    ],
    "hobby": [
        "爱好", "游戏", "音乐", "电影", "旅行", "摄影", "画画",
        "hobby", "game", "music", "movie", "travel", "photo",
    ],
    # SmallUserReadiness-1c: minimal technical domains so developer content
    # lands somewhere instead of domain="" (1a: tech memories were blind to
    # the 5 lifestyle domains). Deliberately narrow — covers the 1a sample
    # shapes, not an exhaustive taxonomy.
    "software": [
        "代码", "编程", "重构", "调试", "解析器", "适配器", "接口", "架构",
        "code", "coding", "parser", "parsers", "adapter", "adapters",
        "refactor", "debug", "interface", "library", "software",
    ],
    "ios": [
        "swift", "swiftui", "xcode", "ios", "iphone", "ipad", "uikit",
    ],
    "rust": [
        "rust", "cargo", "borrow", "lifetime", "serde", "tokio", "trait",
    ],
    "networking": [
        "网络", "代理", "retry", "backoff", "circuit breaker", "tcp",
        "network", "networking", "proxy", "socket", "latency",
    ],
    "ai": [
        "模型", "推理", "微调", "llm", "embedding", "fallback", "prompt",
        "inference", "fine-tune", "agent", "rag",
    ],
}


@dataclass
class ExtractionResult:
    entries: list[MemoryEntry] = field(default_factory=list)
    domains_detected: set[str] = field(default_factory=set)
    patterns_matched: int = 0
    messages_processed: int = 0


_ASCII_KW_RE = re.compile(r"^[a-z0-9][a-z0-9 +.\-]*$")


def _kw_matches(kw: str, text_lower: str) -> bool:
    """SmallUserReadiness-1c: word-boundary match for ASCII keywords so
    'work' no longer matches 'network'/'workflow'; CJK keywords have no
    word boundaries, so they keep substring matching."""
    if _ASCII_KW_RE.match(kw):
        return re.search(rf"\b{re.escape(kw)}\b", text_lower) is not None
    return kw in text_lower


def detect_domain(text: str) -> str:
    """Detect domain from text content using keyword matching."""
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if _kw_matches(kw, text_lower))
        if score > 0:
            scores[domain] = score

    if not scores:
        return ""
    return max(scores, key=scores.get)


def extract_from_message(msg: Message) -> list[tuple[str, str, str]]:
    """Extract memory-worthy content from a single message.

    Returns list of (content, category, domain).
    """
    if msg.role != "user":
        return []

    results = []
    text = msg.content.strip()

    for pattern, category in EXTRACTION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            captured = match.group(1).strip() if match.lastindex else text
            domain = detect_domain(text)
            results.append((text, category, domain))
            break  # one match per message to avoid duplicates

    return results


def gate(messages: list[Message]) -> ExtractionResult:
    """L1 attention gate: process conversation messages into memory entries.

    Filters out noise, extracts memory-worthy content, detects domains.
    """
    result = ExtractionResult()
    seen_content: set[str] = set()

    for msg in messages:
        result.messages_processed += 1
        extractions = extract_from_message(msg)

        for content, category, domain in extractions:
            if content in seen_content:
                continue
            seen_content.add(content)

            privacy = PrivacyLevel.GUARDED if domain in GUARDED_DOMAINS else PrivacyLevel.OPEN
            entry = MemoryEntry(
                content=content,
                domain=domain,
                level=MemoryLevel.FACT,
                privacy=privacy,
                created_at=msg.timestamp,
                metadata={"category": category, "source": "gate"},
            )
            result.entries.append(entry)
            result.patterns_matched += 1
            if domain:
                result.domains_detected.add(domain)

    return result
