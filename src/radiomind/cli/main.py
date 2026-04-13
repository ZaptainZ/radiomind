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

    with open(file) as f:
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

    if not mind._llm.is_available():
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

    if not mind._llm.is_available():
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
    click.echo(f"Habits (L3):  {s['habits']}")
    click.echo(f"Domains:      {s['domain_count']}")
    if s.get("domains"):
        for d in s["domains"]:
            click.echo(f"  - {d['name']} ({d['memory_count']} memories)")
    click.echo()
    click.echo(f"LLM: {'available' if s['llm_available'] else 'unavailable'} ({', '.join(s['llm_backends']) or 'none'})")
    click.echo(f"LLM calls: {s['llm_usage']['total_calls']} ({s['llm_usage']['total_tokens']} tokens)")
    click.echo()

    digest = mind.get_context_digest()
    if digest:
        click.echo("Context Digest:")
        click.echo(f"  {digest}")

    mind.shutdown()


@cli.command()
@click.option("--model", default=None, help="MLX model to fine-tune (e.g. mlx-community/Qwen2.5-0.5B-Instruct-4bit)")
@click.option("--iters", default=None, type=int, help="Training iterations (default: 500)")
@click.option("--data-only", is_flag=True, help="Only generate training data, don't train.")
def train(model: str | None, iters: int | None, data_only: bool) -> None:
    """Run LoRA fine-tuning on accumulated knowledge (requires MLX)."""
    mind = _get_mind()

    if data_only:
        count, path = mind.generate_training_data()
        click.echo(f"Generated {count} training examples → {path}")
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
    count, data_path = mind.generate_training_data()
    click.echo(f"  {count} examples generated")

    if count < 3:
        click.echo("Too few examples. Ingest more conversations first.")
        mind.shutdown()
        return

    click.echo("Starting LoRA fine-tuning (this may take a few minutes)...")
    result = mind.train(**kwargs)

    if result.success:
        click.echo(f"Training complete in {result.duration_s:.1f}s")
        click.echo(f"  Model: {result.model}")
        click.echo(f"  Adapter: {result.adapter_path}")
        click.echo(f"\nTo load in Ollama:")
        click.echo(f"  radiomind deploy")
    else:
        click.echo(f"Training failed: {result.error}")

    mind.shutdown()


@cli.command()
def deploy() -> None:
    """Deploy trained LoRA adapter to Ollama."""
    from radiomind.training.lora import export_to_ollama
    from radiomind.core.config import Config

    cfg = Config.load()
    adapter_path = cfg.home / "models" / "lora" / "adapters"

    if not adapter_path.exists():
        click.echo("No trained adapter found. Run 'radiomind train' first.")
        return

    click.echo("Deploying adapter to Ollama...")
    success, msg = export_to_ollama(adapter_path)
    click.echo(msg)


@cli.command("learn")
@click.argument("text")
def learn_text(text: str) -> None:
    """Add external knowledge (text) to L2 facts."""
    mind = _get_mind()
    entries = mind.learn(text)
    click.echo(f"Learned {len(entries)} entry(s)")
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
def rh_consolidate() -> None:
    """Run RadioHeader-compatible consolidation (dream + digest)."""
    from radiomind.adapters.radioheader import RadioHeaderAdapter

    mind = _get_mind()

    if not mind._llm.is_available():
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
