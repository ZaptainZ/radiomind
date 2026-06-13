"""RadioMind CLI — command-line interface."""

from __future__ import annotations

import json

import click

from radiomind import __version__


def _get_mind():
    from radiomind.core.mind import RadioMind
    mind = RadioMind()
    mind.initialize()
    return mind


def _render_train_gap(report, prepared: bool) -> list[str]:
    """CLIProductSmoke-1b (F1): turn a refused DataGenReport into an
    actionable gap + next step, instead of a single threshold sentence."""
    from radiomind.training.data_gen import (
        MIN_DISTINCT_EXAMPLES, MIN_DOMAINS, MIN_HABITS,
    )
    lines = ["Not enough data to train yet — current vs required:"]
    for label, have, need in (
        ("habits", report.habits_used, MIN_HABITS),
        ("domains", report.domains_used, MIN_DOMAINS),
        ("examples", report.distinct_examples, MIN_DISTINCT_EXAMPLES),
    ):
        mark = "ok" if have >= need else "short"
        lines.append(f"  {label:10s} {have}/{need}  [{mark}]")
    if prepared:
        lines.append(
            "prepare-habits already ran — this is a DATA-VOLUME shortfall, "
            "not an LLM/router failure.")
    lines.append("Next: add more memories across different topics "
                 "(`radiomind ingest <file>` or `radiomind learn \"...\"`)"
                 + ("" if prepared else ", then `radiomind train --prepare-habits`")
                 + ".")
    return lines


def _render_backends(rows: list[dict]) -> str:
    """CLIProductSmoke-1b (F6): label backends default-first with tags.
    e.g. 'dashscope [default], openrouter, openai [deprecated]'."""
    parts = []
    for r in rows:
        tags = []
        if r["is_default"]:
            tags.append("default")
        if r["deprecated"]:
            tags.append("deprecated")
        elif not r["available"]:
            tags.append("unavailable")
        suffix = f" [{', '.join(tags)}]" if tags else ""
        parts.append(f"{r['name']}{suffix}")
    return ", ".join(parts) or "none"


@click.group()
@click.version_option(__version__, prog_name="radiomind")
def cli() -> None:
    """RadioMind — Bionic memory core for AI agents."""


@cli.command()
def init() -> None:
    """Initialize RadioMind data directory."""
    mind = _get_mind()
    click.echo(f"RadioMind initialized at {mind.config.home}")
    mind.shutdown()


@cli.command()
@click.option("--platform", "-p", default="", help="Force platform: claude-code, codex, cursor, windsurf")
@click.option("--force", is_flag=True, help="Overwrite existing config.")
@click.option("--remove", is_flag=True, help="Remove RadioMind config.")
def setup(platform: str, force: bool, remove: bool) -> None:
    """Setup RadioMind for your AI coding agent.

    \b
    Auto-detects platform and configures:
      Claude Code → hooks (Stop, PreCompact, SessionStart) + MCP
      Codex CLI   → hooks.json + MCP
      Cursor      → MCP config
      Windsurf    → MCP config
      Others      → prints MCP config to add manually

    Also detects RadioHeader — if present, skips SessionStart
    (RadioHeader already injects context digest).

    \b
    Claude Code users can also install as plugin:
      claude plugin add radiomind
    """
    from radiomind.hooks.setup import setup as do_setup, remove as do_remove

    if remove:
        result = do_remove(platform=platform)
        if result["removed"]:
            click.echo(f"Removed: {', '.join(result['removed'])}")
        else:
            click.echo("Nothing to remove.")
        return

    result = do_setup(platform=platform, force=force)

    click.echo(f"Platform: {result['platform']}")
    if result.get("radioheader_detected"):
        click.echo("RadioHeader detected — skipping SessionStart")
    click.echo()

    for action in result["actions"]:
        if action.startswith("{"):
            click.echo(action)
        else:
            click.echo(f"  ✓ {action}")

    config_path = result.get("config_path", "")
    if config_path and not config_path.startswith("("):
        click.echo(f"\nConfig: {config_path}")
        click.echo("Restart your agent to activate.")


@cli.command("setup-restore")
@click.option("--platform", "-p", default="", help="Force platform (claude-code, codex, cursor).")
def setup_restore(platform: str) -> None:
    """Restore the settings file backed up by the most recent `radiomind setup`.

    Looks for `<file>.radiomind-bak.YYYYMMDD-HHMMSS` next to the target
    file and copies the latest one back. Use this to undo a setup run
    without re-editing settings.json by hand.
    """
    from pathlib import Path as _P
    from radiomind.hooks.setup import detect_platform, restore_latest_backup

    plat = platform or detect_platform()
    if plat == "claude-code":
        target = _P.home() / ".claude" / "settings.json"
    elif plat == "codex":
        target = _P.home() / ".codex" / "hooks.json"
    elif plat == "cursor":
        target = _P.home() / ".cursor" / "mcp.json"
    else:
        click.echo(f"No known settings file for platform: {plat}")
        raise SystemExit(1)

    restored = restore_latest_backup(target)
    if restored is None:
        click.echo(f"No backup found next to {target}.")
        raise SystemExit(1)
    click.echo(f"Restored {target} from {restored.name}")


@cli.command("embed-backfill")
@click.option("--batch-size", default=50, help="Batch size for encoding.")
def embed_backfill(batch_size: int) -> None:
    """Backfill embeddings for existing memories without vectors.

    Useful after first-time install or after embedding package was added.
    Only processes memories where embedding IS NULL.
    """
    mind = _get_mind()

    if not mind._embedder:
        click.echo("Embedding encoder not available.")
        click.echo("Install: pip install 'radiomind[embedding]'")
        mind.shutdown()
        return

    rows = mind._store.conn.execute(
        "SELECT id, content FROM memories WHERE embedding IS NULL AND status='active'"
    ).fetchall()

    total = len(rows)
    if total == 0:
        click.echo("All memories already have embeddings.")
        mind.shutdown()
        return

    click.echo(f"Backfilling embeddings for {total} memories...")
    done = 0
    with click.progressbar(rows, label="Encoding") as bar:
        for row in bar:
            emb = mind._embedder.encode(row["content"])
            if emb:
                mind._store.conn.execute(
                    "UPDATE memories SET embedding = ? WHERE id = ?",
                    (emb, row["id"]),
                )
                done += 1
    mind._store.conn.commit()

    click.echo(f"Done: {done}/{total} encoded.")
    mind.shutdown()


@cli.command()
@click.argument("query")
@click.option("--domain", "-d", default=None, help="Filter by domain.")
@click.option("--pyramid/--flat", default=True, help="Use pyramid search (default) or flat.")
def search(query: str, domain: str | None, pyramid: bool) -> None:
    """Search memories (pyramid + habits)."""
    mind = _get_mind()

    if pyramid:
        results = mind.search_pyramid(query)
    else:
        results = mind.search(query, domain=domain)

    if not results:
        click.echo("No results found.")
        # CLIProductSmoke-1b (F3): without an embedder, retrieval is
        # keyword/FTS-only — natural-language questions often miss where
        # keywords would hit. Tell the user instead of looking broken.
        if mind._embedder is None:
            click.echo(
                "  note: no embedding model loaded — search is keyword (FTS) "
                "only, so phrase questions as keywords (e.g. 'network retry' "
                "not 'how do I handle network retries'). For semantic search: "
                "pip install radiomind[embedding], or enable a retrieval "
                "provider in config.toml."
            )
    else:
        for r in results:
            level = r.entry.level.name.lower()
            dom = r.entry.domain or "?"
            click.echo(f"  [{level}/{dom}] {r.entry.content}  (score={r.score:.2f}, method={r.method})")

    habits = mind.query_habits(query)
    if habits:
        click.echo("\nHabits:")
        for h in habits:
            status = h.status.value
            click.echo(f"  [{status}] {h.description}  (confidence={h.confidence:.1f})")

    mind.shutdown()


@cli.command()
@click.argument("file", type=click.Path(exists=True))
def ingest(file: str) -> None:
    """Ingest conversation history from JSONL file.

    Each line: {"role": "user"|"assistant", "content": "..."}
    """
    from radiomind.core.types import Message

    mind = _get_mind()
    messages = []

    with open(file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            messages.append(Message(role=data["role"], content=data["content"]))

    entries = mind.ingest(messages)
    click.echo(f"Processed {len(messages)} messages → {len(entries)} memories extracted")

    for e in entries:
        dom = e.domain or "?"
        click.echo(f"  [{dom}] {e.content}")

    mind.shutdown()


@cli.command("chat")
@click.option("--domain", "-d", default=None, help="Focus on a specific domain.")
def chat_refine(domain: str | None) -> None:
    """Trigger chat refinement (three-body debate)."""
    mind = _get_mind()

    if not mind.is_llm_available():
        click.echo("No LLM backend available. Is Ollama running?")
        mind.shutdown()
        return

    click.echo("Starting three-body debate...")
    result = mind.trigger_chat(domain=domain)
    click.echo(f"Done in {result.duration_s:.1f}s ({result.tokens_used} tokens)")
    click.echo(f"New insights: {len(result.new_insights)}")
    for insight in result.new_insights:
        click.echo(f"  [candidate] {insight.description} (confidence={insight.confidence:.1f})")

    mind.shutdown()


@cli.command()
def dream() -> None:
    """Trigger dream refinement (pruning + wandering)."""
    mind = _get_mind()

    if not mind.is_llm_available():
        click.echo("No LLM backend available. Is Ollama running?")
        mind.shutdown()
        return

    click.echo("Entering dream state...")
    result = mind.trigger_dream()
    click.echo(f"Done in {result.duration_s:.1f}s")
    click.echo(f"Merged: {result.merged}, Pruned: {result.pruned}")
    click.echo(f"Wandering insights: {len(result.new_insights)}")
    for insight in result.new_insights:
        click.echo(f"  [candidate] {insight.description}")

    mind.shutdown()


@cli.command("refine-step")
@click.argument("step", type=click.Choice(
    ["prepare", "guardian", "explorer", "reducer", "synthesize",
     "dream_prune", "dream_wander", "dream_apply"],
))
@click.option("--domain", "-d", default="", help="Domain to focus on.")
@click.option("--response", "-r", default="", help="Your response to the previous prompt.")
def refine_step(step: str, domain: str, response: str) -> None:
    """Step-by-step refinement — host AI does the thinking.

    Start: radiomind refine-step prepare --domain health
    Then follow the prompts returned by each step.

    \b
    Chat debate: prepare → guardian → explorer → reducer → synthesize
    Dream:       dream_prune → dream_apply
                 dream_wander → dream_apply
    """
    mind = _get_mind()
    result = mind.refine_step(step, domain=domain, response=response)

    if result.get("prompt"):
        click.echo("--- Prompt for you ---")
        click.echo(result["prompt"])
        click.echo("---")

    click.echo(f"Step: {result['step']} → next: {result.get('next_step', 'done')}")
    click.echo(result.get("context", ""))

    if result.get("insights"):
        click.echo(f"Insights: {len(result['insights'])}")
        for i in result["insights"]:
            click.echo(f"  - {i['description']} (confidence={i.get('confidence', '?')})")

    if result.get("actions"):
        click.echo(f"Actions: {len(result['actions'])}")
        for a in result["actions"]:
            click.echo(f"  - {a['type']}: {a.get('detail', a.get('description', a.get('id', '')))}")

    if result.get("done"):
        click.echo("Refinement complete.")

    mind.shutdown()


@cli.command()
def doctor() -> None:
    """Run a health check on the RadioMind install.

    Checks: home dir, database schema, embedding backend, LLM connectivity,
    platform hooks, RadioHeader conflicts. Prints PASS/WARN/FAIL per item.
    """
    import shutil as _sh
    from pathlib import Path

    from radiomind.core.config import Config

    checks: list[tuple[str, str, str]] = []  # (level, name, detail)

    def add(level: str, name: str, detail: str = "") -> None:
        checks.append((level, name, detail))

    cfg = Config.load()
    home = cfg.home

    if home.exists():
        add("PASS", "home directory", str(home))
    else:
        add("WARN", "home directory", f"{home} will be created on first use")

    db = cfg.db_path
    if db.exists():
        try:
            import sqlite3
            c = sqlite3.connect(str(db))
            v = c.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
            n = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            c.close()
            add("PASS", "database", f"schema v{v[0] if v else '?'}, {n} memories")
        except Exception as e:
            add("FAIL", "database", f"open failed: {e}")
    else:
        add("WARN", "database", "not created yet")

    try:
        from radiomind.storage.embedding import EmbeddingEncoder
        enc = EmbeddingEncoder(home / "models" / "embedding")
        if enc.load():
            add("PASS", "embedding model", "loaded")
        else:
            add("WARN", "embedding model", "not installed — run: pip install radiomind[embedding]")
    except Exception as e:
        add("WARN", "embedding model", f"unavailable: {type(e).__name__}")

    try:
        mind = _get_mind()
        if mind.is_llm_available():
            add("PASS", "LLM backend", _render_backends(mind._llm.backend_status()))
        else:
            add("WARN", "LLM backend", "no LLM — pure-memory mode only")

        # Habit grounding rate: refinement insights should carry evidence +
        # falsifier after P3. If many habits lack both, the LLM is skipping
        # the new structured output.
        habits = mind._habits.all_habits() if mind._habits else []
        active = [h for h in habits if h.status.value != "archived"]
        if active:
            grounded = sum(1 for h in active if h.evidence and h.falsifier)
            rate = grounded / len(active)
            if rate >= 0.6:
                add("PASS", "habit grounding", f"{grounded}/{len(active)} have evidence+falsifier")
            elif rate >= 0.3:
                add("WARN", "habit grounding", f"only {grounded}/{len(active)} carry evidence — run refinement with a stronger LLM")
            else:
                add("WARN", "habit grounding", f"{grounded}/{len(active)} grounded — most habits pre-date EVIDENCE/FALSIFIER prompts")
        mind.shutdown()
    except Exception as e:
        add("FAIL", "LLM check", str(e))

    try:
        from radiomind.hooks.setup import detect_platform, detect_radioheader
        plat = detect_platform()
        rh = detect_radioheader()
        add("PASS", "platform", plat + (" (RadioHeader detected)" if rh else ""))
    except Exception as e:
        add("WARN", "platform detect", str(e))

    claude_settings = Path.home() / ".claude" / "settings.json"
    if claude_settings.exists():
        try:
            import json as _j
            s = _j.loads(claude_settings.read_text())
            has_mcp = "radiomind" in s.get("mcpServers", {})
            has_hook = any(
                isinstance(h, dict) and "radiomind" in h.get("command", "").lower()
                for hooks_list in s.get("hooks", {}).values() if isinstance(hooks_list, list)
                for h in hooks_list
            )
            if has_mcp or has_hook:
                bits = []
                if has_mcp: bits.append("MCP")
                if has_hook: bits.append("hooks")
                add("PASS", "Claude Code integration", " + ".join(bits))
            else:
                add("WARN", "Claude Code integration", "not configured — run: radiomind setup")
        except Exception as e:
            add("WARN", "Claude Code integration", f"parse error: {e}")

    # CLIProductSmoke-1b (F4): the doctor itself is running through SOME
    # working entry point, so "not on PATH" is never a failure — only a
    # convenience note. Distinguish global PATH from the current invocation.
    import sys as _sys
    bin_path = _sh.which("radiomind")
    if bin_path:
        add("PASS", "radiomind CLI", f"on PATH — {bin_path}")
    else:
        entry = ("python -m radiomind"
                 if _sys.argv and _sys.argv[0].endswith("__main__.py")
                 else f"{_sys.executable} -m radiomind / venv script")
        add("PASS", "radiomind CLI",
            f"current entry works ({entry}); not on global PATH — "
            f"add it for a bare 'radiomind' command")

    # Print
    from click import style
    colors = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}
    fail_count = sum(1 for lvl, _, _ in checks if lvl == "FAIL")
    click.echo(f"RadioMind Doctor (v{__version__})")
    click.echo(f"Home: {home}")
    click.echo()
    for level, name, detail in checks:
        tag = style(f"[{level}]", fg=colors.get(level, "white"))
        click.echo(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    click.echo()
    if fail_count:
        click.echo(style(f"{fail_count} check(s) failed.", fg="red"))
        raise SystemExit(1)
    click.echo(style("All critical checks passed.", fg="green"))


@cli.command()
def status() -> None:
    """Show memory statistics and profiles."""
    mind = _get_mind()
    s = mind.stats()

    click.echo(f"RadioMind v{__version__}")
    click.echo(f"Home: {mind.config.home}")
    click.echo()
    click.echo(f"Memories: {s['total_active']} active, {s['archived']} archived")
    click.echo(f"  Facts:      {s['by_level']['fact']}")
    click.echo(f"  Patterns:   {s['by_level']['pattern']}")
    click.echo(f"  Principles: {s['by_level']['principle']}")
    # Habit breakdown by status + grounding rate
    all_habits = mind._habits.all_habits() if mind._habits else []
    by_status = {"candidate": 0, "confirmed": 0, "archived": 0}
    grounded = 0
    for h in all_habits:
        by_status[h.status.value] = by_status.get(h.status.value, 0) + 1
        if h.evidence and h.falsifier:
            grounded += 1
    active_habits = by_status["candidate"] + by_status["confirmed"]
    ground_pct = f"{grounded}/{active_habits} grounded" if active_habits else "no habits"
    click.echo(
        f"Habits (L3):  {s['habits']} total  "
        f"({by_status['confirmed']} confirmed, {by_status['candidate']} candidate, "
        f"{by_status['archived']} archived; {ground_pct})"
    )
    click.echo(f"Domains:      {s['domain_count']}")
    if s.get("domains"):
        for d in s["domains"]:
            click.echo(f"  - {d['name']} ({d['memory_count']} memories)")
    click.echo()
    llm_label = (_render_backends(mind._llm.backend_status())
                 if s['llm_available'] and mind._llm else "none")
    click.echo(f"LLM: {'available' if s['llm_available'] else 'unavailable'} ({llm_label})")
    click.echo(f"LLM calls: {s['llm_usage']['total_calls']} ({s['llm_usage']['total_tokens']} tokens)")
    click.echo()

    digest = mind.get_context_digest()
    if digest:
        click.echo("Context Digest:")
        click.echo(f"  {digest}")

    mind.shutdown()


# --- LoRA path: supported but opt-in (RADIOMIND_ENABLE_LORA=1) -------------
# 2026-06-12 LoRA-1b 4-arm A/B (bench/lora_ab/lora1b-pass-*.json): on the
# 0.5B Qwen recipe the adapter beats base under BOTH token-overlap and
# LLM-judge (20W/7L/1T), and the Ollama deploy path preserves quality even
# at q8_0 once the Modelfile carries TEMPLATE/stop/num_predict — the April
# "GGUF roundtrip loses LoRA signal" finding was re-attributed to the bare
# Modelfile (unterminated raw completion, 17k-token runaways read as
# timeouts). Stays opt-in (not default-on) because: (a) 4B-class bases
# still lose at current data scale (llm-judge-qwen3-4b.json), (b) training
# requires >=5 live habits which the 14-day zero-hit expiry can wipe
# (fuel-supply policy pending — LoRAFuel-1a).
import os as _os
_LORA_ENABLED = _os.environ.get("RADIOMIND_ENABLE_LORA", "").lower() in ("1", "true", "yes")


@cli.command(hidden=not _LORA_ENABLED)
@click.option("--model", default=None, help="MLX model to fine-tune (e.g. mlx-community/Qwen2.5-0.5B-Instruct-4bit)")
@click.option("--iters", default=None, type=int, help="Training iterations (default: 500)")
@click.option("--data-only", is_flag=True, help="Only generate training data, don't train.")
@click.option("--prepare-habits/--no-prepare-habits", "prepare", default=True,
              help="When the habit store is below the training threshold, "
                   "auto-run chat refinement over the largest domains to top "
                   "up fuel first (LoRAFuel-1b). No-op when fuel is sufficient.")
def train(model: str | None, iters: int | None, data_only: bool,
          prepare: bool) -> None:
    """[SUPPORTED, OPT-IN] LoRA fine-tuning — set RADIOMIND_ENABLE_LORA=1.

    \b
    Status (2026-06-12 4-arm A/B): supported on the 0.5B Qwen recipe —
    adapter beats base under token-overlap AND LLM-judge, and the Ollama
    deploy path preserves quality (bench/lora_ab/lora1b-pass-*.json).
    Opt-in because 4B-class bases still lose at current data scale, and
    training needs >=5 live habits (check `radiomind status` first).
    """
    if not _LORA_ENABLED:
        click.echo("LoRA is supported but opt-in.")
        click.echo("To enable: export RADIOMIND_ENABLE_LORA=1")
        click.echo("Evidence: bench/lora_ab/lora1b-pass-*.json (4-arm A/B).")
        raise SystemExit(1)
    mind = _get_mind()

    # LoRAFuel-1b: top up the habit store before data generation. The
    # 1a audit found nothing in the daily path ever mints habits, so a
    # fresh store always hit the >=MIN_HABITS guard. Conservative: only
    # fires when fuel is short; bounded domain count; --no-prepare-habits
    # opts out entirely.
    if prepare:
        from radiomind.training.data_gen import MIN_HABITS
        from radiomind.training.fuel import prepare_habits

        domains = [
            d["name"] for d in mind._store.list_domains() if d.get("name")
        ]  # already ordered by memory_count DESC
        prep = prepare_habits(
            mind._habits, domains, lambda dom: mind.trigger_chat(domain=dom),
            min_count=MIN_HABITS,
        )
        if prep.triggered:
            per_dom = ", ".join(f"{d}(+{n})" for d, n in prep.domains_refined)
            click.echo(
                f"prepare-habits: {prep.before} → {prep.after} habits "
                f"(need >= {prep.min_needed}); refined {len(prep.domains_refined)} "
                f"domain(s): {per_dom}"
            )
            if not prep.reached:
                click.echo(click.style(
                    f"prepare-habits failed: {prep.reason}", fg="yellow"))
        else:
            click.echo(
                f"prepare-habits: skipped — {prep.before} habits already "
                f">= {prep.min_needed}"
            )

    if data_only:
        report, path = mind.generate_training_data_with_report()
        if report.refused:
            for line in _render_train_gap(report, prepared=prepare):
                click.echo(click.style(line, fg="yellow"))
            mind.shutdown()
            return
        click.echo(f"Train: {report.train_count}  Valid: {report.valid_count}  → {path}")
        click.echo(
            f"  habits_used={report.habits_used}, domains_used={report.domains_used}, "
            f"dropped_pii={report.dropped_pii}, dropped_dup={report.dropped_dup}, "
            f"dropped_short={report.dropped_short}"
        )
        click.echo(f"  habit_ids={','.join(report.habit_ids)}")
        if report.narrow_adapter:
            click.echo(click.style(
                "  NARROW adapter: single-domain — fits this one topic, not a "
                "generalized personality. Add other topics for a full profile.",
                fg="yellow"))
        mind.shutdown()
        return

    from radiomind.training.lora import check_mlx_available
    available, msg = check_mlx_available()
    if not available:
        click.echo(msg)
        click.echo("\nYou can still generate training data with: radiomind train --data-only")
        mind.shutdown()
        return

    kwargs = {}
    if model:
        kwargs["model"] = model
    if iters:
        kwargs["iterations"] = iters

    click.echo("Generating training data...")
    report, data_path = mind.generate_training_data_with_report()
    if report.refused:
        for line in _render_train_gap(report, prepared=prepare):
            click.echo(click.style(line, fg="yellow"))
        mind.shutdown()
        return
    click.echo(f"  Train: {report.train_count}  Valid: {report.valid_count}")

    click.echo("Starting LoRA fine-tuning (this may take a few minutes)...")
    result = mind.train(**kwargs)

    if result.success:
        click.echo(f"Training complete in {result.duration_s:.1f}s")
        click.echo(f"  Model: {result.model}")
        click.echo(f"  Adapter: {result.adapter_path}")
        if result.narrow_adapter:
            click.echo(click.style(
                "  NARROW adapter: trained on a single domain — fits this one "
                "topic, not a generalized personality.", fg="yellow"))
        click.echo(f"\nTo load in Ollama:")
        click.echo(f"  radiomind deploy")
    else:
        click.echo(f"Training failed: {result.error}")

    mind.shutdown()


@cli.command(hidden=not _LORA_ENABLED)
@click.option("--base", default="qwen2.5:0.5b", help="Ollama base model name.")
@click.option("--name", default="radiomind-personal", help="Name to register under.")
@click.option("--mlx-base", default="mlx-community/Qwen2.5-0.5B-Instruct-4bit",
              help="MLX base model (must match the one used for training).")
@click.option("--llama-cpp-convert", default="",
              help="Path to llama.cpp convert_hf_to_gguf.py (or set $LLAMA_CPP_CONVERT).")
def deploy(base: str, name: str, mlx_base: str, llama_cpp_convert: str) -> None:
    """[SUPPORTED, OPT-IN] Fuse + GGUF-convert + register LoRA with Ollama.

    Gated: requires RADIOMIND_ENABLE_LORA=1. The April "GGUF roundtrip
    degrades quality" finding was re-attributed by the 2026-06-12 4-arm
    A/B: the real defect was a bare Modelfile (no TEMPLATE/stop ->
    unterminated raw completion). With the template fix, q8_0 deploy is
    on par with MLX-direct. See bench/lora_ab/lora1b-pass-q8.json.
    """
    if not _LORA_ENABLED:
        click.echo("LoRA deploy is supported but opt-in.")
        click.echo("To enable: export RADIOMIND_ENABLE_LORA=1")
        raise SystemExit(1)
    from radiomind.training.lora import export_to_ollama
    from radiomind.core.config import Config

    cfg = Config.load()
    adapter_path = cfg.home / "models" / "lora" / "adapters"

    if not adapter_path.exists():
        click.echo("No trained adapter found. Run 'radiomind train' first.")
        return

    click.echo(f"Fusing adapter + base ({mlx_base}) → GGUF → Ollama ({name})...")
    success, msg = export_to_ollama(
        adapter_path,
        base_model=base,
        model_name=name,
        mlx_base_model=mlx_base,
        llama_cpp_convert=llama_cpp_convert,
    )
    click.echo(msg)
    if not success:
        raise SystemExit(1)


@cli.command("learn")
@click.argument("text")
def learn_text(text: str) -> None:
    """Add external knowledge (text) to L2 facts."""
    mind = _get_mind()
    entries = mind.learn(text)
    click.echo(f"Learned {len(entries)} entry(s)")
    mind.shutdown()


@cli.command("push-habits")
@click.option("--platform", "-p", default=None, help="Force: claude-code, codex, cursor")
@click.option("--project-dir", default=None, help="Project directory (default: cwd)")
@click.option("--dry-run", is_flag=True, help="Preview without writing")
def push_habits(platform: str | None, project_dir: str | None, dry_run: bool) -> None:
    """Push confirmed habits to host platform's native memory.

    \b
    Writes to:
      Claude Code → ~/.claude/projects/{project}/memory/radiomind_habits.md
      Codex       → .codex/AGENTS.md
      Cursor      → .cursorrules

    Idempotent. Uses markers to track individual habits — updates changed
    ones, removes archived ones, skips duplicates.
    """
    mind = _get_mind()
    result = mind.push_habits(platform=platform, project_dir=project_dir, dry_run=dry_run)
    if result.get("error"):
        click.echo(f"Error: {result['error']}")
    else:
        prefix = "[dry-run] " if dry_run else ""
        click.echo(f"{prefix}Target: {result['path']}")
        click.echo(f"{prefix}Written: {result['written']}, Updated: {result['updated']}, Removed: {result['removed']}")
    mind.shutdown()


@cli.command("migrate-radioheader")
@click.option("--path", default=None, help="RadioHeader home (default: ~/.claude/radioheader)")
def migrate_radioheader(path: str | None) -> None:
    """Import RadioHeader topics/shortwave/registry into RadioMind."""
    from pathlib import Path
    from radiomind.adapters.radioheader import RadioHeaderAdapter

    mind = _get_mind()
    rh_home = Path(path) if path else None
    adapter = RadioHeaderAdapter(mind, radioheader_home=rh_home)

    click.echo("Migrating RadioHeader data into RadioMind...")
    result = adapter.migrate()
    click.echo(f"  Topics:    {result.topics_imported} imported")
    click.echo(f"  Shortwave: {result.shortwave_imported} imported")
    click.echo(f"  Projects:  {result.projects_imported} imported")
    click.echo(f"  Skipped:   {result.skipped_duplicates} duplicates")
    if result.errors:
        click.echo(f"  Errors:    {len(result.errors)}")
        for e in result.errors[:5]:
            click.echo(f"    - {e}")

    s = mind.stats()
    click.echo(f"\nRadioMind now has {s['total_active']} memories across {s['domain_count']} domains")
    mind.shutdown()


@cli.command("rh-search")
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Max results.")
def rh_search(query: str, limit: int) -> None:
    """Search using RadioHeader-compatible output format."""
    from radiomind.adapters.radioheader import RadioHeaderAdapter

    mind = _get_mind()
    adapter = RadioHeaderAdapter(mind)
    result = adapter.search(query, limit=limit)

    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    mind.shutdown()


@cli.command("rh-consolidate")
@click.option("--dry-run", is_flag=True, help="Preview changes without modifying files.")
def rh_consolidate(dry_run: bool) -> None:
    """Run RadioHeader-compatible consolidation (dream + digest)."""
    from radiomind.adapters.radioheader import RadioHeaderAdapter

    mind = _get_mind()

    if dry_run:
        s = mind.stats()
        click.echo(f"[dry-run] Would consolidate {s['total_active']} memories across {s['domain_count']} domains")
        click.echo(f"[dry-run] Habits: {s['habits']}, LLM: {'available' if mind.is_llm_available() else 'unavailable'}")
        mind.shutdown()
        return

    if not mind.is_llm_available():
        click.echo("No LLM backend available.")
        mind.shutdown()
        return

    adapter = RadioHeaderAdapter(mind)
    click.echo("Running consolidation...")
    result = adapter.consolidate()
    click.echo(f"  Merged: {result['merged']}")
    click.echo(f"  Pruned: {result['pruned']}")
    click.echo(f"  Insights: {result['insights']}")
    click.echo(f"  Digest: {result['digest_written']}")
    mind.shutdown()


@cli.command()
@click.option("--host", default="0.0.0.0", help="Bind host")
@click.option("--port", default=8730, help="Bind port")
def serve(host: str, port: int) -> None:
    """Start REST API server (FastAPI + Uvicorn).

    API docs: http://localhost:8730/docs
    """
    try:
        from radiomind.server import run_server
        click.echo(f"Starting RadioMind REST API on {host}:{port}")
        click.echo(f"API docs: http://localhost:{port}/docs")
        run_server(host=host, port=port)
    except ImportError:
        click.echo("FastAPI not installed. Run: pip install 'radiomind[server]'")


@cli.group("community")
def community() -> None:
    """Community knowledge sharing (Stigmergy model)."""


@community.command("sync")
@click.option("--source", default=None, help="RadioHeader community path")
def community_sync(source: str | None) -> None:
    """Sync community entries from RadioHeader's community pool."""
    from pathlib import Path
    from radiomind.community.pool import CommunityPool

    mind = _get_mind()
    pool = CommunityPool(mind, community_dir=mind.config.home / "community")
    pool.open()

    rh_path = Path(source) if source else None
    result = pool.sync_from_radioheader(rh_path)
    click.echo(f"Imported: {result.imported}, Skipped: {result.skipped}")
    if result.errors:
        for e in result.errors[:3]:
            click.echo(f"  Error: {e}")

    pool.close()
    mind.shutdown()


@community.command("contribute")
@click.option("--min-confidence", default=0.7, help="Min habit confidence to contribute")
def community_contribute(min_confidence: float) -> None:
    """Contribute personal insights to the community (with PII filtering)."""
    from radiomind.community.pool import CommunityPool

    mind = _get_mind()
    pool = CommunityPool(mind)
    pool.open()

    result = pool.contribute(min_confidence=min_confidence)
    click.echo(f"Contributed: {result.contributed}")
    click.echo(f"Filtered (PII): {result.filtered_pii}")
    click.echo(f"Skipped (privacy): {result.skipped_privacy}")
    click.echo(f"Skipped (duplicate): {result.skipped_duplicate}")

    pool.close()
    mind.shutdown()


@community.command("vote")
@click.argument("entry_id")
@click.argument("vote", type=click.Choice(["+1", "-1"]))
def community_vote(entry_id: str, vote: str) -> None:
    """Vote on a community entry."""
    from radiomind.community.pool import CommunityPool

    mind = _get_mind()
    pool = CommunityPool(mind)
    pool.open()

    v = 1 if vote == "+1" else -1
    result = pool.vote(entry_id, v)
    click.echo(f"Score: {result['final_score']} (verified: {result['verified']})")

    pool.close()
    mind.shutdown()


@community.command("stats")
def community_stats() -> None:
    """Show community sharing statistics."""
    from radiomind.community.pool import CommunityPool

    mind = _get_mind()
    pool = CommunityPool(mind)
    pool.open()

    s = pool.stats()
    click.echo(f"Community entries: {s['total_entries']}")
    click.echo(f"  Verified: {s['verified']}")
    click.echo(f"  Archivable: {s['archivable']}")
    click.echo(f"  Total votes: {s['total_votes']}")
    click.echo(f"  Pool files: {s['pool_files']}")
    click.echo(f"  Contributions: {s['contributions']}")

    pool.close()
    mind.shutdown()


@cli.command("mcp-server")
def mcp_server() -> None:
    """Start RadioMind MCP server (stdio transport).

    For Claude Desktop:
      claude mcp add radiomind -- radiomind mcp-server
    """
    from radiomind.mcp_server import main as mcp_main
    mcp_main()


@cli.command()
@click.argument("key", required=False)
@click.argument("value", required=False)
def config(key: str | None, value: str | None) -> None:
    """View or modify configuration."""
    from radiomind.core.config import Config

    cfg = Config.load()
    if key is None:
        click.echo(json.dumps(cfg.data, indent=2))
    elif value is None:
        click.echo(f"{key} = {cfg.get(key)}")
    else:
        cfg.set(key, value)
        cfg.save()
        click.echo(f"Set {key} = {value}")
