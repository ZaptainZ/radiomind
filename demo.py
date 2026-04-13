#!/usr/bin/env python3
"""RadioMind v0.1 Demo — full lifecycle without Ollama.

Demonstrates: ingest → search → learn → profile → stats
(Chat/Dream refinement requires Ollama running)
"""

from radiomind import RadioMind
from radiomind.core.types import Message


def main():
    print("=" * 60)
    print("  RadioMind v0.1 — Bionic Memory Core Demo")
    print("=" * 60)

    # Initialize — loads ~/.radiomind/config.toml automatically
    mind = RadioMind()
    mind.initialize()
    print(f"\n✓ Initialized at {mind.config.home}")

    # --- 1. Ingest conversations ---
    print("\n--- 1. Ingesting conversations ---")
    messages = [
        Message(role="user", content="我叫小明"),
        Message(role="user", content="我在北京工作"),
        Message(role="user", content="我喜欢每天早上跑步"),
        Message(role="user", content="我发现跑步后睡眠质量明显提升"),
        Message(role="user", content="我讨厌加班"),
        Message(role="user", content="我打算学习Rust编程语言"),
        Message(role="user", content="请记住我的生日是3月15日"),
        Message(role="user", content="我每天晚上10点前睡觉"),
    ]
    entries = mind.ingest(messages)
    print(f"  Processed {len(messages)} messages → {len(entries)} memories")
    for e in entries:
        print(f"    [{e.domain or '?':>8}] {e.content}")

    # --- 2. Search ---
    print("\n--- 2. Pyramid Search ---")
    for query in ["跑步", "加班", "生日"]:
        results = mind.search(query)
        print(f"  Query: '{query}' → {len(results)} results")
        for r in results[:2]:
            print(f"    [{r.entry.level.name:>9}] {r.entry.content}")

    # --- 3. Learn external knowledge ---
    print("\n--- 3. Learning external knowledge ---")
    mind.learn("规律运动可以改善心血管健康和降低焦虑水平")
    mind.learn("晚上11点后的蓝光会影响褪黑素分泌，降低睡眠质量")
    results = mind.search("焦虑")
    print(f"  Learned 2 entries, search '焦虑' → {len(results)} results")

    # --- 4. User Profile ---
    print("\n--- 4. User Profile ---")
    profile = mind.get_user_profile()
    print(f"  WHO: {profile.who}")
    print(f"  HOW: {profile.how}")
    print(f"  WHAT: {profile.what}")

    # --- 5. Self Profile ---
    print("\n--- 5. Self Profile ---")
    sp = mind.get_self_profile()
    print(f"  Identity: {sp.identity}")
    print(f"  State: {sp.state}")
    print(f"  Capability: {sp.capability}")

    # --- 6. Context Digest ---
    print("\n--- 6. Context Digest (for system prompt injection) ---")
    digest = mind.get_context_digest(token_budget=250)
    print(f"  {digest}")

    # --- 7. Stats ---
    print("\n--- 7. Stats ---")
    s = mind.stats()
    print(f"  Memories: {s['total_active']} active, {s['archived']} archived")
    print(f"  By level: {s['by_level']}")
    print(f"  Habits (L3): {s['habits']}")
    print(f"  Domains: {s['domain_count']}")
    print(f"  LLM: {'available' if s['llm_available'] else 'unavailable'}")

    # --- 8. Chat/Dream (only if Ollama available) ---
    if mind._llm.is_available():
        print("\n--- 8. Chat Refinement (three-body debate) ---")
        result = mind.trigger_chat()
        print(f"  Done in {result.duration_s:.1f}s, {len(result.new_insights)} insights")
        for i in result.new_insights:
            print(f"    [candidate] {i.description} (confidence={i.confidence:.1f})")

        print("\n--- 9. Dream Refinement (pruning + wandering) ---")
        result = mind.trigger_dream()
        print(f"  Done in {result.duration_s:.1f}s")
        print(f"  Merged: {result.merged}, Pruned: {result.pruned}")
        print(f"  Wandering insights: {len(result.new_insights)}")
    else:
        print("\n--- 8/9. Skipping Chat/Dream (Ollama not running) ---")

    mind.shutdown()
    print("\n" + "=" * 60)
    print("  Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
