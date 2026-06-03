"""devtools.py — unified repo-dev diagnostic CLI (PX-1b).

Thin dispatcher over the existing bench gates. **NO logic migration, NO
runtime change.** Each subcommand forwards to the existing script's `main()`
by constructing the argv that script already understands — devtools owns the
verb surface and the safety rails, not the behaviour.

Usage:
  python -m bench.end_to_end.devtools regression-pack
  python -m bench.end_to_end.devtools target-pack --report path/to/artifact.json
  python -m bench.end_to_end.devtools diagnose --qid c18a7dc8 --e2e-result run.json

Scope (PX-1b):
  - regression-pack : wraps regression_pack.main() — the pure, deterministic
                      gate (no ingest / LLM / benchmark).
  - target-pack     : wraps target_pack.main() in --report mode ONLY (parse an
                      existing artifact). `--report` is REQUIRED here, so devtools
                      can NEVER trigger target_pack's heavy real-e2e run path.
                      For a real run, call bench/end_to_end/target_pack.py directly.
  - diagnose        : forwards argv to diagnose_qid.main() (heavy: real
                      ingest + LLM). devtools only constructs the argv; it does
                      not change diagnose logic.
  - report          : (PX-1c) renders a standard report (diagnosis.json +
                      summary.md) from an EXISTING diagnose-<qid>.json. Pure
                      projection — no ingest / LLM / re-run.

Design: `plan(argv)` is a PURE function (argparse → Dispatch); it imports
nothing heavy and runs no gate, so tests can pin the dispatch/argv-construction
without any risk of an accidental benchmark run. `run(argv)` is the only place
that imports a target module and calls its `main()`.

PX-1c will add the standard diagnosis report (summary.md / diagnosis.json /
recommended_next_action). It is deliberately out of PX-1b scope.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Dispatch:
    """Pure description of what `run()` will do. No side effects to build one.

    command:  the devtools verb (regression-pack / target-pack / diagnose)
    module:   the existing bench module to invoke (regression_pack / target_pack
              / diagnose_qid)
    argv:     the argv to hand that module's main() (without argv[0])
    """
    command: str
    module: str
    argv: list[str] = field(default_factory=list)


_PROG = "python -m bench.end_to_end.devtools"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=_PROG,
        description="RadioMind repo-dev diagnostic CLI (thin wrapper over the "
                    "bench gates; no runtime change).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ---- regression-pack: pure deterministic gate ----
    rp = sub.add_parser(
        "regression-pack",
        help="Run the deterministic regression pack (fast, no ingest/LLM).",
    )
    rp.add_argument(
        "--integration", action="store_true",
        help="Forwarded to regression_pack (reserved; runs the fast pack only).",
    )

    # ---- target-pack: artifact parse ONLY (--report required) ----
    tp = sub.add_parser(
        "target-pack",
        help="Parse/summarize an existing target-pack artifact json. Does NOT "
             "run a real e2e — --report is required.",
    )
    tp.add_argument(
        "--report", type=Path, required=True,
        help="Existing runner result json to summarize (no run is performed).",
    )

    # ---- diagnose: forward to the heavy single-qid microscope ----
    dg = sub.add_parser(
        "diagnose",
        help="Diagnose one qid (heavy: real ingest + LLM). Wraps diagnose_qid.",
    )
    dg.add_argument("--qid", required=True)
    dg.add_argument("--e2e-result", type=Path, default=None,
                    help="Overlay a saved runner result json's final answer.")
    dg.add_argument("--sandbox", type=Path, default=None)
    dg.add_argument("--keep-sandbox", action="store_true")
    dg.add_argument("--out", type=Path, default=None)

    # ---- report: pure projection of an existing diagnose rec (PX-1c) ----
    rep = sub.add_parser(
        "report",
        help="Render diagnosis.json + summary.md from an existing "
             "diagnose-<qid>.json. Pure; no ingest/LLM/re-run.",
    )
    rep.add_argument("--diagnose-json", type=Path, required=True,
                     help="An existing diagnose_qid.py output json.")
    rep.add_argument("--out", type=Path, required=True,
                     help="Output directory for the report files.")
    return p


def plan(argv: list[str]) -> Dispatch:
    """PURE: parse devtools argv → a Dispatch. No imports of target modules,
    no gate execution, no benchmark. argparse errors raise SystemExit (which is
    exactly the 'no accidental run' guarantee for target-pack without --report).
    """
    ns = _build_parser().parse_args(argv)

    if ns.command == "regression-pack":
        fwd: list[str] = []
        if ns.integration:
            fwd.append("--integration")
        return Dispatch("regression-pack", "regression_pack", fwd)

    if ns.command == "target-pack":
        # --report is required by the parser → real-run path is unreachable here.
        return Dispatch("target-pack", "target_pack",
                        ["--report", str(ns.report)])

    if ns.command == "diagnose":
        fwd = ["--qid", ns.qid]
        if ns.e2e_result is not None:
            fwd += ["--e2e-result", str(ns.e2e_result)]
        if ns.sandbox is not None:
            fwd += ["--sandbox", str(ns.sandbox)]
        if ns.keep_sandbox:
            fwd.append("--keep-sandbox")
        if ns.out is not None:
            fwd += ["--out", str(ns.out)]
        return Dispatch("diagnose", "diagnose_qid", fwd)

    if ns.command == "report":
        return Dispatch("report", "diagnosis_report",
                        ["--diagnose-json", str(ns.diagnose_json),
                         "--out", str(ns.out)])

    # argparse(required=True) makes this unreachable, but be explicit.
    raise SystemExit(2)


def run(argv: list[str] | None = None) -> int:
    """Execute the planned dispatch: import the target bench module and call its
    main() with the constructed argv. This is the ONLY place a target module is
    imported or run."""
    d = plan(sys.argv[1:] if argv is None else argv)

    # Match the bench scripts' flat-import convention (they sit side-by-side and
    # import each other by bare name via this dir on sys.path).
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)

    import importlib
    mod = importlib.import_module(d.module)

    old_argv = sys.argv
    try:
        sys.argv = [f"{d.module}.py", *d.argv]
        return int(mod.main() or 0)
    finally:
        sys.argv = old_argv


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
