"""Training data generation: L3 habits + L2 memories → JSONL for LoRA fine-tuning.

Goal: produce a **high-quality, non-overlapping train/valid split** that a
small local model can fine-tune on without overfitting. Previous iterations
copied the training set as the validation set — that's textbook overfit
setup and makes loss curves meaningless.

Hard rules enforced here:
  - Strict deduplication by normalized content hash
  - Minimum diversity: >= MIN_DISTINCT_EXAMPLES unique user turns
  - Minimum domain / habit coverage before accepting the run
  - 80/20 random split with fixed seed (reproducible)
  - PII filtering before emission
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from radiomind.community.pool import detect_pii, sanitize_for_sharing
from radiomind.core.types import Habit, MemoryEntry, MemoryLevel, MemoryStatus
from radiomind.storage.database import MemoryStore
from radiomind.storage.hdc import HabitStore

# --- Quality gates ------------------------------------------------------

MIN_DISTINCT_EXAMPLES = 30      # refuse to train with less than this
MIN_HABITS = 5                  # need a reasonable habit pool
MIN_DOMAINS = 2
MAX_EXAMPLES_PER_HABIT = 6      # prevent one habit from dominating
VALID_FRACTION = 0.2
SEED = 20260415


SYSTEM_TEMPLATE = """You are a personal AI assistant who deeply understands this user.
Key facts about the user:
{user_context}

Always respond in a way that reflects your understanding of the user."""


# Paraphrase templates. Keeping to short, distinct shapes so the same underlying
# habit produces genuinely different training examples, not near-dupes.
QA_TEMPLATES_ZH: list[tuple[str, str]] = [
    ("你知道我什么？", "{habit_summary}"),
    ("用一句话描述我", "{habit_one_line}"),
    ("关于{domain}方面我有什么特点？", "{domain_insights}"),
    ("我在{domain}有什么习惯？", "{domain_habits}"),
    ("我有哪些明显偏好？", "{preferences}"),
    ("我不喜欢什么？", "{aversions}"),
    ("用几句话总结我的日常节奏", "{routines}"),
    ("我的长期目标是什么？", "{goals}"),
    ("我平时{domain}相关的决定模式", "{decision_pattern}"),
]

QA_TEMPLATES_EN: list[tuple[str, str]] = [
    ("What do you know about me?", "{habit_summary}"),
    ("Describe me in one line.", "{habit_one_line}"),
    ("What about my {domain} habits?", "{domain_insights}"),
    ("What are my habits around {domain}?", "{domain_habits}"),
    ("What are my clear preferences?", "{preferences}"),
    ("What do I dislike?", "{aversions}"),
    ("Summarize my routines in a few lines.", "{routines}"),
    ("What are my long-term goals?", "{goals}"),
    ("My typical decision pattern around {domain}?", "{decision_pattern}"),
]


@dataclass
class DataGenReport:
    train_count: int
    valid_count: int
    dropped_pii: int
    dropped_dup: int
    dropped_short: int
    habits_used: int
    domains_used: int
    refused: bool = False
    refused_reason: str = ""
    # CLIProductSmoke-1b (F1): distinct usable examples produced, so the CLI
    # can show the gap (e.g. 18/30) without parsing refused_reason.
    distinct_examples: int = 0
    # LoRAFuel-1b: which habits this training set consumed (observational
    # only — groundwork for future shelf-life/incremental-training policy).
    habit_ids: list = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.habit_ids is None:
            self.habit_ids = []


def habit_id(h) -> str:
    """Stable observational id for a habit (the HDC store has no id
    column): sha1 of the description, 12 hex chars."""
    return hashlib.sha1(h.description.encode("utf-8")).hexdigest()[:12]


class TrainingDataGenerator:
    def __init__(self, store: MemoryStore, habits: HabitStore):
        self._store = store
        self._habits = habits

    def generate(
        self,
        output_path: Path,
        language: str = "zh",
        valid_path: Path | None = None,
        seed: int = SEED,
    ) -> int:
        """Generate JSONL train/valid split. Returns train example count.

        Writes:
          output_path         → train set
          valid_path (default {output_path.parent}/valid.jsonl) → holdout
        """
        report = self.generate_with_report(
            output_path, language=language, valid_path=valid_path, seed=seed
        )
        if report.refused:
            return 0
        return report.train_count

    def generate_with_report(
        self,
        output_path: Path,
        language: str = "zh",
        valid_path: Path | None = None,
        seed: int = SEED,
    ) -> DataGenReport:
        rng = random.Random(seed)
        templates = QA_TEMPLATES_ZH if language == "zh" else QA_TEMPLATES_EN

        all_habits = [
            h for h in self._habits.all_habits()
            if h.status != MemoryStatus.ARCHIVED
        ]
        stats = self._store.stats()
        domains = [d["name"] for d in stats.get("domains", []) if d["name"]]

        user_context = self._build_user_context(all_habits, domains)
        system_prompt = SYSTEM_TEMPLATE.format(user_context=user_context)

        preferences = self._get_preferences(all_habits, kind="preference")
        aversions = self._get_preferences(all_habits, kind="aversion")
        habit_summary = self._join_habits(all_habits, limit=6)
        habit_one_line = self._join_habits(all_habits, limit=2, sep="；")
        routines = self._get_routines(all_habits)
        goals = self._get_goals(all_habits)

        raw_examples: list[tuple[str, str, str]] = []  # (q, a, tag)

        # --- Per-habit specific examples (teach individual facts) -------
        # Each habit gets MULTIPLE distinct (Q, A) phrasings so the model
        # learns to recognize and emit the same fact from different angles.
        habits_used = 0
        consumed_habit_ids: list[str] = []
        for i, h in enumerate(all_habits):
            clean = self._sanitize(h.description)
            if not self._ok_answer(clean):
                continue

            # Reverse-direction examples: content-first Q/A
            variants = self._habit_variants(clean, idx=i, language=language)
            for q, a in variants:
                raw_examples.append((q, a, f"habit-specific:{id(h)}:{hash(q)}"))
            habits_used += 1
            consumed_habit_ids.append(habit_id(h))

        # --- Global aggregate examples (teach overall personality) ------
        for h in all_habits[:30]:
            per_habit = 0
            for q_template, a_template in templates:
                if per_habit >= MAX_EXAMPLES_PER_HABIT:
                    break
                # Skip templates that need domain if we don't have one
                needs_domain = "{domain}" in q_template or "{domain}" in a_template
                if needs_domain and not domains:
                    continue

                dom = domains[habits_used % len(domains)] if domains else ""

                q = q_template.replace("{domain}", dom) if needs_domain else q_template
                a_fields = {
                    "habit_summary": habit_summary,
                    "habit_one_line": habit_one_line,
                    "preferences": preferences,
                    "aversions": aversions,
                    "routines": routines,
                    "goals": goals,
                    "domain": dom,
                    "domain_insights": self._get_domain_insights(dom),
                    "domain_habits": self._get_domain_habits(all_habits, dom),
                    "decision_pattern": self._get_decision_pattern(dom),
                }
                try:
                    a = a_template.format(**a_fields).strip()
                except KeyError:
                    continue
                if not self._ok_answer(a):
                    continue
                raw_examples.append((q, a, f"habit:{id(h)}"))
                per_habit += 1
            # (habits_used already incremented above)

        # --- L2 principle / pattern examples ----------------------------
        principles = self._store.list_by_level(MemoryLevel.PRINCIPLE, limit=20)
        for p in principles:
            clean = self._sanitize(p.content)
            if not self._ok_answer(clean):
                continue
            q = (
                f"关于{p.domain}，你观察到什么规律？"
                if language == "zh" else
                f"What patterns have you noticed about {p.domain}?"
            )
            raw_examples.append((q, clean, f"principle:{p.id}"))

        patterns = self._store.list_by_level(MemoryLevel.PATTERN, limit=40)
        for p in patterns:
            clean = self._sanitize(p.content)
            if not self._ok_answer(clean):
                continue
            q = (
                f"在{p.domain}方面有什么值得注意的？"
                if language == "zh" else
                f"What's noteworthy about {p.domain}?"
            )
            raw_examples.append((q, clean, f"pattern:{p.id}"))

        # --- L2 facts (direct — don't wait for refinement to produce habits)
        # v0.2 limitation: data_gen previously only tapped L3 habits and
        # L2 patterns/principles. On a real user DB with 745 facts but few
        # refined habits, that produced only ~80 training examples. Tap the
        # raw facts too — they're per-domain specific truths about the user.
        L2_PROMPT_ZH = [
            "你对我在{domain}方面知道什么？",
            "关于{domain}，我有什么特点或偏好？",
            "说一个你记得的我在{domain}领域的事实",
            "描述我在{domain}上的一个具体观察",
        ]
        L2_PROMPT_EN = [
            "What do you know about me in {domain}?",
            "In the {domain} area, what are my traits?",
            "Share a fact about me in {domain}.",
            "Describe one specific observation of me in {domain}.",
        ]
        l2_prompts = L2_PROMPT_ZH if language == "zh" else L2_PROMPT_EN

        # Per-domain sample cap to prevent one noisy domain from dominating
        MAX_FACTS_PER_DOMAIN = 8
        fact_count_by_domain: dict[str, int] = {}
        for dom_info in stats.get("domains", [])[:20]:  # top 20 domains
            dom = dom_info["name"]
            if not dom:
                continue
            facts = self._store.list_by_domain(dom, level=MemoryLevel.FACT, limit=MAX_FACTS_PER_DOMAIN)
            for f in facts:
                clean = self._sanitize(f.content)
                if not self._ok_answer(clean) or len(clean) > 500:
                    continue
                # Use one rotating prompt per fact
                q_tmpl = l2_prompts[(fact_count_by_domain.get(dom, 0)) % len(l2_prompts)]
                q = q_tmpl.format(domain=dom)
                raw_examples.append((q, clean, f"fact:{f.id}"))
                fact_count_by_domain[dom] = fact_count_by_domain.get(dom, 0) + 1

        # --- Dedup + quality gates --------------------------------------
        dropped_pii = 0
        dropped_dup = 0
        dropped_short = 0
        seen_hashes: set[str] = set()
        clean_examples: list[dict] = []

        for q, a, tag in raw_examples:
            if detect_pii(q) or detect_pii(a):
                dropped_pii += 1
                continue
            if len(a) < 10 or len(a) > 600:
                dropped_short += 1
                continue
            fp = self._fingerprint(q, a)
            if fp in seen_hashes:
                dropped_dup += 1
                continue
            seen_hashes.add(fp)
            clean_examples.append(self._format_example(system_prompt, q, a))

        # --- Refuse if below thresholds ---------------------------------
        refused_reason = ""
        if len(clean_examples) < MIN_DISTINCT_EXAMPLES:
            refused_reason = (
                f"need >= {MIN_DISTINCT_EXAMPLES} unique examples, "
                f"have {len(clean_examples)}"
            )
        elif habits_used < MIN_HABITS:
            refused_reason = f"need >= {MIN_HABITS} habits with content, have {habits_used}"
        elif len(domains) < MIN_DOMAINS:
            refused_reason = f"need >= {MIN_DOMAINS} domains, have {len(domains)}"

        if refused_reason:
            return DataGenReport(
                train_count=0, valid_count=0,
                dropped_pii=dropped_pii, dropped_dup=dropped_dup, dropped_short=dropped_short,
                habits_used=habits_used, domains_used=len(domains),
                refused=True, refused_reason=refused_reason,
                distinct_examples=len(clean_examples),
                habit_ids=consumed_habit_ids,
            )

        # --- Shuffle + 80/20 split --------------------------------------
        rng.shuffle(clean_examples)
        n_valid = max(5, int(len(clean_examples) * VALID_FRACTION))
        valid_set = clean_examples[:n_valid]
        train_set = clean_examples[n_valid:]

        # --- Write ------------------------------------------------------
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for ex in train_set:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

        if valid_path is None:
            valid_path = output_path.parent / "valid.jsonl"
        with open(valid_path, "w", encoding="utf-8") as f:
            for ex in valid_set:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

        return DataGenReport(
            train_count=len(train_set),
            valid_count=len(valid_set),
            dropped_pii=dropped_pii,
            dropped_dup=dropped_dup,
            dropped_short=dropped_short,
            habits_used=habits_used,
            domains_used=len(domains),
            distinct_examples=len(clean_examples),
            habit_ids=consumed_habit_ids,
        )

    @staticmethod
    def _habit_variants(habit: str, idx: int, language: str = "zh") -> list[tuple[str, str]]:
        """Generate multiple distinct (Q, A) training pairs rooted on a habit.

        Uses rotation through phrasings keyed on idx so different habits get
        different anchor questions — increases lexical diversity without LLM.
        """
        if language == "zh":
            anchors = [
                ("关于我，你还记得什么？", habit),
                ("说一个你对我的观察", habit),
                ("补充一条我的信息", habit),
                ("告诉我一件关于我的事", habit),
                ("随便说一条你知道的我", habit),
                (f"是否知道我有这个特点：{habit[:8]}…？", f"知道。{habit}"),
                ("请根据你对我的了解回答", habit),
            ]
        else:
            anchors = [
                ("What else do you know about me?", habit),
                ("Share an observation about me.", habit),
                ("Tell me something you remember about me.", habit),
                ("Add one fact about me.", habit),
                (f"Do you know about this trait: {habit[:40]}...?", f"Yes. {habit}"),
            ]
        # Rotate so adjacent habits don't both start with the same anchor
        rotated = anchors[idx % len(anchors):] + anchors[: idx % len(anchors)]
        # Take up to MAX_EXAMPLES_PER_HABIT distinct variants
        return rotated[:MAX_EXAMPLES_PER_HABIT]

    # --- Content helpers ------------------------------------------------

    def _build_user_context(self, habits: list[Habit], domains: list[str]) -> str:
        parts = []
        if habits:
            parts.append("Habits: " + "；".join(h.description for h in habits[:5]))
        if domains:
            parts.append("Active domains: " + ", ".join(domains))
        return "\n".join(parts) if parts else "No specific context yet."

    def _join_habits(self, habits: list[Habit], limit: int = 6, sep: str = "\n- ") -> str:
        cleaned = []
        for h in habits[:limit]:
            s = self._sanitize(h.description)
            if s:
                cleaned.append(s)
        if not cleaned:
            return "暂未形成明显习惯。"
        return ("- " + sep.join(cleaned)) if sep.startswith("\n") else sep.join(cleaned)

    def _get_preferences(self, habits: list[Habit], kind: str = "preference") -> str:
        if kind == "preference":
            keywords = ["喜欢", "偏好", "prefer", "like", "love", "enjoy"]
        else:
            keywords = ["不喜欢", "讨厌", "拒绝", "hate", "dislike", "avoid"]
        hits = [h.description for h in habits if any(kw in h.description for kw in keywords)]
        return "；".join(hits[:5]) if hits else ("还在了解中。" if kind == "preference" else "暂无明确负面偏好。")

    def _get_routines(self, habits: list[Habit]) -> str:
        hits = [
            h.description for h in habits
            if any(kw in h.description for kw in ["每天", "通常", "总是", "经常", "usually", "every day"])
        ]
        return "\n- " + "\n- ".join(hits[:4]) if hits else "尚未观察到稳定节奏。"

    def _get_goals(self, habits: list[Habit]) -> str:
        hits = [
            h.description for h in habits
            if any(kw in h.description for kw in ["想要", "打算", "计划", "目标", "want to", "plan to"])
        ]
        return "；".join(hits[:4]) if hits else "目标还在梳理中。"

    def _get_domain_insights(self, domain: str) -> str:
        if not domain:
            return "暂无特定领域洞察。"
        entries = self._store.list_by_domain(domain, level=MemoryLevel.PATTERN, limit=3)
        if entries:
            return "；".join(e.content for e in entries)
        entries = self._store.list_by_domain(domain, level=MemoryLevel.FACT, limit=3)
        if entries:
            return "；".join(e.content for e in entries)
        return f"关于{domain}的信息还在积累中。"

    def _get_domain_habits(self, habits: list[Habit], domain: str) -> str:
        if not domain:
            return "暂无具体领域习惯。"
        # Heuristic: habit mentions the domain keyword
        hits = [h.description for h in habits if domain in h.description]
        if hits:
            return "；".join(hits[:3])
        return self._get_domain_insights(domain)

    def _get_decision_pattern(self, domain: str) -> str:
        if not domain:
            return "暂无明确决策模式。"
        principles = self._store.list_by_domain(domain, level=MemoryLevel.PRINCIPLE, limit=2)
        if principles:
            return "；".join(p.content for p in principles)
        return "这方面的决策偏好还在形成中。"

    # --- Filters ------------------------------------------------------

    @staticmethod
    def _ok_answer(text: str) -> bool:
        if not text or not text.strip():
            return False
        # Reject boilerplate "I don't know" style answers from domain fallbacks
        bad_markers = ("还在了解中", "还在积累中", "暂无", "还在观察中", "尚未", "还在形成中", "还在梳理中", "暂未")
        if any(m in text for m in bad_markers):
            return False
        return True

    @staticmethod
    def _fingerprint(q: str, a: str) -> str:
        def norm(s: str) -> str:
            return re.sub(r"\s+", "", s.lower())
        return hashlib.sha256((norm(q) + "||" + norm(a)).encode()).hexdigest()

    @staticmethod
    def _sanitize(text: str) -> str:
        if detect_pii(text):
            return ""
        return sanitize_for_sharing(text)

    @staticmethod
    def _format_example(system: str, user: str, assistant: str) -> dict:
        return {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ]
        }
