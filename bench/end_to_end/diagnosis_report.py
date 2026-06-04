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

The summary.md (PX-2b) is self-contained: Question / Gold / Answer / Verdict /
Diagnosis (layer + meaning + fix_family + do_not + next_action) / Next command.

Building blocks (all pure, unit-tested in tests/test_diagnosis_report.py):
  load_diagnose_json(path)                          -> dict
  lookup_manifest_line(qid)                         -> str | None
  build_diagnosis_report(data, src, manifest, art)  -> dict   (diagnosis.json)
  render_summary_md(report)                         -> str    (summary.md)
  write_report(report, out_dir)                     -> dict   (written paths)
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
        "next_action": "in the diagnose json read final_answer.answer (the "
                       "concrete wrong value the LLM returned) + "
                       "closure_view.committers.<name> (was a proof ready?) to "
                       "confirm the committer was bypassed by a concrete answer; "
                       "then audit upstream hint-trust or add a suppressor-shaped "
                       "guard — never the committer. Verify with a fresh run.",
    },
    "proof_input_turn_missing": {
        "meaning": "a required proof input/anchor was not found in the retrieved "
                   "turns (the evidence turn was likely out-ranked / not retrieved)",
        "fix_family": "retrieval / turn-ranking audit",
        "do_not": "do not edit the parser/regex (extraction is not the bug)",
        "next_action": "in the diagnose json read helper_proofs.<helper>."
                       "refusal_reason (which anchor was missing) + "
                       "retrieve_top_30_preview (where the gold turn ranked) to "
                       "confirm the proof turn never reached the window; then "
                       "audit retrieval granularity / ranking — not the parser.",
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


def lookup_manifest_line(qid: str) -> str | None:
    """Best-effort: map a qid to its target_pack MANIFEST line (e.g.
    'age-interval-committer'). Returns None if target_pack/MANIFEST is
    unavailable or the qid is not in it. Never raises."""
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import target_pack  # sits next to this file
        meta = target_pack.MANIFEST.get(qid)
        return meta.get("line") if isinstance(meta, dict) else None
    except Exception:
        return None


def _trunc(s, n: int) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def build_diagnosis_report(data: dict, source: str = "",
                           manifest_line: str | None = None,
                           e2e_artifact: str | None = None) -> dict:
    """Project a diagnose rec into the stable diagnosis.json schema. Pure.

    Handles both current recs (with path_summary) and legacy recs (without):
    a missing path_summary degrades to layer='unknown' with an explicit note,
    never crashes. Missing question/gold/final_answer fields degrade to None
    (omitted in the summary), never crash.

    manifest_line: the target_pack MANIFEST line for this qid; if None it is
    looked up best-effort. e2e_artifact: the e2e result path to embed in the
    suggested diagnose command (a placeholder is used when None).
    """
    ps = data.get("path_summary") or {}
    has_ps = bool(ps)
    qid = data.get("qid") or ps.get("qid") or "unknown"
    diag = ps.get("diagnosis") or {}
    layer = diag.get("layer") or "unknown"
    reason = diag.get("reason") or ("" if has_ps else _NO_PATH_SUMMARY)

    recognized = layer in LAYER_GUIDANCE
    g = LAYER_GUIDANCE.get(layer, LAYER_GUIDANCE["unknown"])

    if manifest_line is None:
        manifest_line = lookup_manifest_line(qid)

    # compact, stable context for the human summary (NOT the full diagnose rec)
    retrieval = ps.get("retrieval") or None
    fa = ps.get("final_answer") or None

    # PX-2b: surface what the qid asked, what gold was, what the model answered,
    # the verdict, and the exact next command — so the summary is self-contained.
    art = e2e_artifact or "<e2e-result.json>"
    suggested_command = (
        f"python -m bench.end_to_end.devtools diagnose --qid {qid} "
        f"--e2e-result {art}"
    )

    context: dict = {
        "question": _trunc(data.get("question"), 300) or None,
        "gold": _trunc(data.get("gold"), 200) or None,
        "qtype": data.get("qtype"),
        "manifest_line": manifest_line,
        "source_artifact": source or None,
        "suggested_command": suggested_command,
        "retrieval": retrieval,
        # answer/verdict fields below default to None when no e2e overlay
        "answer_snippet": None,
        "correct": None,
        "judge_failed": None,
        "answer_pure_abstain": None,
        "verdict": None,
        "flags": [],
    }
    if fa is not None:
        flags = []
        if fa.get("answer_error"):
            flags.append("answer-error")
        if fa.get("judge_failed"):
            flags.append("judge-failed")
        if fa.get("pure_abstain"):
            flags.append("pure-abstain")
        context["answer_snippet"] = _trunc(fa.get("answer"), 200) or None
        context["correct"] = bool(fa.get("correct"))
        context["judge_failed"] = bool(fa.get("judge_failed"))
        context["answer_pure_abstain"] = bool(fa.get("pure_abstain"))
        context["verdict"] = "correct" if fa.get("correct") else "WRONG"
        context["flags"] = flags

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
    """Render the self-contained human summary.md from a report dict. Pure.

    The summary answers, top to bottom: what the qid asked (Question), what was
    expected (Gold), what the model produced (Answer + Verdict), where it failed
    (Diagnosis), and what to run next (Next command)."""
    qid = report.get("qid", "unknown")
    layer = report.get("layer", "unknown")
    ctx = report.get("context") or {}
    verdict = ctx.get("verdict")
    ml = ctx.get("manifest_line")
    title_tail = verdict if verdict else layer
    title = f"# diagnose {qid} — {title_tail}"
    if ml:
        title += f" ({ml})"

    lines = [title, ""]

    # ---- what the qid is ----
    if ctx.get("question"):
        lines.append(f"**Question:** {ctx['question']}")
    if ctx.get("qtype"):
        lines.append(f"**Type:** {ctx['qtype']}")
    if ctx.get("gold") is not None:
        lines.append(f"**Gold:** {ctx['gold']}")
    if ctx.get("answer_snippet") is not None:
        lines.append(f"**Answer:** {ctx['answer_snippet']}")

    # ---- verdict ----
    if verdict is not None:
        flags = ctx.get("flags") or []
        tail = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"**Verdict:** {verdict}{tail}")
    else:
        lines.append("**Verdict:** n/a (no e2e overlay — re-run diagnose with "
                     "--e2e-result for the live outcome)")

    # ---- diagnosis ----
    lines += [
        "",
        "## Diagnosis",
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

    # ---- next command ----
    cmd = ctx.get("suggested_command")
    if cmd:
        lines += ["", "## Next command", "```bash", cmd, "```"]

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


# ======================= PX-2c: batch triage index =======================
#
# A target-pack artifact carries per_query verdicts but NO path_summary /
# diagnosis.layer (that only exists in a diagnose-<qid>.json). So the batch
# index gives a PRELIMINARY, verdict-level classification — NOT an authoritative
# layer. It fills the real `layer` column only when an existing diagnose json is
# found on disk. It never runs diagnose / ingest / a benchmark.

# preliminary label -> what it means (loosely maps to a layer family, but is
# explicitly NOT the diagnosis.layer).
PRELIM_MEANING: dict[str, str] = {
    "pass": "judged correct",
    "judge-infra": "judge infra error — verdict unreliable, re-run",
    "answer-error": "answer-LLM returned an error string (infra/transient) — "
                    "re-run; not a logic result",
    "trust-gap-candidate": "a hint fired but the answer abstained — likely an "
                           "answer-LLM trust gap (run diagnose to confirm)",
    "abstain-no-hint": "abstained with no hint fired — likely a retrieval / "
                       "helper-refusal gap (run diagnose to confirm)",
    "concrete-wrong-candidate": "a concrete wrong answer (not an abstain) — "
                                "committer-bypass or wrong-value path (run "
                                "diagnose to confirm)",
    "missing": "required qid not present in the artifact",
}


def classify_preliminary(present: bool, correct: bool, judge_failed: bool,
                         helper_hints: dict | None, answer=None) -> str:
    """Pure verdict-level classification from a per_query record. Returns a
    PRELIM_MEANING key. This is NOT a diagnosis.layer — it is a triage hint."""
    if not present:
        return "missing"
    if correct:
        return "pass"
    if judge_failed:
        return "judge-infra"
    if answer is not None and str(answer).startswith("[answer error"):
        return "answer-error"
    hh = helper_hints or {}
    abstain = bool(hh.get("answer_pure_abstain"))
    fired = [k for k, v in hh.items() if v and k != "answer_pure_abstain"]
    if abstain and fired:
        return "trust-gap-candidate"
    if abstain:
        return "abstain-no-hint"
    return "concrete-wrong-candidate"


def _find_diagnose_json(diagnose_dir, qid: str):
    """Return Path to an existing diagnose-<qid>.json under diagnose_dir, or
    None. Read-only lookup; never runs diagnose."""
    if not diagnose_dir:
        return None
    p = Path(diagnose_dir) / f"diagnose-{qid}.json"
    return p if p.exists() else None


def build_triage_index(artifact_data: dict, manifest: dict,
                       diagnose_dir=None, artifact_path: str = "") -> dict:
    """Pure-ish projection of a target-pack artifact into a triage index.

    Reuses target_pack.summarize for the manifest merge + counts, then enriches
    each row with a preliminary verdict-level label, an answer snippet, fired
    hints, a suggested diagnose command, and (best-effort, read-only) the real
    layer from an existing diagnose-<qid>.json. Does NOT run diagnose/ingest.
    """
    per_query = (artifact_data.get("per_query")
                 or artifact_data.get("results") or [])
    by_qid = {}
    for rec in per_query:
        if isinstance(rec, dict):
            q = rec.get("question_id") or rec.get("qid")
            if q is not None:
                by_qid[q] = rec

    # manifest merge + counts (reuse the audited summarizer)
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import target_pack
        summ = target_pack.summarize(per_query, manifest)
    except Exception as e:
        summ = {"rows": [], "required_pass": 0, "required_total": 0,
                "observe_pass": 0, "observe_total": 0,
                "required_all_pass": False, "_error": repr(e)}

    rows = []
    for srow in summ.get("rows", []):
        qid = srow["qid"]
        pq = by_qid.get(qid, {})
        present = srow["present"]
        correct = srow["correct"]
        judge_failed = bool(pq.get("judge_failed"))
        hh = pq.get("helper_hints") or {}
        fired = [k for k, v in hh.items() if v and k != "answer_pure_abstain"]
        prelim = classify_preliminary(present, correct, judge_failed, hh,
                                      answer=pq.get("answer"))
        dj = _find_diagnose_json(diagnose_dir, qid)
        real_layer = None
        if dj is not None:
            try:
                d = json.loads(dj.read_text())
                real_layer = ((d.get("path_summary") or {})
                              .get("diagnosis") or {}).get("layer")
            except Exception:
                real_layer = None
        art = artifact_path or "<artifact.json>"
        rows.append({
            "qid": qid,
            "line": srow["line"],
            "mode": srow["mode"],
            "present": present,
            "correct": correct,
            "verdict": ("PASS" if correct else
                        ("MISSING" if not present else "WRONG")),
            "preliminary": prelim,
            "preliminary_meaning": PRELIM_MEANING.get(prelim, ""),
            "qtype": pq.get("qtype"),
            "answer_snippet": _trunc(pq.get("answer"), 160) or None,
            "hints": fired,
            "answer_pure_abstain": bool(hh.get("answer_pure_abstain")),
            "real_layer": real_layer,
            "diagnose_json": str(dj) if dj is not None else None,
            "suggested_command": (
                f"python -m bench.end_to_end.devtools diagnose --qid {qid} "
                f"--e2e-result {art}"),
        })

    return {
        "artifact": artifact_path or None,
        "summary": {
            "required_pass": summ.get("required_pass", 0),
            "required_total": summ.get("required_total", 0),
            "observe_pass": summ.get("observe_pass", 0),
            "observe_total": summ.get("observe_total", 0),
            "required_all_pass": summ.get("required_all_pass", False),
            "overall_accuracy": artifact_data.get("overall_accuracy"),
        },
        "rows": rows,
    }


_INDEX_CAVEAT = (
    "> ⚠ **Preliminary, verdict-level triage.** The `preliminary` column is "
    "NOT the authoritative `diagnosis.layer` — a target-pack artifact carries "
    "no `path_summary`. The `layer` column is filled only where an existing "
    "`diagnose-<qid>.json` was found on disk. To get the real layer for a red "
    "qid, run the suggested `devtools diagnose` command, then `devtools report "
    "--diagnose-json …`."
)


def _index_table(rows: list) -> list[str]:
    out = ["| qid | line | verdict | preliminary | layer | qtype | hints |",
           "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(
            f"| `{r['qid']}` | {r['line']} | {r['verdict']} | "
            f"{r['preliminary']} | {r['real_layer'] or '—'} | "
            f"{r.get('qtype') or '—'} | {', '.join(r['hints']) or '—'} |")
    return out


def render_index_md(index: dict) -> str:
    """Render the batch triage index.md. Pure."""
    s = index.get("summary") or {}
    rows = index.get("rows") or []
    required = [r for r in rows if r["mode"] == "required"]
    observe = [r for r in rows if r["mode"] == "observe_only"]
    reds = [r for r in rows if not r["correct"]]

    lines = [
        "# target-pack triage index",
        "",
        f"artifact: `{index.get('artifact') or '—'}`",
        f"required {s.get('required_pass')}/{s.get('required_total')} "
        f"| observe {s.get('observe_pass')}/{s.get('observe_total')} "
        f"| gate {'PASS' if s.get('required_all_pass') else 'FAIL'}",
        "",
        _INDEX_CAVEAT,
        "",
        "## Required (gates the pack)",
        *_index_table(required),
        "",
        "## Observe-only (never reds the pack)",
        *_index_table(observe),
    ]

    if reds:
        lines += ["", "## Next commands (red / missing qids)"]
        for r in reds:
            lines += [
                "",
                f"### `{r['qid']}` — {r['line']} ({r['preliminary']})",
                f"_{r['preliminary_meaning']}_",
            ]
            if r["answer_snippet"]:
                lines.append(f"- answer: {r['answer_snippet']}")
            if r["real_layer"]:
                lines.append(f"- known layer (from existing diagnose): "
                             f"`{r['real_layer']}`")
            lines += ["```bash", r["suggested_command"], "```"]
    return "\n".join(lines) + "\n"


def write_triage(index: dict, out_dir, artifact_path: str = "") -> dict:
    """Write index.md + triage.json into out_dir. For any row that already has a
    diagnose-<qid>.json on disk, also emit a per-qid <qid>/summary.md +
    diagnosis.json (reusing the single-report pipeline). Never runs diagnose."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    idx_md = out / "index.md"
    tj = out / "triage.json"
    idx_md.write_text(render_index_md(index))
    tj.write_text(json.dumps(index, indent=2, ensure_ascii=False))

    per_qid = {}
    for r in index.get("rows") or []:
        dj = r.get("diagnose_json")
        if not dj:
            continue
        try:
            data = load_diagnose_json(dj)
            rep = build_diagnosis_report(
                data, source=dj, manifest_line=r.get("line"),
                e2e_artifact=artifact_path or None)
            paths = write_report(rep, out / r["qid"])
            per_qid[r["qid"]] = {k: str(v) for k, v in paths.items()}
        except Exception as e:  # one bad rec must not sink the index
            per_qid[r["qid"]] = {"error": repr(e)}

    return {"index_md": idx_md, "triage_json": tj, "per_qid": per_qid}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render a diagnosis report. Single mode (--diagnose-json) "
                    "projects one diagnose rec; batch mode "
                    "(--target-pack-artifact) builds a verdict-level triage "
                    "index. Pure projection; never runs diagnose/ingest.",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--diagnose-json", type=Path,
                   help="An existing diagnose_qid.py output json (single mode).")
    g.add_argument("--target-pack-artifact", type=Path,
                   help="An existing target-pack result json (batch triage).")
    ap.add_argument("--out", type=Path, required=True,
                    help="Output directory.")
    ap.add_argument("--diagnose-dir", type=Path, default=None,
                    help="Batch mode: dir to look for existing diagnose-<qid>."
                         "json to enrich the index with real layers. Defaults "
                         "to the artifact's parent directory.")
    args = ap.parse_args()

    if args.target_pack_artifact:
        try:
            here = str(Path(__file__).resolve().parent)
            if here not in sys.path:
                sys.path.insert(0, here)
            import target_pack
            manifest = target_pack.MANIFEST
        except Exception as e:
            print(f"could not load target_pack.MANIFEST: {e}")
            return 2
        art = str(args.target_pack_artifact)
        ddir = args.diagnose_dir or args.target_pack_artifact.parent
        data = load_diagnose_json(args.target_pack_artifact)
        index = build_triage_index(data, manifest, diagnose_dir=ddir,
                                   artifact_path=art)
        paths = write_triage(index, args.out, artifact_path=art)
        s = index["summary"]
        n_red = sum(1 for r in index["rows"] if not r["correct"])
        print(f"triage: required {s['required_pass']}/{s['required_total']} "
              f"| {n_red} red/missing | gate "
              f"{'PASS' if s['required_all_pass'] else 'FAIL'}")
        print(f"  wrote: {paths['index_md']}")
        print(f"  wrote: {paths['triage_json']}")
        if paths["per_qid"]:
            print(f"  per-qid sub-reports: {len(paths['per_qid'])} "
                  f"(from existing diagnose jsons)")
        return 0

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
