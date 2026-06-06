"""stability_report.py — n-run stability report (VR-3b, pure artifact parser).

Aggregates several Mem0-protocol runs (each a single-answer + single-judge run)
that share the SAME qid set AND order into a stability view: run-score
mean/std/min/max, per-qid pass-rate + mode verdict, and an unstable-qid table.

**It does NOT change the evaluation protocol.** Each input artifact is still a
verbatim single-run Mem0-compatible score; this only reports statistics over
several of them. NO benchmark run, NO ingest, NO runtime change.

Interpretation (critical, encoded in output):
- DEFAULT = `cross-version-envelope`: the runs may be DIFFERENT architecture
  versions, so mean/std mixes version differences + sampling noise — it is a
  descriptive envelope, NOT a pure same-architecture run-to-run std.
- `--same-arch` only RELABELS the interpretation to `same-arch-stability`
  (caller asserts all inputs are the same code version). It does NOT verify the
  architecture — it is an annotation, used only when the inputs really are
  repeats of one version.

Usage (via devtools):
  python -m bench.end_to_end.devtools stability-report \
    --artifacts a.json b.json c.json --out reports/stability [--same-arch]

Building blocks (pure, unit-tested):
  load_artifact(path)                      -> dict
  qid_order(data)                          -> list[str]
  build_stability_report(runs, same_arch, current) -> dict
  render_summary_md(report)                -> str
  write_stability(report, out_dir)         -> dict
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def load_artifact(path: str | Path) -> dict:
    """Read a runner result json. Pure IO."""
    return json.loads(Path(path).read_text())


def _per_query(data: dict) -> list:
    return data.get("per_query") or data.get("results") or []


def qid_order(data: dict) -> list:
    return [r.get("question_id") or r.get("qid")
            for r in _per_query(data) if isinstance(r, dict)]


class StabilityInputError(Exception):
    """same-set/same-order validation failure."""


def _validate_same_qids(runs: list) -> None:
    """All runs must share identical qid order (implies same set + length).
    Raises StabilityInputError listing the first mismatch."""
    if len(runs) < 2:
        raise StabilityInputError("need >= 2 artifacts to build a stability report")
    ref_label, ref_data = runs[0]
    ref = qid_order(ref_data)
    for label, data in runs[1:]:
        cur = qid_order(data)
        if len(cur) != len(ref):
            raise StabilityInputError(
                f"per_query length differs: {ref_label}={len(ref)} vs "
                f"{label}={len(cur)}")
        if set(cur) != set(ref):
            only_ref = sorted(set(ref) - set(cur))[:5]
            only_cur = sorted(set(cur) - set(ref))[:5]
            raise StabilityInputError(
                f"qid SET differs ({ref_label} vs {label}): "
                f"only in {ref_label}={only_ref}; only in {label}={only_cur}")
        if cur != ref:
            i = next(k for k in range(len(ref)) if ref[k] != cur[k])
            raise StabilityInputError(
                f"qid ORDER differs ({ref_label} vs {label}) at index {i}: "
                f"{ref[i]} vs {cur[i]}")


def _correct_map(data: dict) -> dict:
    return {(r.get("question_id") or r.get("qid")): bool(r.get("correct"))
            for r in _per_query(data) if isinstance(r, dict)}


def _qtype_map(data: dict) -> dict:
    return {(r.get("question_id") or r.get("qid")): r.get("qtype")
            for r in _per_query(data) if isinstance(r, dict)}


def build_stability_report(runs: list, same_arch: bool = False,
                           current: str | None = None) -> dict:
    """Pure. runs = [(label, data), ...] sharing same qid order. Returns the
    stability.json structure. Raises StabilityInputError on set/order mismatch."""
    _validate_same_qids(runs)
    qids = qid_order(runs[0][1])
    qtypes = _qtype_map(runs[0][1])
    cmaps = [(label, _correct_map(data)) for label, data in runs]

    # run-level scores computed from per_query (self-consistent with per-qid),
    # plus the artifact's own reported overall_accuracy for cross-check.
    run_rows = []
    for (label, data), (_, cm) in zip(runs, cmaps):
        n = len(cm)
        score = round(sum(cm.values()) / n, 4) if n else None
        run_rows.append({
            "label": label,
            "score": score,
            "reported_overall_accuracy": data.get("overall_accuracy"),
            "answer_model": data.get("answer_model"),
            "judge_model": data.get("judge_model"),
            "n": n,
        })

    scores = [r["score"] for r in run_rows if r["score"] is not None]
    agg = {
        "n_runs": len(run_rows),
        "mean": round(statistics.mean(scores), 4) if scores else None,
        "std": round(statistics.stdev(scores), 4) if len(scores) > 1 else 0.0,
        "min": min(scores) if scores else None,
        "max": max(scores) if scores else None,
        "median": round(statistics.median(scores), 4) if scores else None,
        "interpretation": "same-arch-stability" if same_arch
                          else "cross-version-envelope",
    }

    per_qid = []
    for q in qids:
        passes = [cm[q] for _, cm in cmaps if q in cm]
        n = len(passes)
        n_pass = sum(1 for p in passes if p)
        pr = round(n_pass / n, 4) if n else None
        if pr is None:
            mode = "?"
        elif pr > 0.5:
            mode = "P"
        elif pr < 0.5:
            mode = "F"
        else:
            mode = "TIE"
        per_qid.append({
            "qid": q, "qtype": qtypes.get(q),
            "n_pass": n_pass, "n_runs": n, "pass_rate": pr,
            "mode_verdict": mode, "stable": pr in (0.0, 1.0),
        })

    unstable = sorted(
        [r for r in per_qid if r["pass_rate"] not in (0.0, 1.0, None)],
        key=lambda r: abs(r["pass_rate"] - 0.5))

    by_qtype: dict = {}
    for r in per_qid:
        qt = r["qtype"] or "?"
        by_qtype.setdefault(qt, []).append(r["pass_rate"] or 0.0)
    by_qtype = {qt: round(sum(v) / len(v), 4) for qt, v in sorted(by_qtype.items())}

    family = {
        "stable_pass": sum(1 for r in per_qid if r["pass_rate"] == 1.0),
        "stable_fail": sum(1 for r in per_qid if r["pass_rate"] == 0.0),
        "unstable": len(unstable),
    }

    placement = None
    if current is not None:
        cur_row = next((r for r in run_rows if r["label"] == current
                        or Path(str(r["label"])).name == Path(current).name), None)
        if cur_row and cur_row["score"] is not None and scores:
            s = cur_row["score"]
            below = sum(1 for x in scores if x < s)
            placement = {
                "label": cur_row["label"], "score": s,
                "percentile": round(100 * below / len(scores), 1),
                "is_max": s >= max(scores), "is_min": s <= min(scores),
                "delta_vs_mean": round(s - agg["mean"], 4),
                "delta_vs_max": round(s - max(scores), 4),
            }

    return {
        "runs": run_rows,
        "aggregate": agg,
        "per_qid": per_qid,
        "unstable_qids": unstable,
        "by_qtype": by_qtype,
        "family_summary": family,
        "placement": placement,
    }


_CAVEAT = {
    "cross-version-envelope":
        "> ⚠ **cross-version envelope** — these runs may be DIFFERENT "
        "architecture versions, so mean/std mixes version differences with "
        "sampling noise. This is a descriptive envelope, NOT a pure "
        "same-architecture run-to-run std. For a true stability std, run k "
        "repeats of ONE version and pass --same-arch.",
    "same-arch-stability":
        "> **same-arch stability** (caller-asserted) — inputs are repeats of "
        "one architecture version; mean/std approximates run-to-run sampling "
        "noise. NB: --same-arch is an annotation, not a verified fact.",
}


def render_summary_md(report: dict) -> str:
    agg = report["aggregate"]
    interp = agg["interpretation"]
    lines = [
        "# stability report",
        "",
        _CAVEAT[interp],
        "",
        f"**runs:** {agg['n_runs']}  |  **mean:** {agg['mean']}  "
        f"**std:** {agg['std']}  **min:** {agg['min']}  **max:** {agg['max']}  "
        f"**median:** {agg['median']}",
        f"**interpretation:** `{interp}`",
        "",
        "## Runs",
        "| label | score | reported_acc | answer | judge |",
        "|---|---|---|---|---|",
    ]
    for r in report["runs"]:
        lines.append(
            f"| {Path(str(r['label'])).name} | {r['score']} | "
            f"{r['reported_overall_accuracy']} | {r['answer_model']} | "
            f"{r['judge_model']} |")

    p = report.get("placement")
    if p:
        lines += [
            "",
            "## Placement (highlighted run)",
            f"- `{Path(str(p['label'])).name}` score **{p['score']}** — "
            f"percentile {p['percentile']}  "
            f"{'(== MAX, high-end/lucky)' if p['is_max'] else ''}"
            f"{'(== MIN, low-end/unlucky)' if p['is_min'] else ''}",
            f"- Δ vs mean {p['delta_vs_mean']:+}, Δ vs max {p['delta_vs_max']:+}",
        ]

    fam = report["family_summary"]
    lines += [
        "",
        "## Per-qid stability",
        f"stable-pass {fam['stable_pass']} | stable-fail {fam['stable_fail']} | "
        f"unstable {fam['unstable']}",
        "",
        "### Unstable qids (0 < pass_rate < 1, most unstable first)",
        "| qid | qtype | pass_rate | n_pass/n | mode |",
        "|---|---|---|---|---|",
    ]
    for r in report["unstable_qids"]:
        lines.append(
            f"| `{r['qid']}` | {r['qtype'] or '—'} | {r['pass_rate']} | "
            f"{r['n_pass']}/{r['n_runs']} | {r['mode_verdict']} |")
    if not report["unstable_qids"]:
        lines.append("| (none — every qid is stable across runs) | | | | |")

    lines += ["", "## By qtype (mean pass-rate)"]
    for qt, pr in report["by_qtype"].items():
        lines.append(f"- {qt}: {pr}")
    return "\n".join(lines) + "\n"


def write_stability(report: dict, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sj = out / "stability.json"
    sm = out / "summary.md"
    sj.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    sm.write_text(render_summary_md(report))
    return {"stability_json": sj, "summary_md": sm}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifacts", nargs="+", required=True,
                    help="Two+ runner result jsons with identical qid set+order.")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--same-arch", action="store_true",
                    help="Annotate as same-arch stability (NOT verified). "
                         "Default: cross-version envelope.")
    ap.add_argument("--current", default=None,
                    help="An artifact path/name to highlight in placement.")
    args = ap.parse_args()

    runs = [(p, load_artifact(p)) for p in args.artifacts]
    try:
        report = build_stability_report(runs, same_arch=args.same_arch,
                                        current=args.current)
    except StabilityInputError as e:
        print(f"stability-report: input error — {e}")
        return 2
    paths = write_stability(report, args.out)
    a = report["aggregate"]
    print(f"stability: {a['n_runs']} runs  mean={a['mean']} std={a['std']} "
          f"min={a['min']} max={a['max']}  [{a['interpretation']}]")
    print(f"  unstable qids: {report['family_summary']['unstable']}")
    print(f"  wrote: {paths['stability_json']}")
    print(f"  wrote: {paths['summary_md']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
