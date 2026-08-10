"""Name hints (称呼线索) — turn "who is this?" into a question you can tap.

An open question costs the owner a keyboard and a memory search on a phone; a
yes/no one costs a tap. The material for the cheaper question is already lying in
the life log: people get addressed by name in conversation ("与庆松、明月约好晚上
吃烧烤"), and the episodes now carry clean speaker labels in `participants`, so a
name that keeps showing up exactly when spk_003 is in the room is a strong guess
at spk_003's name.

Division of labour, and it matters:

- **The LLM only decides what is a personal name.** That is irreducibly semantic:
  in real summaries "明月" (a person) sits beside "明天" (tomorrow), "四季青桥" (a
  station) and "狮子头" (a dish), and a pattern that catches the first catches all
  four. Regex extraction was tried as a direction in this project and abandoned.
- **The attribution is arithmetic, and stays here.** Once the name set is known,
  "which speaker does this name belong to" is counting: how often the name appears
  with a speaker versus how often it appears at all. Keeping this deterministic
  means the ranking is reproducible and inspectable, and the LLM's job shrinks to
  something easy to check.

Host-thinks (same as `lifelog consolidate`): `prepare` hands out material and a
prompt, the caller's LLM answers, `apply` does the counting and stores the result.
The bare CLI on R76S has no LLM, and both halves still work there.

A candidate is a PROPOSAL, never a name. Nothing here writes `display_name` —
being talked about and being present are different things ("与庆松、明月约好" is
said about people who are elsewhere), and only the owner can close that gap.
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_SUMMARY_CHARS = 300
MAX_OPTIONS = 3
# A name must co-occur with the speaker at least this often to be recorded at all.
MIN_SUPPORT = 1
# ...and more often than its own baseline rate, or it is just a frequent word that
# attaches to whoever happens to be around.
MIN_LIFT = 1.2
# Promotion to a tap target asks a different, blunter question than lift does:
# "when this name comes up, is this speaker usually in the room?" Lift compares
# against a baseline and gets noisy when there are few episodes; this is a direct
# conditional and stays stable at small N. Both must hold — two sightings of a
# name that is nearly always this speaker's.
STRONG_SUPPORT = 2
STRONG_PRECISION = 0.6

# Things that look like names in this corpus but are not. The per-chunk speaker
# markers leak into summary prose even after `participants` was cleaned up
# ("发言人1D提出可尝试反向打光"), so they must be dropped whatever the LLM says.
_NOT_A_NAME = re.compile(r"^(我|自己|对方[甲乙丙丁]?|发言人[0-9A-Za-z]*|spk_\d+)$")

SYSTEM = (
    "你从生活记录的摘要里找出**人名**。只找人名，不找地名、菜名、公司名、产品名。"
)

INSTRUCTION = """\
下面是若干段生活记录摘要。请找出其中出现的**人的名字**。

规则：
- 只要人名。「四季青桥」是地铁站、「狮子头」是菜、「明天」是时间词 —— 都不是人名。
- **不要**收录「我」「自己」「对方甲」这类代称。
- **不要**收录「发言人1A」「发言人1D」这类转写标记，它们不是名字。
- 名字被提到时，那个人**未必在场**（「与庆松、明月约好晚上吃烧烤」说的是不在场的人）。
  你不需要判断在不在场，只管把名字列出来，在场与否由调用方另行统计。
- 找不到就返回空列表，不要猜。

只输出 JSON，不要解释：
{"names": ["名字1", "名字2"]}
"""


def build_material(ll, user_id: str = "", limit: int = 200) -> dict[str, Any]:
    """Episodes worth scanning for names, with their speaker labels attached."""
    eps = ll.list_episodes(limit=limit, user_id=user_id)
    out = []
    for e in eps:
        summary = (e.get("summary") or "").strip()
        if not summary:
            continue
        out.append({
            "id": e["id"], "date": e.get("date", ""),
            "start_clock": e.get("start_clock", ""),
            "summary": summary[:MAX_SUMMARY_CHARS],
            "participants": [p for p in (e.get("participants") or [])],
        })
    return {"episodes": out, "count": len(out)}


def build_prompt(material: dict[str, Any]) -> str:
    lines = [INSTRUCTION, ""]
    for e in material["episodes"]:
        lines.append(f"[{e['date']} {e['start_clock']}] {e['summary']}")
    return "\n".join(lines)


def _strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```$", "", t)
    return t.strip()


def parse_response(text: str) -> list[str]:
    """Names from the LLM's reply, with the never-a-name set filtered out here
    rather than trusted to the prompt."""
    try:
        data = json.loads(_strip_fence(text))
    except (json.JSONDecodeError, TypeError):
        return []
    names = data.get("names", []) if isinstance(data, dict) else data
    out, seen = [], set()
    for n in names or []:
        if not isinstance(n, str):
            continue
        n = n.strip()
        if not n or n in seen or _NOT_A_NAME.match(n):
            continue
        seen.add(n)
        out.append(n)
    return out


def rank_candidates(names: list[str], episodes: list[dict[str, Any]],
                    labels: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Attribute names to speakers by co-occurrence. Pure arithmetic, no model.

    `lift` is how much more often a name appears when this speaker is present than
    it does overall. A name mentioned everywhere (someone discussed constantly but
    never in the room) has lift ≈ 1 and does not become a candidate for anyone;
    a name that tracks one speaker's presence stands out.
    """
    total = len(episodes)
    if not total or not names:
        return {}

    name_eps = {n: [e for e in episodes if n in e["summary"]] for n in names}
    out: dict[str, list[dict[str, Any]]] = {}

    for label in labels:
        present = [e for e in episodes if label in e["participants"]]
        if not present:
            continue
        cands = []
        for n in names:
            hits = [e for e in name_eps[n] if label in e["participants"]]
            support = len(hits)
            if support < MIN_SUPPORT:
                continue
            base = len(name_eps[n]) / total          # how common the name is at all
            rate = support / len(present)            # how common it is around this speaker
            lift = rate / base if base else 0.0
            if lift < MIN_LIFT:
                continue
            # Of the times this name is spoken, how often is this speaker there?
            precision = support / len(name_eps[n])
            strong = support >= STRONG_SUPPORT and precision >= STRONG_PRECISION
            cands.append({
                "name": n,
                "support": support,
                "speaker_episodes": len(present),
                "name_episodes": len(name_eps[n]),
                "precision": round(precision, 2),
                "lift": round(lift, 2),
                # Deliberately never 1.0: this is a guess from co-occurrence, and
                # the owner is the one who knows.
                "confidence": 0.6 if strong else 0.3,
                "strong": strong,
                "episodes": [e["id"] for e in hits][:5],
                "days": sorted({e["date"] for e in hits}),
            })
        if cands:
            cands.sort(key=lambda c: (-c["support"], -c["precision"], c["name"]))
            out[label] = cands[:MAX_OPTIONS]
    return out


def apply_names(names: list[str], *, sp, ll, user_id: str = "",
                limit: int = 200) -> dict[str, Any]:
    """Count, rank, and store the candidates against each unnamed active speaker."""
    material = build_material(ll, user_id=user_id, limit=limit)
    people = [s for s in sp.list_speakers(user_id=user_id, status="active")
              if not s["display_name"] and not s["is_wearer"]]
    ranked = rank_candidates(names, material["episodes"], [s["label"] for s in people])

    stored = {}
    for label, cands in ranked.items():
        sp.set_name_candidates(label, cands, user_id=user_id)
        stored[label] = [c["name"] for c in cands]
    return {"names_in": len(names), "episodes_scanned": material["count"],
            "speakers_considered": len(people), "stored": stored}
