"""Writes a run to disk (JSON for machines, Markdown for people) and compares two runs."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .engine import machine_info
from .score import headline

ROOT = Path(__file__).resolve().parents[2]


def _git_state() -> dict:
    def run(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return ""

    return {"commit": run("rev-parse", "--short", "HEAD"), "dirty": bool(run("status", "--porcelain", "--", "app"))}


def build_run(dataset: str, engine: str, scores: dict, settings: dict) -> dict:
    return {
        "dataset": dataset,
        "engine": engine,
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": _git_state(),
        "machine": machine_info(),
        "settings": settings,
        "scores": scores,
        "headline": headline(scores),
    }


def write(run: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = run["when"].replace(":", "").replace("-", "")[:15]
    stem = f"{run['dataset']}_{run['engine']}_{stamp}"
    json_path, md_path = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(run, indent=1, default=_json_default), encoding="utf-8")
    md_path.write_text(markdown(run), encoding="utf-8")
    return json_path, md_path


def _json_default(value):
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"not serialisable: {type(value)}")


def _pct(value) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def markdown(run: dict) -> str:
    s = run["scores"]
    lines = [
        f"# Evaluation: {run['dataset']} / {run['engine']}",
        "",
        f"Run {run['when']} on commit `{run['git']['commit']}`{' (app files modified)' if run['git']['dirty'] else ''}. "
        f"{s['photos']} photos. Machine: {run['machine']['processor'] or run['machine']['platform']}, "
        f"{run['machine']['cpu_count']} threads, {run['machine']['ram_gb']} GB.",
        "",
    ]
    for note in s["notes"]:
        lines += [f"> {note}", ""]

    if "exact" in s:
        e, n = s["exact"], s["near"]
        lines += [
            "## Duplicates and similar photos", "",
            "| Task | Precision | Recall | F1 | Missed pairs | Wrong pairs |", "| --- | --- | --- | --- | --- | --- |",
            f"| Exact copies | {_pct(e['precision'])} | {_pct(e['recall'])} | {_pct(e['f1'])} | {e['fn']} | {e['fp']} |",
            f"| Similar photos | {_pct(n['precision'])} | {_pct(n['recall'])} | {_pct(n['f1'])} | {n['fn']} | {n['fp']} |",
            "",
            f"Photo-level (B-cubed): precision {_pct(n['bcubed']['precision'])}, recall {_pct(n['bcubed']['recall'])}. "
            f"Sets that merged different moments: **{n['shape']['merged_groups']}**. "
            f"Moments split across sets: **{n['shape']['split_groups']}**. "
            f"Largest set found {n['shape']['largest_predicted_group']} (largest real one {n['shape']['largest_truth_group']}).",
            "",
            "Threshold sweep (Hamming distance; the app uses "
            f"{run['settings'].get('near_duplicate_hash_distance')}):", "",
            "| Distance | Precision | Recall | F1 | Merged sets | Split moments | Largest set |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for d, row in n["sweep"].items():
            lines.append(f"| {d} | {_pct(row['precision'])} | {_pct(row['recall'])} | {_pct(row['f1'])} | "
                         f"{row['merged_groups']} | {row['split_groups']} | {row['largest_predicted_group']} |")
        lines.append("")
        if n["problem_groups"]:
            lines += ["Where grouping went wrong:", ""]
            for p in n["problem_groups"][:25]:
                lines.append(f"- **{p['problem']}** {('(' + ', '.join(p['tags']) + ')') if p.get('tags') else ''} "
                             f"{', '.join(p['members'][:4])}{' ...' if len(p['members']) > 4 else ''}")
            lines.append("")

    if "keeper" in s:
        k = s["keeper"]
        lines += ["## Which photo to keep", "", "| Case | Groups | Right pick | Not grouped |", "| --- | --- | --- | --- |"]
        lines.append(f"| All | {k['all']['cases']} | {_pct(k['all']['accuracy_overall'])} | "
                     f"{k['all']['cases'] - k['all']['answered']} |")
        for tag, row in k["by_tag"].items():
            lines.append(f"| {tag} | {row['cases']} | {_pct(row['accuracy_overall'])} | {row['cases'] - row['answered']} |")
        lines.append("")

    if "flags" in s:
        lines += ["## Flags", "", "| Reason | Precision | Recall | False alarms | Missed | Ranking AP |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for reason, f in s["flags"]["by_reason"].items():
            label = reason if f["scope"] == "all photos" else f"{reason} ({f['scope']})"
            lines.append(f"| {label} | {_pct(f['precision'])} | {_pct(f['recall'])} | {f['fp']} | {f['fn']} | "
                         f"{_pct(f.get('ranking_average_precision'))} |")
        if s["flags"]["not_scored"]:
            lines += ["", "Not scored here: " + ", ".join(s["flags"]["not_scored"]) +
                      " (they need the recognition model, which cannot be judged fairly on generated pictures; "
                      "run on labelled real photos to score them)."]
        extra = s["flags"]["unlabelled_flags"]
        if extra:
            lines += ["", "Flags the app raised for reasons this dataset does not label: " +
                      ", ".join(f"{k} ({v})" for k, v in extra.items()) + "."]
        lines.append("")

    if "categories" in s:
        c = s["categories"]
        lines += ["## Categories", "", f"Accuracy {_pct(c['accuracy'])} over {c['photos']} photos.", "",
                  "| Category | Precision | Recall | F1 |", "| --- | --- | --- | --- |"]
        for label, row in c["per_class"].items():
            lines.append(f"| {label} | {_pct(row['precision'])} | {_pct(row['recall'])} | {_pct(row['f1'])} |")
        lines.append("")

    if "search" in s:
        q = s["search"]
        lines += ["## Search", "", f"{q['queries']} queries: recall@1 {_pct(q['recall_at_1'])}, "
                  f"recall@5 {_pct(q['recall_at_5'])}, recall@10 {_pct(q['recall_at_10'])}, MRR {q['mrr']:.2f}.", ""]

    lat = s["latency"]
    lines += ["## Speed", "", "| Stage | Seconds | ms per photo |", "| --- | --- | --- |"]
    for stage, secs in lat["seconds"].items():
        lines.append(f"| {stage} | {secs} | {lat['ms_per_photo'][stage]} |")
    lines.append("")
    return "\n".join(lines)


def compare(before: dict, after: dict) -> str:
    """Side-by-side headline numbers; arrows only mark a move of more than half a point."""
    a, b = before["headline"], after["headline"]
    lines = [f"Comparing {before['engine']} ({before['when'][:10]}) with {after['engine']} ({after['when'][:10]})", "",
             f"{'metric':<42}{'before':>10}{'after':>10}{'change':>10}"]
    for key in sorted(set(a) | set(b)):
        x, y = a.get(key), b.get(key)
        if x is None or y is None:
            lines.append(f"{key:<42}{_fmt(key, x):>10}{_fmt(key, y):>10}")
            continue
        change = y - x
        lines.append(f"{key:<42}{_fmt(key, x):>10}{_fmt(key, y):>10}{_delta(key, change):>10}")
    return "\n".join(lines)


def _is_ratio(key: str) -> bool:
    return not (key.startswith("latency.") or key.endswith("_groups"))


def _fmt(key: str, value) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%" if _is_ratio(key) else f"{value:g}"


def _delta(key: str, change: float) -> str:
    if _is_ratio(key):
        return "" if abs(change) < 0.005 else f"{change * 100:+.1f}"
    return "" if change == 0 else f"{change:+g}"
