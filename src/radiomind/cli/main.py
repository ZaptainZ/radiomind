"""RadioMind CLI — command-line interface."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import click

from radiomind import __version__


def _get_mind():
    from radiomind.core.mind import RadioMind
    mind = RadioMind()
    mind.initialize()
    return mind


def _get_library():
    """Lightweight library access — opens just the SQLite store, NOT the full mind.

    Library ops are pure SQLite; `_get_mind()` would load the embedding model (onnxruntime) on every
    subprocess invocation, which is slow on low-power hosts and can exceed a caller's timeout.
    """
    from radiomind.core.config import Config
    from radiomind.storage.database import MemoryStore
    from radiomind.storage.library import LibraryStore

    cfg = Config.load()
    store = MemoryStore(cfg.db_path)
    store.open()
    return store, LibraryStore(store.conn)


def _get_library_kg():
    """Open the knowledge graph directly (for `library link`) without loading the full mind."""
    from radiomind.core.config import Config
    from radiomind.storage.knowledge_graph import KnowledgeGraph

    cfg = Config.load()
    kg = KnowledgeGraph(cfg.db_path.parent / "knowledge.db")
    kg.open()
    return kg


def _get_lifelog():
    """Lightweight life-log access — opens just the SQLite store, NOT the full mind
    (same reasoning as `_get_library`: avoid loading the embedding model per call)."""
    from radiomind.core.config import Config
    from radiomind.storage.database import MemoryStore
    from radiomind.storage.lifelog import LifelogStore

    cfg = Config.load()
    store = MemoryStore(cfg.db_path)
    store.open()
    return store, LifelogStore(store.conn)


def _get_speakers():
    """Lightweight speaker-gallery access (same reasoning as `_get_library`).
    Match thresholds come from config so they can be recalibrated without a code change."""
    from radiomind.core.config import Config
    from radiomind.storage.database import MemoryStore
    from radiomind.storage.speakers import MatchPolicy, SpeakerStore

    cfg = Config.load()
    store = MemoryStore(cfg.db_path)
    store.open()
    return store, SpeakerStore(store.conn, policy=MatchPolicy.from_config(cfg))


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


def _render_retrieval_status(st: dict) -> str:
    """ManagedRetrieval-1b: one-line retrieval-egress posture for status/doctor.

    `st` = radiomind.core.retrieval_consent.retrieval_egress_status(...).
    States the active mode and whether memory/query text leaves the device.
    """
    line = f"retrieval: {st['mode']}"
    if st["remote_active"]:
        line += " — memory/query/candidate text is sent to a third-party API"
    elif st["remote_key_present"] and not st["remote_consented"]:
        line += (
            " (remote retrieval available but disabled until consent: set "
            "RADIOMIND_REMOTE_RETRIEVAL=1 or retrieval.remote.consent=true)"
        )
    return line


def _render_retrieval_tier(state: dict) -> list[str]:
    """RetrievalUX-1a: position the local retrieval ladder for onboard/doctor.

    Shows the current tier and, when below the recommended local-embedding tier,
    nudges toward `radiomind[embedding]`. The reranker is suggested only when the
    machine is a good fit (state['reranker_reco']); otherwise quietly skipped.
    Remote stays a consent-gated BYOK option, never pushed as default.
    """
    from radiomind.core.retrieval_tier import EMBEDDING_INSTALL, EMBEDDING_NOTE

    lines = [f"retrieval tier: {state['retrieval_tier']}"]
    if not state.get("embedding_installed") and not state.get("remote_retrieval_consent"):
        lines.append(f"  - recommended: {EMBEDDING_INSTALL}  ({EMBEDDING_NOTE})")
    elif state.get("embedding_installed"):
        lines.append("  - best local retrieval active (on-device embedding)")
    reco = state.get("reranker_reco") or {}
    if not state.get("reranker_installed"):
        if reco.get("recommended") and reco.get("install_command"):
            lines.append(f"  - advanced (best local quality): {reco['install_command']}  "
                         f"({reco['estimated_disk']})")
        elif reco.get("reason"):
            lines.append(f"  - {reco['reason']}")
    return lines


def _render_retrieval_consent(consented: bool, key_present: bool) -> str:
    """ManagedRetrieval-1b: onboard posture line (config-only, no live mind).

    Default is local-only; remote retrieval is opt-in and, when enabled, sends
    memory/query/candidate text to a third-party API.
    """
    if consented:
        return ("retrieval: remote embedding/rerank CONSENTED — "
                "memory/query/candidate text will be sent to a third-party API")
    if key_present:
        return ("retrieval: local-only (remote embedding/rerank available but "
                "OFF until consent: RADIOMIND_REMOTE_RETRIEVAL=1 or "
                "retrieval.remote.consent=true)")
    return "retrieval: local-only (no remote retrieval credentials configured)"


_LLM_ENV_VARS = (
    "DASHSCOPE_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
)


def _config_path(cfg) -> Path:
    return cfg._path or (cfg.home / "config.toml")


def _configured_llm_profiles(cfg) -> list[str]:
    llm = cfg.get("llm", {}) or {}
    out: list[str] = []
    default = llm.get("default_backend", "")
    for name, sec in llm.items():
        if name in ("default_backend", "models"):
            continue
        if not isinstance(sec, dict):
            continue
        if name == "ollama":
            if sec.get("host"):
                out.append("ollama")
            continue
        if sec.get("base_url") and sec.get("api_key"):
            out.append(name)
    if default in out:
        out.remove(default)
        out.insert(0, f"{default} [default]")
    return out


def _memory_count(db_path: Path) -> int | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        count = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        conn.close()
        return count
    except Exception:
        return None


def _config_template(home: Path) -> str:
    """A commented standalone config template.

    `radiomind init` intentionally stays light and does not write a config.
    This template is opt-in for power users who want an explicit file.
    """
    return f"""# RadioMind config template
# Generated by `radiomind onboard --write-config-template`.
#
# Most users do not need this file:
# - host agents can pass llm=host_llm,
# - API-key environment variables are auto-detected,
# - local Ollama works when a model is installed.

[general]
home = "{home}"
log_level = "info"

[llm]
# Fill ONE backend below, then set it here. dashscope/openrouter/openai_direct
# use OpenAI-compatible chat/completions APIs.
default_backend = "dashscope"

[llm.dashscope]
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key = ""
model = "qwen-plus"
timeout = 120
max_tokens = 2048

[llm.openrouter]
base_url = "https://openrouter.ai/api/v1"
api_key = ""
model = "openai/gpt-4o-mini"
timeout = 120
max_tokens = 2048

[llm.ollama]
host = "http://localhost:11434"
model = "qwen3:0.6b"

[llm.openai]
# Optional, not the recommended default unless you already use OpenAI directly.
deprecated = true
base_url = "https://api.openai.com/v1"
api_key = ""
model = "gpt-4o-mini"
timeout = 120
max_tokens = 2048

[retrieval.reranker]
enabled = false
model = "BAAI/bge-reranker-v2-m3"

[retrieval.query_rewriter]
enabled = false

[retrieval.remote]
# Remote embedding/rerank send memory text, search queries, and candidate
# snippets to a third-party API. Default OFF — local-only. Set to true (or
# export RADIOMIND_REMOTE_RETRIEVAL=1) to consent. Without consent, a configured
# retrieval provider / DashScope key is NOT used for retrieval; search stays
# local (on-device embedding if installed, otherwise keyword/FTS).
consent = false
"""


def _onboard_state() -> dict:
    from radiomind.core.config import Config
    from radiomind.core.retrieval_consent import (
        remote_retrieval_consented,
        remote_retrieval_key_present,
    )

    from radiomind.core.retrieval_tier import (
        detect_retrieval_tier,
        local_reranker_recommendation,
    )

    cfg = Config.load()
    cfg_path = _config_path(cfg)
    env_keys = [k for k in _LLM_ENV_VARS if os.environ.get(k)]
    rh_home = Path.home() / ".claude" / "radioheader"
    config_exists = cfg_path.exists()
    tier = detect_retrieval_tier(cfg)
    reranker_reco = (local_reranker_recommendation(cfg.home)
                     if not tier["reranker_installed"] else None)
    return {
        "home": str(cfg.home),
        "config_path": str(cfg_path),
        "config_exists": config_exists,
        "db_path": str(cfg.db_path),
        "db_exists": cfg.db_path.exists(),
        "memory_count": _memory_count(cfg.db_path),
        "env_llm_keys": env_keys,
        "config_llm_profiles": _configured_llm_profiles(cfg) if config_exists else [],
        "radioheader_detected": rh_home.exists(),
        "lora_enabled": os.environ.get("RADIOMIND_ENABLE_LORA", "").lower()
        in ("1", "true", "yes"),
        "managed_retrieval": "future / not configured",
        "remote_retrieval_consent": remote_retrieval_consented(cfg),
        "remote_retrieval_key": remote_retrieval_key_present(cfg),
        "retrieval_tier": tier["tier"],
        "embedding_installed": tier["embedding_installed"],
        "reranker_installed": tier["reranker_installed"],
        "reranker_reco": reranker_reco,
    }


def _render_onboard(state: dict) -> list[str]:
    def yn(v: bool) -> str:
        return "yes" if v else "no"

    mem = state["memory_count"]
    mem_s = "not created" if mem is None else str(mem)
    env_s = ", ".join(state["env_llm_keys"]) or "none"
    cfg_s = ", ".join(state["config_llm_profiles"]) or "none"
    lines = [
        "RadioMind onboarding",
        "",
        "Entry route:",
        "  Coding agents (Claude Code/Codex/Cursor/Windsurf): use RadioHeader first.",
        "  Personal agents (Hermes/OpenClaw/RadioHand): use the RadioMind provider.",
        "  Power users: use RadioMind CLI / Python / MCP directly.",
        "",
        "Current setup:",
        f"  home:        {state['home']}",
        f"  config:      {yn(state['config_exists'])} ({state['config_path']})",
        f"  database:    {yn(state['db_exists'])} ({state['db_path']})",
        f"  memories:    {mem_s}",
        f"  env LLM:     {env_s}",
        f"  config LLM:  {cfg_s}",
        f"  RadioHeader: {yn(state['radioheader_detected'])}",
        f"  LoRA opt-in: {yn(state['lora_enabled'])}",
        f"  managed retrieval: {state['managed_retrieval']}",
        "  " + _render_retrieval_consent(
            state.get("remote_retrieval_consent", False),
            state.get("remote_retrieval_key", False),
        ),
    ]
    if state.get("retrieval_tier"):
        lines += ["  " + ln for ln in _render_retrieval_tier(state)]
    lines += [
        "",
        "Recommended next steps:",
    ]
    if not state["config_exists"]:
        lines.append(
            "  - No config file is required for basic use. If you want an explicit "
            "template, run: radiomind onboard --write-config-template"
        )
    if not state["env_llm_keys"] and not state["config_llm_profiles"]:
        lines.append(
            "  - For LLM-backed refine/dream/train, prefer a host LLM first; "
            "otherwise set an API-key env var or fill one config profile."
        )
    if not state["db_exists"]:
        lines.append(
            "  - Add your first memory: radiomind learn \"I prefer concise answers.\""
        )
    else:
        lines.append("  - Inspect health: radiomind doctor")
    if state["radioheader_detected"]:
        lines.append(
            "  - RadioHeader is present. For programming agents, keep RadioHeader "
            "as the entry point and RadioMind as the optional memory backend."
        )
    else:
        lines.append(
            "  - Programming-agent users should install/configure RadioHeader first."
        )
    lines.append(
        "  - Personal LoRA is opt-in: RADIOMIND_ENABLE_LORA=1 radiomind train "
        "--prepare-habits (after enough memories)."
    )
    return lines


def _write_config_template(path: Path, home: Path, force: bool) -> None:
    if path.exists() and not force:
        raise click.ClickException(
            f"Config already exists at {path}. Use --force to overwrite."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_config_template(home))


@click.group()
@click.version_option(__version__, prog_name="radiomind")
def cli() -> None:
    """RadioMind — Bionic memory core for AI agents."""


@cli.command()
def init() -> None:
    """Initialize RadioMind data directory."""
    mind = _get_mind()
    click.echo(f"RadioMind initialized at {mind.config.home}")
    click.echo("Next: run `radiomind onboard` for setup guidance.")
    mind.shutdown()


@cli.command()
@click.option("--write-config-template", is_flag=True,
              help="Write a commented config.toml template. Asks before writing.")
@click.option("--print-config-template", is_flag=True,
              help="Print the config template instead of writing it.")
@click.option("--force", is_flag=True, help="Overwrite an existing config template.")
@click.option("-y", "--yes", is_flag=True, help="Do not prompt when writing.")
def onboard(write_config_template: bool, print_config_template: bool,
            force: bool, yes: bool) -> None:
    """Show first-run guidance without changing anything by default."""
    from radiomind.core.config import Config

    cfg = Config.load()
    cfg_path = _config_path(cfg)

    if print_config_template:
        click.echo(_config_template(cfg.home))
        return

    if write_config_template:
        if cfg_path.exists() and not force:
            raise click.ClickException(
                f"Config already exists at {cfg_path}. Use --force to overwrite."
            )
        if not yes:
            click.confirm(f"Write config template to {cfg_path}?", abort=True)
        _write_config_template(cfg_path, cfg.home, force=force)
        click.echo(f"Wrote config template: {cfg_path}")
        click.echo("Fill one LLM profile only if you need standalone LLM-backed features.")
        return

    for line in _render_onboard(_onboard_state()):
        click.echo(line)


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
                "not 'how do I handle network retries'). For local semantic "
                "search: pip install radiomind[embedding]. For remote "
                "embedding (sends text to a third-party API) configure a "
                "retrieval provider AND consent: RADIOMIND_REMOTE_RETRIEVAL=1 "
                "or retrieval.remote.consent=true."
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
            # Open via MemoryStore so pending migrations apply first — then the reported version is
            # the true on-disk schema, not a stale constant or a pre-migration table value.
            from radiomind.storage.database import MemoryStore
            from radiomind.storage.migrations import CURRENT_SCHEMA_VERSION

            store = MemoryStore(db)
            store.open()
            v = store.conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            n = store.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            store.close()
            ver = v[0] if v else 0
            if ver == CURRENT_SCHEMA_VERSION:
                add("PASS", "database", f"schema v{ver}, {n} memories")
            else:
                add("WARN", "database", f"schema v{ver}, code targets v{CURRENT_SCHEMA_VERSION} (migration incomplete)")
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

    # RetrievalUX-1a: position the local retrieval ladder + conditional reranker
    # advice. Pure detection (no model load); embedding = recommended default,
    # reranker = advanced and only suggested when the machine is a good fit.
    try:
        from radiomind.core.retrieval_tier import (
            EMBEDDING_INSTALL, detect_retrieval_tier, local_reranker_recommendation,
        )
        tier = detect_retrieval_tier(cfg)
        add("PASS", "retrieval tier", tier["tier"])
        if not tier["embedding_installed"] and not tier["remote_consented"]:
            add("WARN", "local embedding",
                f"recommended for higher-quality local search — {EMBEDDING_INSTALL} "
                "(on-device ONNX MiniLM ~86MB; text stays local)")
        if not tier["reranker_installed"]:
            reco = local_reranker_recommendation(home)
            if reco["recommended"] and reco["install_command"]:
                add("PASS", "local reranker",
                    f"advanced best-quality option — {reco['install_command']} "
                    f"({reco['estimated_disk']})")
            else:
                add("PASS", "local reranker", reco["reason"])
    except Exception as e:
        add("WARN", "retrieval tier", f"unavailable: {type(e).__name__}")

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

        # ManagedRetrieval-1b: surface the retrieval data-egress posture.
        from radiomind.core.retrieval_consent import retrieval_egress_status
        rstate = retrieval_egress_status(mind.config, mind._embedder, mind._reranker)
        if rstate["remote_active"]:
            add("WARN", "retrieval egress",
                "remote embedding/rerank ENABLED — memory/query/candidate text "
                "is sent to a third-party API")
        elif rstate["remote_key_present"] and not rstate["remote_consented"]:
            add("PASS", "retrieval egress",
                f"{rstate['mode']}; remote available but disabled until consent "
                "(RADIOMIND_REMOTE_RETRIEVAL=1 or retrieval.remote.consent=true)")
        else:
            add("PASS", "retrieval egress", f"{rstate['mode']} — local-only")
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

    # ManagedRetrieval-1b: make the retrieval data-egress posture visible.
    # RetrievalUX-1a: also show the canonical tier label (consistent with
    # onboard/doctor) above the active-egress line.
    from radiomind.core.retrieval_consent import retrieval_egress_status
    from radiomind.core.retrieval_tier import detect_retrieval_tier
    click.echo(f"retrieval tier: {detect_retrieval_tier(mind.config)['tier']}")
    rstate = retrieval_egress_status(mind.config, mind._embedder, mind._reranker)
    click.echo(_render_retrieval_status(rstate))
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


# --- Knowledge Library (信息收集库) -------------------------------------------
# RadioHand calls these via subprocess and parses the JSON on stdout.

@cli.group("library")
def library() -> None:
    """信息收集库 — capture and search collected external sources."""


@library.command("put")
@click.option("--payload", default="", help="JSON capture payload (title/source_url/summary/tags/...).")
@click.option("--title", default="")
@click.option("--url", default="")
@click.option("--summary", default="")
@click.option("--content-hash", default="")
@click.option("--user", default="")
@click.option("--no-dedup", is_flag=True, default=False)
def library_put(payload: str, title: str, url: str, summary: str, content_hash: str,
                user: str, no_dedup: bool) -> None:
    """Add a captured source. Returns {"id", "duplicate", "tags"} as JSON."""
    from radiomind.storage.library import LibraryItem, content_hash as _chash

    data: dict = {}
    if payload:
        data = json.loads(payload)
    title = data.get("title", title)
    url = data.get("source_url", url)
    summary = data.get("short_summary", summary)
    body = data.get("body", "")
    chash = data.get("content_hash") or content_hash or (_chash(body) if body else "")
    tags = data.get("tags", [])  # [{"name","facet","confidence","source"} | "name"]

    item = LibraryItem(
        title=title,
        source_url=url,
        source_domain=data.get("source_domain", ""),
        source_type=data.get("source_type", "article"),
        author=data.get("author", ""),
        published_at=data.get("published_at"),
        language=data.get("language", ""),
        content_hash=chash,
        short_summary=summary,
        key_points=data.get("key_points", []),
        why_it_matters=data.get("why_it_matters", ""),
        useful_for=data.get("useful_for", []),
        open_questions=data.get("open_questions", []),
        user_id=data.get("user_id", user),
        metadata=data.get("metadata", {}),
    )
    store, lib = _get_library()
    item_id, dup = lib.put_item(item, dedup=not no_dedup)
    applied = []
    if not dup:
        for t in tags:
            if isinstance(t, str):
                name, facet, conf, src = t, "topic", 1.0, "llm"
            else:
                name, facet = t.get("name", ""), t.get("facet", "topic")
                conf, src = float(t.get("confidence", 1.0)), t.get("source", "llm")
            if not name:
                continue
            tag_id = lib.upsert_tag(name, facet)
            lib.tag_item(item_id, tag_id, conf, src)
            applied.append({"name": name, "facet": facet})
    else:
        applied = [{"name": t["name"], "facet": t["facet"]} for t in lib.item_tags(item_id)]
    click.echo(json.dumps({"id": item_id, "duplicate": dup, "tags": applied}, ensure_ascii=False))
    store.close()


@library.command("get")
@click.argument("item_id", type=int)
def library_get(item_id: int) -> None:
    """Get one item (full digest + tags) as JSON."""
    store, lib = _get_library()
    item = lib.get_item(item_id)
    click.echo(json.dumps(item, ensure_ascii=False) if item else json.dumps({"error": "not found"}))
    store.close()


@library.command("search")
@click.argument("query")
@click.option("--tag", "-t", default="")
@click.option("--limit", "-n", default=10)
@click.option("--user", default="")
def library_search(query: str, tag: str, limit: int, user: str) -> None:
    """Search the library (FTS over title+summary). Returns a JSON list."""
    store, lib = _get_library()
    results = lib.search_items(query, limit=limit, tag=tag, user_id=user)
    click.echo(json.dumps(results, ensure_ascii=False))
    store.close()


@library.command("list")
@click.option("--limit", "-n", default=20)
@click.option("--status", default="active")
@click.option("--user", default="")
def library_list(limit: int, status: str, user: str) -> None:
    """List recent items as JSON."""
    store, lib = _get_library()
    click.echo(json.dumps(lib.list_items(limit=limit, status=status, user_id=user), ensure_ascii=False))
    store.close()


@library.command("tag")
@click.argument("item_id", type=int)
@click.argument("name")
@click.option("--facet", default="topic")
@click.option("--confidence", default=1.0)
@click.option("--source", default="user")
def library_tag(item_id: int, name: str, facet: str, confidence: float, source: str) -> None:
    """Attach a tag to an item (user correction uses --source user)."""
    store, lib = _get_library()
    tag_id = lib.upsert_tag(name, facet)
    lib.tag_item(item_id, tag_id, confidence, source)
    click.echo(json.dumps({"item_id": item_id, "tag_id": tag_id, "name": name, "facet": facet}, ensure_ascii=False))
    store.close()


@library.command("tag-merge")
@click.argument("alias_name")
@click.argument("canonical_name")
@click.option("--facet", default="topic")
def library_tag_merge(alias_name: str, canonical_name: str, facet: str) -> None:
    """Merge an alias tag into a canonical tag (hygiene)."""
    store, lib = _get_library()
    canon_id = lib.merge_tag(alias_name, canonical_name, facet)
    click.echo(json.dumps({"canonical_id": canon_id, "merged": alias_name, "into": canonical_name}, ensure_ascii=False))
    store.close()


@library.command("link")
@click.argument("subject")
@click.argument("relation")
@click.argument("obj")
@click.option("--source-id", type=int, default=None, help="library_items.id this claim/relation came from")
@click.option("--confidence", default=1.0)
def library_link(subject: str, relation: str, obj: str, source_id: int | None, confidence: float) -> None:
    """Add a claim/relation as a knowledge-graph triple (reuses the existing KG, no second graph)."""
    kg = _get_library_kg()
    tid = kg.add_triple(subject, relation, obj, source_id=source_id, confidence=confidence)
    click.echo(json.dumps({"triple_id": tid, "subject": subject, "relation": relation, "object": obj}, ensure_ascii=False))
    kg.close()


@library.command("stats")
@click.option("--user", default="")
def library_stats(user: str) -> None:
    """Library counts (items / active / archived / tags) as JSON."""
    store, lib = _get_library()
    click.echo(json.dumps(lib.stats(user_id=user), ensure_ascii=False))
    store.close()


# --- Life Log (生活日志) ------------------------------------------------------
# Time-anchored episodes + day profiles from the ambient-audio pipeline.
# RadioHand calls these via subprocess and parses the JSON on stdout.

@cli.group("lifelog")
def lifelog() -> None:
    """生活日志 — time-anchored episodes + day profiles from ambient audio."""


def _put_episode(ll, data: dict, user: str):
    from radiomind.storage.lifelog import LifelogEpisode
    ep = LifelogEpisode(
        date=data.get("date", ""), start_clock=data.get("start", data.get("start_clock", "")),
        end_clock=data.get("end", data.get("end_clock", "")),
        started_at=float(data.get("started_at", 0) or 0),
        ended_at=float(data.get("ended_at", 0) or 0), tz=data.get("tz", ""),
        activity=data.get("activity", ""),
        participants=data.get("participants", []), topics=data.get("topics", []),
        media=data.get("media", []), summary=data.get("summary", ""),
        user_id=data.get("user_id", user), metadata=data.get("metadata", {}),
    )
    return ll.put_episode(ep)


def _put_day(ll, data: dict, user: str):
    from radiomind.storage.lifelog import DayProfile
    day = DayProfile(
        date=data.get("date", ""), narrative=data.get("narrative", ""),
        people=data.get("people", []), topics=data.get("topics", []),
        activities=data.get("activities", []), highlights=data.get("highlights", []),
        user_id=data.get("user_id", user), metadata=data.get("metadata", {}),
    )
    return ll.put_day(day)


@lifelog.command("put")
@click.option("--payload", default="", help="JSON episode (date/start/end/activity/participants/topics/media/summary).")
@click.option("--user", default="")
def lifelog_put(payload: str, user: str) -> None:
    """Add one episode. Returns {"id", "duplicate"} as JSON."""
    store, ll = _get_lifelog()
    eid, dup = _put_episode(ll, json.loads(payload) if payload else {}, user)
    click.echo(json.dumps({"id": eid, "duplicate": dup}, ensure_ascii=False))
    store.close()


@lifelog.command("put-day")
@click.option("--payload", default="", help="JSON day profile (date/narrative/people/topics/activities/highlights).")
@click.option("--user", default="")
def lifelog_put_day(payload: str, user: str) -> None:
    """Upsert a day profile. Returns {"id", "updated"} as JSON."""
    store, ll = _get_lifelog()
    did, upd = _put_day(ll, json.loads(payload) if payload else {}, user)
    click.echo(json.dumps({"id": did, "updated": upd}, ensure_ascii=False))
    store.close()


@lifelog.command("put-rollup")
@click.option("--payload", default="", help="Full rollup JSON {date, episodes[], day_profile{}}.")
@click.option("--user", default="")
def lifelog_put_rollup(payload: str, user: str) -> None:
    """Ingest a whole day's rollup (all episodes + day profile) in one call — the
    entry point RadioHand uses. Returns {"date","episodes":[ids],"day":id} as JSON."""
    store, ll = _get_lifelog()
    data = json.loads(payload) if payload else {}
    date = data.get("date", "")
    ep_ids = []
    tz = data.get("tz", "")
    for ep in data.get("episodes", []):
        ep.setdefault("date", date)
        if tz:
            ep.setdefault("tz", tz)
        eid, dup = _put_episode(ll, ep, user)
        ep_ids.append({"id": eid, "duplicate": dup})
    day_id = None
    if data.get("day_profile"):
        dp = dict(data["day_profile"]); dp.setdefault("date", date)
        day_id, _ = _put_day(ll, dp, user)
    click.echo(json.dumps({"date": date, "episodes": ep_ids, "day": day_id}, ensure_ascii=False))
    store.close()


@lifelog.command("search")
@click.argument("query")
@click.option("--date", "-d", default="")
@click.option("--person", "-p", default="")
@click.option("--limit", "-n", default=10)
@click.option("--user", default="")
def lifelog_search(query: str, date: str, person: str, limit: int, user: str) -> None:
    """Search episodes (FTS over activity+summary+topics). Returns a JSON list.
    This is the retrieval bridge — RadioHand injects relevant episodes into chat."""
    store, ll = _get_lifelog()
    click.echo(json.dumps(ll.search_episodes(query, limit=limit, date=date, person=person, user_id=user), ensure_ascii=False))
    store.close()


@lifelog.command("get")
@click.argument("episode_id", type=int)
def lifelog_get(episode_id: int) -> None:
    """Get one episode as JSON."""
    store, ll = _get_lifelog()
    ep = ll.get_episode(episode_id)
    click.echo(json.dumps(ep, ensure_ascii=False) if ep else json.dumps({"error": "not found"}))
    store.close()


@lifelog.command("list")
@click.option("--date", "-d", default="")
@click.option("--limit", "-n", default=50)
@click.option("--user", default="")
def lifelog_list(date: str, limit: int, user: str) -> None:
    """List episodes (optionally for one date) as JSON."""
    store, ll = _get_lifelog()
    click.echo(json.dumps(ll.list_episodes(date=date, limit=limit, user_id=user), ensure_ascii=False))
    store.close()


@lifelog.command("day")
@click.argument("date")
@click.option("--user", default="")
def lifelog_day(date: str, user: str) -> None:
    """Get one day's profile as JSON."""
    store, ll = _get_lifelog()
    day = ll.get_day(date, user_id=user)
    click.echo(json.dumps(day, ensure_ascii=False) if day else json.dumps({"error": "not found"}))
    store.close()


@lifelog.command("stats")
@click.option("--user", default="")
def lifelog_stats(user: str) -> None:
    """Life-log counts (episodes / day_profiles / days_covered) as JSON."""
    store, ll = _get_lifelog()
    click.echo(json.dumps(ll.stats(user_id=user), ensure_ascii=False))
    store.close()


# --- consolidation (蒸馏升格) -------------------------------------------------
# Life log → durable memory. Host-thinks: `prepare` hands out the prompt, the
# caller's LLM answers, `apply` writes the result. `auto` does both when this
# host happens to have an LLM (the bare CLI on R76S does not).

@lifelog.group("consolidate")
def lifelog_consolidate() -> None:
    """蒸馏升格 — distil recent days into L2 facts / habits / KG triples."""


def _consolidate_writers():
    """Habit store + knowledge graph, opened without the full mind."""
    from radiomind.core.config import Config
    from radiomind.storage.hdc import HabitStore
    from radiomind.storage.knowledge_graph import KnowledgeGraph

    cfg = Config.load()
    habits = HabitStore(cfg.home / "data" / "hdc", dim=cfg.get("hdc.dim", 10000))
    habits.open()
    kg = KnowledgeGraph(cfg.db_path.parent / "knowledge.db")
    kg.open()
    return habits, kg


def _consolidate_llm(timeout: int = 0):
    """Any reachable LLM: env keys → config.toml backends → local Ollama.

    Distilling a day of material through a reasoning model runs for minutes, well
    past the 45s a backend defaults to, so the caller's timeout is pushed down.
    """
    from radiomind.core.config import Config
    from radiomind.core.llm import LLMRouter
    from radiomind.core.llm_auto import _from_env, _from_ollama

    def _stretch(obj):
        if obj is None or not timeout:
            return obj
        for backend in [obj, *getattr(obj, "_backends", {}).values()]:
            if hasattr(backend, "timeout"):
                backend.timeout = timeout
        return obj

    env_backend = _from_env()
    if env_backend:
        return _stretch(env_backend)
    router = LLMRouter(Config.load())
    if router.is_available():
        return _stretch(router)
    return _stretch(_from_ollama())


def _prepare_payload(ll, store, days, since, until, force, user, max_episodes, domain):
    from radiomind.refinement import lifelog_consolidate as lc

    ctx = lc.build_context(ll, store=store, days=days, user_id=user, since=since,
                           until=until, force=force, max_episodes=max_episodes, domain=domain)
    payload = {
        "dates": ctx["dates"],
        "n_days": len(ctx["dates"]),
        "n_episodes": len(ctx["episodes"]),
        "n_existing_facts": len(ctx["existing_facts"]),
        "domain": domain,
        "system": lc.SYSTEM,
        "prompt": lc.build_prompt(ctx) if ctx["dates"] else "",
    }
    if not ctx["dates"]:
        payload["note"] = "no un-consolidated day profiles in range (use --force to redo)"
    return payload


@lifelog_consolidate.command("prepare")
@click.option("--days", "-n", default=7, help="How many recent day profiles to distil.")
@click.option("--since", default="", help="Earliest date (YYYY-MM-DD).")
@click.option("--until", default="", help="Latest date (YYYY-MM-DD).")
@click.option("--force", is_flag=True, help="Include days already consolidated.")
@click.option("--max-episodes", default=200, help="Cap on episodes pulled into the prompt.")
@click.option("--domain", default="lifelog", help="Memory domain distilled facts land in.")
@click.option("--user", default="")
def lifelog_consolidate_prepare(days: int, since: str, until: str, force: bool,
                                max_episodes: int, domain: str, user: str) -> None:
    """Build the distillation prompt. Returns {"dates","prompt","system",...} as JSON —
    the caller runs its own LLM on `prompt`, then passes the reply to `apply`."""
    store, ll = _get_lifelog()
    payload = _prepare_payload(ll, store, days, since, until, force, user, max_episodes, domain)
    click.echo(json.dumps(payload, ensure_ascii=False))
    store.close()


@lifelog_consolidate.command("apply")
@click.option("--response", default="", help="The LLM's reply to the prepare prompt (JSON).")
@click.option("--response-file", default="", help="Read the reply from a file instead.")
@click.option("--dates", default="", help="Comma-separated dates from prepare — marks them consolidated.")
@click.option("--domain", default="lifelog")
@click.option("--min-confidence", default=0.5, help="Drop facts below this confidence.")
@click.option("--dry-run", is_flag=True, help="Parse and report, write nothing.")
@click.option("--user", default="")
def lifelog_consolidate_apply(response: str, response_file: str, dates: str, domain: str,
                              min_confidence: float, dry_run: bool, user: str) -> None:
    """Write a distillation result: facts → L2 memories, habits → habit store,
    entities → knowledge graph. Returns a JSON summary."""
    from radiomind.refinement import lifelog_consolidate as lc

    text = Path(response_file).read_text() if response_file else response
    try:
        result = lc.parse_response(text)
    except ValueError as exc:
        click.echo(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)

    store, ll = _get_lifelog()
    habits, kg = (None, None) if dry_run else _consolidate_writers()
    summary = lc.apply_result(
        result, store=store, ll=ll, habits=habits, kg=kg,
        dates=[d.strip() for d in dates.split(",") if d.strip()],
        user_id=user, domain=domain, min_confidence=min_confidence, dry_run=dry_run,
    )
    click.echo(json.dumps(summary, ensure_ascii=False))
    if habits:
        habits.close()
    if kg:
        kg.close()
    store.close()


@lifelog_consolidate.command("auto")
@click.option("--days", "-n", default=7)
@click.option("--since", default="")
@click.option("--until", default="")
@click.option("--force", is_flag=True)
@click.option("--max-episodes", default=200)
@click.option("--domain", default="lifelog")
@click.option("--min-confidence", default=0.5)
@click.option("--model", default="", help="Override the model for this call.")
@click.option("--timeout", default=300, help="Seconds to wait for the LLM (reasoning models are slow).")
@click.option("--dry-run", is_flag=True)
@click.option("--user", default="")
def lifelog_consolidate_auto(days: int, since: str, until: str, force: bool, max_episodes: int,
                             domain: str, min_confidence: float, model: str, timeout: int,
                             dry_run: bool, user: str) -> None:
    """Prepare → call this host's LLM → apply, in one shot. Fails cleanly with
    {"error": "no LLM"} on a pure-memory host; use prepare/apply there."""
    from radiomind.refinement import lifelog_consolidate as lc

    store, ll = _get_lifelog()
    payload = _prepare_payload(ll, store, days, since, until, force, user, max_episodes, domain)
    if not payload["dates"]:
        click.echo(json.dumps(payload, ensure_ascii=False))
        store.close()
        return

    llm = _consolidate_llm(timeout=timeout)
    if llm is None:
        click.echo(json.dumps(
            {"error": "no LLM available on this host — use `consolidate prepare` + `apply`",
             "dates": payload["dates"]}, ensure_ascii=False))
        store.close()
        raise SystemExit(1)

    resp = llm.generate(payload["prompt"], system=lc.SYSTEM, model=model)
    try:
        result = lc.parse_response(resp.text)
    except ValueError as exc:
        click.echo(json.dumps({"error": f"LLM reply not parseable: {exc}", "raw": resp.text[:500]},
                              ensure_ascii=False))
        store.close()
        raise SystemExit(1)

    habits, kg = (None, None) if dry_run else _consolidate_writers()
    summary = lc.apply_result(
        result, store=store, ll=ll, habits=habits, kg=kg, dates=payload["dates"],
        user_id=user, domain=domain, min_confidence=min_confidence, dry_run=dry_run,
    )
    summary["model"] = resp.model
    summary["tokens"] = resp.tokens_prompt + resp.tokens_completion
    click.echo(json.dumps(summary, ensure_ascii=False))
    if habits:
        habits.close()
    if kg:
        kg.close()
    store.close()


# --- Speakers (声纹身份) ------------------------------------------------------
# The audio tool is stateless: it extracts turns + embeddings and forgets them.
# Identity and accumulation live here. RadioHand calls these via subprocess.

@cli.group("speakers")
def speakers() -> None:
    """声纹身份 — resolve voices to stable people and accumulate who recurs."""


def _load_payload(payload: str, payload_file: str) -> dict:
    """Turn payloads carry hundreds of base64 vectors — a file avoids ARG_MAX."""
    if payload_file:
        return json.loads(Path(payload_file).read_text())
    return json.loads(payload) if payload else {}


def _parse_turns(data: dict, user: str) -> list:
    from radiomind.storage.speakers import SpeakerTurn, decode_embedding

    tz = data.get("tz", "")
    model_id = data.get("model_id", "")
    out = []
    for t in data.get("turns", []):
        emb = t.get("embedding")
        out.append(SpeakerTurn(
            started_at=float(t.get("started_at", 0)), ended_at=float(t.get("ended_at", 0)),
            date=t.get("date", ""), tz=t.get("tz", tz),
            embedding=decode_embedding(emb) if emb is not None else None,
            model_id=t.get("model_id", model_id), speech_s=float(t.get("speech_s", 0)),
            quality=float(t.get("quality", 0)),
            region_type=t.get("region_type", "conversation"),
            source_file=t.get("source_file", data.get("source_file", "")),
            user_id=t.get("user_id", user), metadata=t.get("metadata", {}),
        ))
    return out


def _emit(obj, out_file: str) -> None:
    """Hand truncates a subprocess's stdout at 64KB, so bulk detail goes to a file
    and stdout keeps the summary."""
    text = json.dumps(obj, ensure_ascii=False)
    if out_file:
        Path(out_file).write_text(text)
        click.echo(json.dumps({"out_file": out_file, "bytes": len(text)}, ensure_ascii=False))
    else:
        click.echo(text)


@speakers.command("put-turns")
@click.option("--payload", default="", help="JSON {model_id, tz, turns:[{started_at, speech_s, embedding(base64), ...}]}.")
@click.option("--payload-file", default="", help="Read that JSON from a file (preferred for a full day).")
@click.option("--out-file", default="", help="Write the full per-turn detail here instead of stdout.")
@click.option("--dry-run", is_flag=True, help="Resolve and report, store nothing.")
@click.option("--user", default="")
def speakers_put_turns(payload: str, payload_file: str, out_file: str, dry_run: bool, user: str) -> None:
    """Store turns and resolve them to speakers in one call. Returns a summary."""
    from radiomind.storage.speakers import ModelMismatch

    store, sp = _get_speakers()
    data = _load_payload(payload, payload_file)
    try:
        summary = sp.put_turns(_parse_turns(data, user), user_id=user,
                               model_id=data.get("model_id", ""), dry_run=dry_run)
    except ModelMismatch as exc:
        click.echo(json.dumps({"error": "model_mismatch", "detail": str(exc)}, ensure_ascii=False))
        store.close()
        raise SystemExit(1)
    _emit(summary, out_file)
    store.close()


@speakers.command("resolve")
@click.option("--payload", default="")
@click.option("--payload-file", default="")
@click.option("--out-file", default="")
@click.option("--user", default="")
def speakers_resolve(payload: str, payload_file: str, out_file: str, user: str) -> None:
    """Preview which speaker each embedding would bind to, without storing anything."""
    store, sp = _get_speakers()
    data = _load_payload(payload, payload_file)
    results = []
    for t in _parse_turns(data, user):
        if t.embedding is None:
            results.append({"started_at": t.started_at, "error": "no embedding"})
            continue
        match, score, binding = sp.match(t.embedding, user_id=user, speech_s=t.speech_s)
        results.append({"started_at": t.started_at, "speech_s": t.speech_s,
                        "label": match["label"] if match else None,
                        "score": round(score, 4), "binding": binding})
    _emit({"resolved": results, "n": len(results)}, out_file)
    store.close()


@speakers.command("list")
@click.option("--status", default="", help="active | pending | archived")
@click.option("--user", default="")
def speakers_list(status: str, user: str) -> None:
    """List speakers as JSON, loudest first."""
    store, sp = _get_speakers()
    click.echo(json.dumps(sp.list_speakers(user_id=user, status=status), ensure_ascii=False))
    store.close()


@speakers.command("get")
@click.argument("label")
@click.option("--user", default="")
def speakers_get(label: str, user: str) -> None:
    """Get one speaker as JSON (follows merge tombstones)."""
    store, sp = _get_speakers()
    row = sp.get(sp.resolve_label(label, user), user)
    click.echo(json.dumps(row, ensure_ascii=False) if row else json.dumps({"error": "not found"}))
    store.close()


@speakers.command("name")
@click.argument("label")
@click.argument("display_name")
@click.option("--confidence", default=1.0, help="<1 means this is a proposal, not a confirmation.")
@click.option("--evidence", default="", help="What the name was inferred from.")
@click.option("--no-kg", is_flag=True, help="Skip the knowledge-graph alias.")
@click.option("--user", default="")
def speakers_name(label: str, display_name: str, confidence: float, evidence: str,
                  no_kg: bool, user: str) -> None:
    """Bind a person to a voice. A confirmed name also becomes a KG alias, which
    rewrites existing triples — so facts recorded under `spk_003` follow the name."""
    store, sp = _get_speakers()
    result = sp.name(sp.resolve_label(label, user), display_name, user_id=user,
                     confidence=confidence, evidence=evidence)
    if not result.get("error") and confidence >= 1.0 and not no_kg:
        kg = _get_library_kg()
        kg.add_alias(label, display_name)
        kg.close()
        result["kg_alias"] = True
    click.echo(json.dumps(result, ensure_ascii=False))
    store.close()


@speakers.command("promote")
@click.option("--user", default="")
def speakers_promote(user: str) -> None:
    """Promote pending speakers that recur across days; expire the ones that never grew."""
    store, sp = _get_speakers()
    click.echo(json.dumps(sp.promote(user_id=user), ensure_ascii=False))
    store.close()


@speakers.command("merge-candidates")
@click.option("--user", default="")
def speakers_merge_candidates(user: str) -> None:
    """Speaker pairs similar enough to propose merging (never auto-applied)."""
    store, sp = _get_speakers()
    click.echo(json.dumps(sp.merge_candidates(user_id=user), ensure_ascii=False))
    store.close()


@speakers.command("merge")
@click.argument("from_label")
@click.argument("into_label")
@click.option("--reason", default="")
@click.option("--dry-run", is_flag=True)
@click.option("--user", default="")
def speakers_merge(from_label: str, into_label: str, reason: str, dry_run: bool, user: str) -> None:
    """Merge one speaker into another. Reversible — turn embeddings are kept."""
    store, sp = _get_speakers()
    click.echo(json.dumps(sp.merge(from_label, into_label, user_id=user, reason=reason,
                                   dry_run=dry_run), ensure_ascii=False))
    store.close()


@speakers.command("split")
@click.argument("label")
@click.option("--dry-run", is_flag=True)
@click.option("--user", default="")
def speakers_split(label: str, dry_run: bool, user: str) -> None:
    """Split one speaker into two by re-clustering its turns."""
    store, sp = _get_speakers()
    click.echo(json.dumps(sp.split(label, user_id=user, dry_run=dry_run), ensure_ascii=False))
    store.close()


@speakers.command("rebuild")
@click.argument("label")
@click.option("--user", default="")
def speakers_rebuild(label: str, user: str) -> None:
    """Recompute a speaker's centroid and stats from its turns."""
    store, sp = _get_speakers()
    row = sp.get(sp.resolve_label(label, user), user)
    if not row:
        click.echo(json.dumps({"error": "not found"}))
    else:
        click.echo(json.dumps(sp.rebuild(row["id"]), ensure_ascii=False))
    store.close()


@speakers.command("forget")
@click.argument("label")
@click.option("--dry-run", is_flag=True)
@click.option("--user", default="")
def speakers_forget(label: str, dry_run: bool, user: str) -> None:
    """Erase a person and every embedding of them. Callers must also anonymize
    `@<label>` references in already-generated text."""
    store, sp = _get_speakers()
    click.echo(json.dumps(sp.forget(label, user_id=user, dry_run=dry_run), ensure_ascii=False))
    store.close()


@speakers.command("stats")
@click.option("--user", default="")
def speakers_stats(user: str) -> None:
    """Gallery counts as JSON."""
    store, sp = _get_speakers()
    click.echo(json.dumps(sp.stats(user_id=user), ensure_ascii=False))
    store.close()


@speakers.command("manual")
@click.option("--json", "as_json", is_flag=True, default=True, help="(always JSON)")
@click.option("--user", default="")
def speakers_manual(as_json: bool, user: str) -> None:
    """Self-description for an agent: what this namespace is for, its coverage,
    current thresholds, health, and what maintenance it currently wants."""
    store, sp = _get_speakers()
    click.echo(json.dumps(sp.manual(user_id=user), ensure_ascii=False))
    store.close()
