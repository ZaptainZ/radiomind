"""Training data generation: L3 habits + L2 memories → JSONL for LoRA fine-tuning.

Converts RadioMind's accumulated knowledge into instruction-tuning format so a
small local model can internalize user habits without retrieval ("neocortical memory").
"""

from __future__ import annotations

import json
from pathlib import Path

from radiomind.core.types import Habit, MemoryEntry, MemoryLevel
from radiomind.storage.database import MemoryStore
from radiomind.storage.hdc import HabitStore

SYSTEM_TEMPLATE = """You are a personal AI assistant who deeply understands this user.
Key facts about the user:
{user_context}

Always respond in a way that reflects your understanding of the user."""

QA_TEMPLATES = [
    ("What do you know about me?", "Based on our interactions, {habit_summary}"),
    ("What are my preferences?", "{preferences}"),
    ("What should I keep in mind about {domain}?", "{domain_insights}"),
    ("Remind me about my habits.", "{habits_list}"),
    ("What patterns have you noticed about me?", "{patterns}"),
]

QA_TEMPLATES_ZH = [
    ("你了解我什么？", "根据我们的交流，{habit_summary}"),
    ("我有什么偏好？", "{preferences}"),
    ("关于{domain}我需要注意什么？", "{domain_insights}"),
    ("提醒我一下我的习惯。", "{habits_list}"),
    ("你发现了我什么规律？", "{patterns}"),
]


class TrainingDataGenerator:
    def __init__(self, store: MemoryStore, habits: HabitStore):
        self._store = store
        self._habits = habits

    def generate(self, output_path: Path, language: str = "zh") -> int:
        """Generate JSONL training data. Returns number of examples."""
        templates = QA_TEMPLATES_ZH if language == "zh" else QA_TEMPLATES
        all_habits = self._habits.all_habits()
        stats = self._store.stats()
        domains = [d["name"] for d in stats.get("domains", [])]

        user_context = self._build_user_context(all_habits, domains)
        system_prompt = SYSTEM_TEMPLATE.format(user_context=user_context)

        examples = []

        # Habit-based Q&A
        if all_habits:
            habit_descriptions = [h.description for h in all_habits]
            habit_summary = "；".join(habit_descriptions[:10])
            habits_list = "\n".join(f"- {h}" for h in habit_descriptions[:10])

            for q_template, a_template in templates:
                q = q_template
                a = a_template.format(
                    habit_summary=habit_summary,
                    preferences=self._get_preferences(all_habits),
                    habits_list=habits_list,
                    patterns=self._get_patterns(),
                    domain=domains[0] if domains else "general",
                    domain_insights=self._get_domain_insights(domains[0] if domains else ""),
                )
                if "{domain}" in q and domains:
                    for dom in domains[:3]:
                        q_filled = q.replace("{domain}", dom)
                        a_filled = a_template.format(
                            domain=dom,
                            domain_insights=self._get_domain_insights(dom),
                            habit_summary=habit_summary,
                            preferences=self._get_preferences(all_habits),
                            habits_list=habits_list,
                            patterns=self._get_patterns(),
                        )
                        examples.append(self._format_example(system_prompt, q_filled, a_filled))
                else:
                    examples.append(self._format_example(system_prompt, q, a))

        # Memory-based Q&A from L2 principles and patterns
        principles = self._store.list_by_level(MemoryLevel.PRINCIPLE, limit=10)
        for p in principles:
            q = f"关于{p.domain}，你观察到什么规律？" if language == "zh" else f"What patterns have you noticed about {p.domain}?"
            examples.append(self._format_example(system_prompt, q, p.content))

        patterns = self._store.list_by_level(MemoryLevel.PATTERN, limit=20)
        for p in patterns:
            q = f"在{p.domain}方面有什么值得注意的？" if language == "zh" else f"What's noteworthy about {p.domain}?"
            examples.append(self._format_example(system_prompt, q, p.content))

        # Write JSONL
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

        return len(examples)

    def _build_user_context(self, habits: list[Habit], domains: list[str]) -> str:
        parts = []
        if habits:
            parts.append("Habits: " + "；".join(h.description for h in habits[:5]))
        if domains:
            parts.append("Active domains: " + ", ".join(domains))
        return "\n".join(parts) if parts else "No specific context yet."

    def _get_preferences(self, habits: list[Habit]) -> str:
        prefs = [h.description for h in habits if any(kw in h.description for kw in ["喜欢", "偏好", "prefer", "like", "love"])]
        return "；".join(prefs[:5]) if prefs else "还在了解中。"

    def _get_patterns(self) -> str:
        patterns = self._store.list_by_level(MemoryLevel.PATTERN, limit=5)
        if patterns:
            return "\n".join(f"- {p.content}" for p in patterns)
        return "还在观察中，暂未发现明显规律。"

    def _get_domain_insights(self, domain: str) -> str:
        if not domain:
            return "暂无特定领域的洞察。"
        entries = self._store.list_by_domain(domain, level=MemoryLevel.PATTERN, limit=3)
        if entries:
            return "；".join(e.content for e in entries)
        entries = self._store.list_by_domain(domain, level=MemoryLevel.FACT, limit=3)
        if entries:
            return "；".join(e.content for e in entries)
        return f"关于{domain}的信息还在积累中。"

    @staticmethod
    def _format_example(system: str, user: str, assistant: str) -> dict:
        return {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ]
        }
