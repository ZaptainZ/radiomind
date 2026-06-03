"""diagnosis_report.py — standard diagnosis report (PX-1c).

Projects an EXISTING diagnose-<qid>.json (produced by diagnose_qid.py) into a
stable, human-readable report. **Pure file IO — NO ingest, NO LLM, NO benchmark,
NO re-run of diagnose.** It only reads a saved rec and renders two files:

  - diagnosis.json : stable machine schema (qid, layer, reason, fix_family,
                     do_not, next_action, source, meaning, layer_recognized,
                     context)
  - summary.md     : short human-readable report

`recommended_next_action` is a PURE LOOKUP keyed on `path_summary.diagnosis.layer`
— it adds NO new reasoning. The table mirrors DEV_WORKFLOW §4 / the PX-1a audit
§5.4 (the only "knowledge" here is that already-written human guidance, moved
into a constant).

Usage (via devtools):
  python -m bench.end_to_end.devtools report --diagnose-json <json> --out <dir>

Building blocks (all pure, unit-tested in tests/test_diagnosis_report.py):
  load_diagnose_json(path)            -> dict
  build_diagnosis_report(data, src)   -> dict   (the diagnosis.json content)
  render_summary_md(report)           -> str    (the summary.md content)
  write_report(report, out_dir)       -> dict   (written file paths)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# layer -> human guidance. Pure lookup; mirrors DEV_WORKFLOW §4 / PX-1a §5.4.
# Keys are the DX-2c stabilized diagnosis.layer enum.
LAYER_GUIDANCE: dict[str, dict[str, str]] = {
    "pass": {
        "meaning": "e2e answer judged correct",
        "fix_family": "(none)",
        "do_not": "—",
        "next_action": "nothing to do — this qid passes",
    },
    "answer_or_judge_path": {
        "meaning": "proof was ready / no infra error but the final answer is "
                   "wrong or abstained, OR an [answer error] / judge failure",
        "fix_family": "infra retry, or answer-LLM trust/prompt",
        "do_not": "do not treat as a logic gap or edit a helper",
        "next_action": "re-run for infra flakes; if stable, inspect the "
                       "answer-LLM hint-trust / prompt path",
    },
    "concrete_wrong_bypassed_committer": {
        "meaning": "a committer proof was ready, but the answer-LLM returned a "
                   "concrete wrong value (not an abstain), so commit_on_abstain "
                   "never fired",
        "fix_family": "upstream hint-trust or a suppressor-shaped guard",
        "do_not": "do not edit the existing committer (it only rescues abstains)",
        "next_action": "audit hint trust upstream, or consider a "
                       "suppressor-shaped guard; verify with a fresh run",
    },
    "proof_input_turn_missing": {
        "meaning": "a required proof input/anchor was not found in the retrieved "
                   "turns (the evidence turn was likely out-ranked / not retrieved)",
        "fix_family": "retrieval / turn-ranking audit",
        "do_not": "do not edit the parser/regex (extraction is not the bug)",
        "next_action": "audit retrieval granularity / ranking so the evidence "
                       "turn reaches the window",
    },
    "helper_refusal": {
        "meaning": "a helper gate refused (trigger miss, etc.)",
        "fix_family": "the named helper's gate",
        "do_not": "do not change global retrieval",
        "next_action": "read the named helper's refusal_reason in helper_proofs "
                       "and adjust that gate",
    },
    "retrieval_gap": {
        "meaning": "no gold sessions retrieved in the top window",
        "fix_family": "retrieval breadth",
        "do_not": "do not change a closure",
        "next_action": "audit retrieval breadth/recall — gold sessions are not "
                       "reaching the window at all",
    },
    "closure_ready": {
        "meaning": "deterministic committer/suppressor proof is ready "
                   "(no e2e overlay applied)",
        "fix_family": "overlay an e2e result to see the live outcome",
        "do_not": "do not assume ready == pass",
        "next_action": "re-run diagnose with --e2e-result to get the live "
                       "verdict before acting",
    },
    "proof_ready": {
        "meaning": "helper(s) produced a proof; the line may be hint-only "
                   "(no closure rescue)",
        "fix_family": "overlay an e2e result to see the live outcome",
        "do_not": "do not assume ready == pass",
        "next_action": "re-run diagnose with --e2e-result; remember hint-only "
                       "lines have no commit rescue",
    },
    "skill_route_gap": {
        "meaning": "a structured skill is present but no closure/helper resolved "
                   "it; the diagnostic needs more fields",
        "fix_family": "improve the diagnostic, don't change business code",
        "do_not": "do not change business/runtime code on this signal alone",
        "next_action": "extend diagnose_qid to probe the missing route, then "
                       "re-diagnose",
    },
    "unknown": {
        "meaning": "insufficient deterministic evidence to localize",
        "fix_family": "improve the diagnostic, don't change business code",
        "do_not": "do not change business/runtime code on this signal alone",
        "next_action": "add an --e2e-result overlay, or read closure_view + "
                       "helper_proofs in the diagnose rec directly",
    },
}

_NO_PATH_SUMMARY = (
    "(no path_summary in this diagnose rec — it predates DX-2a or is "
    "incomplete; re-run diagnose_qid.py to get a localized layer)"
)


def load_diagnose_json(path: str | Path) -> dict:
    """Read a saved diagnose-<qid>.json. Pure IO, no validation beyond JSON."""
    return json.loads(Path(path).read_text())


def build_diagnosis_report(data: dict, source: str = "") -> dict:
    """Project a diagnose rec into the stable diagnosis.json schema. Pure.

    Handles both current recs (with path_summary) and legacy recs (without):
    a missing path_summary degrades to layer='unknown' with an explicit note,
    never crashes.
    """
    ps = data.get("path_summary") or {}
    has_ps = bool(ps)
    qid = data.get("qid") or ps.get("qid") or "unknown"
    diag = ps.get("diagnosis") or {}
    layer = diag.get("layer") or "unknown"
    reason = diag.get("reason") or ("" if has_ps else _NO_PATH_SUMMARY)

    recognized = layer in LAYER_GUIDANCE
    g = LAYER_GUIDANCE.get(layer, LAYER_GUIDANCE["unknown"])

    # compact, stable context for the human summary (NOT the full diagnose rec)
    retrieval = ps.get("retrieval") or None
    fa = ps.get("final_answer") or None
    context: dict = {"retrieval": retrieval}
    if fa is not None:
        flags = []
        if fa.get("answer_error"):
            flags.append("answer-error")
        if fa.get("judge_failed"):
            flags.append("judge-failed")
        if fa.get("pure_abstain"):
            flags.append("pure-abstain")
        context["verdict"] = "correct" if fa.get("correct") else "WRONG"
        context["flags"] = flags
    else:
        context["verdict"] = None
        context["flags"] = []

    return {
        "qid": qid,
        "layer": layer,
        "reason": reason,
        "meaning": g["meaning"],
        "fix_family": g["fix_family"],
        "do_not": g["do_not"],
        "next_action": g["next_action"],
        "layer_recognized": recognized,
        "source": source,
        "context": context,
    }


def render_summary_md(report: dict) -> str:
    """Render the short human-readable summary.md from a report dict. Pure."""
    qid = report.get("qid", "unknown")
    layer = report.get("layer", "unknown")
    ctx = report.get("context") or {}
    verdict = ctx.get("verdict")
    title_tail = verdict if verdict else layer

    lines = [
        f"# diagnose {qid} — {title_tail}",
        "",
        f"**Layer:** `{layer}`",
        f"**Meaning:** {report.get('meaning', '')}",
        f"**Fix family:** {report.get('fix_family', '')}",
        f"**Do not:** {report.get('do_not', '')}",
        f"**Next action:** {report.get('next_action', '')}",
        "",
        f"**Reason:** {report.get('reason', '')}",
    ]
    if not report.get("layer_recognized", True):
        lines += [
            "",
            f"> ⚠ Unrecognized layer `{layer}` — fell back to generic "
            "guidance. Check DEV_WORKFLOW §4 for the current enum.",
        ]

    retr = ctx.get("retrieval")
    if retr:
        lines += [
            "",
            f"- retrieval: gold {retr.get('gold_hits_top_200')}/200, "
            f"{retr.get('gold_hits_top_30')}/30",
        ]
    if verdict is not None:
        flags = ctx.get("flags") or []
        tail = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"- e2e: {verdict}{tail}")

    src = report.get("source")
    if src:
        lines += ["", f"_source: {src}_"]
    return "\n".join(lines) + "\n"


def write_report(report: dict, out_dir: str | Path) -> dict:
    """Write diagnosis.json + summary.md into out_dir. Returns written paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dj = out / "diagnosis.json"
    sm = out / "summary.md"
    dj.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    sm.write_text(render_summary_md(report))
    return {"diagnosis_json": dj, "summary_md": sm}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render a standard diagnosis report from an existing "
                    "diagnose-<qid>.json. Pure projection; no re-run.",
    )
    ap.add_argument("--diagnose-json", type=Path, required=True,
                    help="An existing diagnose_qid.py output json.")
    ap.add_argument("--out", type=Path, required=True,
                    help="Output directory for diagnosis.json + summary.md.")
    args = ap.parse_args()

    data = load_diagnose_json(args.diagnose_json)
    report = build_diagnosis_report(data, source=str(args.diagnose_json))
    paths = write_report(report, args.out)
    print(f"diagnosis: {report['qid']} → layer={report['layer']} "
          f"({'recognized' if report['layer_recognized'] else 'UNRECOGNIZED'})")
    print(f"  next action: {report['next_action']}")
    print(f"  wrote: {paths['diagnosis_json']}")
    print(f"  wrote: {paths['summary_md']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
