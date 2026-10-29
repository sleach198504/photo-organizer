"""Turns (truth, engine result) into a nested dict of scores. No I/O and no app imports."""
from __future__ import annotations

from . import metrics
from .engine import EngineResult
from .truth import Truth


def score(truth: Truth, result: EngineResult) -> dict:
    out: dict = {
        "photos": len(result.paths),
        "tasks": truth.tasks,
        "notes": result.notes,
    }

    if "near_duplicates" in truth.tasks:
        out["exact"] = _exact(truth, result)
        out["near"] = _near(truth, result)
    if "keeper" in truth.tasks:
        out["keeper"] = _keeper(truth, result)
    if "flags" in truth.tasks:
        out["flags"] = _flags(truth, result)
    if "categories" in truth.tasks:
        out["categories"] = metrics.multiclass(truth.categories, result.categories)
    if "search" in truth.tasks and truth.queries:
        out["search"] = _search(truth, result)

    out["latency"] = _latency(result)
    return out


def _truth_groups(truth: Truth, kind: str) -> list[list[str]]:
    return [g.members for g in truth.groups if g.kind == kind]


def _exact(truth: Truth, result: EngineResult) -> dict:
    return metrics.pairwise_grouping(_truth_groups(truth, "exact"), result.exact_groups)


def _near(truth: Truth, result: EngineResult) -> dict:
    expected = _truth_groups(truth, "near")
    predicted = [g["members"] for g in result.near_groups]
    scores = metrics.pairwise_grouping(expected, predicted)
    scores["bcubed"] = metrics.bcubed(expected, predicted, result.paths)
    scores["shape"] = metrics.group_shape_errors(expected, predicted)
    scores["sweep"] = {
        str(d): {**metrics.pairwise_grouping(expected, groups),
                 **{k: v for k, v in metrics.group_shape_errors(expected, groups).items()
                    if k in ("merged_groups", "split_groups", "largest_predicted_group")}}
        for d, groups in sorted(result.near_sweep.items())
    }
    scores["problem_groups"] = _problem_groups(truth, result)
    return scores


def _problem_groups(truth: Truth, result: EngineResult) -> list[dict]:
    """Human-readable list of where grouping went wrong, so a score can be investigated."""
    predicted = [set(g["members"]) for g in result.near_groups]
    problems = []
    for group in truth.groups:
        if group.kind != "near":
            continue
        members = set(group.members)
        found = [p for p in predicted if len(p & members) >= 2]
        if not found:
            problems.append({"group": group.id, "problem": "not grouped", "tags": group.tags,
                             "members": sorted(members), "notes": [truth.notes.get(m, "") for m in sorted(members)]})
        elif len(found) > 1 or members - found[0]:
            problems.append({"group": group.id, "problem": "split", "tags": group.tags, "members": sorted(members)})
        elif found[0] - members:
            problems.append({"group": group.id, "problem": "merged with others", "tags": group.tags,
                             "extra": sorted(found[0] - members)})
    in_truth = {m for g in truth.groups if g.kind == "near" for m in g.members}
    for p in predicted:
        stray = p - in_truth
        if stray:
            problems.append({"group": None, "problem": "includes photos that are not alike",
                             "members": sorted(p), "unrelated": sorted(stray),
                             "notes": [truth.notes.get(m, "") for m in sorted(p)]})
    return problems


def _keeper(truth: Truth, result: EngineResult) -> dict:
    cases = []
    for group in truth.groups:
        if group.kind != "near" or not group.best:
            continue
        members = set(group.members)
        best_group = max(result.near_groups, key=lambda g: len(members & set(g["members"])), default=None)
        formed = best_group is not None and len(members & set(best_group["members"])) >= 2
        cases.append({
            "id": group.id,
            "best": group.best,
            "chosen": best_group["keeper"] if formed else None,
            "tags": group.tags,
            "notes": {m: truth.notes.get(m, "") for m in group.members},
        })
    return metrics.keeper_accuracy(cases)


def _scoreable(reason: str, truth: Truth, result: EngineResult) -> bool:
    """Blurry comes from the sharpness stage. Every other flag is raised inside the
    recognition stage. On generated pictures the model is not a fair judge, except for
    screenshots on PNG files, which are decided by file type before the model is asked."""
    if reason == "blurry":
        return True
    content_on = result.settings.get("content", True) and not any("not installed" in n for n in result.notes)
    # The screenshot check itself runs inside the recognition stage, so it needs it on.
    return content_on and (truth.content_reliable or reason == "screenshot")


def _flags(truth: Truth, result: EngineResult) -> dict:
    out: dict = {"by_reason": {}, "not_scored": []}
    for reason in truth.flag_names():
        if not _scoreable(reason, truth, result):
            out["not_scored"].append(reason)
            continue
        positives = {p for p, names in truth.flags.items() if reason in names}
        unsure = {p for p, names in truth.unsure.items() if reason in names}
        universe = result.paths
        scope = "all photos"
        if reason == "screenshot" and not truth.content_reliable:
            universe = [p for p in universe if p.lower().endswith(".png")]
            scope = "PNG files only"
        scores = metrics.binary_flag(universe, positives, result.flags.get(reason, set()), unsure)
        scores["scope"] = scope
        if reason == "blurry" and result.sharpness:
            scores["ranking_average_precision"] = metrics.average_precision(
                {p: -s for p, s in result.sharpness.items()}, positives, unsure)
        out["by_reason"][reason] = scores
    labelled = set(truth.flag_names())
    fair = truth.content_reliable or not result.settings.get("content", True)
    out["unlabelled_flags"] = {
        reason: len(paths) for reason, paths in sorted(result.flags.items())
        if reason not in labelled and fair
    }
    return out


def _search(truth: Truth, result: EngineResult) -> dict:
    return metrics.retrieval([
        {"text": q.text, "relevant": q.relevant, "ranked": result.search.get(q.text, [])} for q in truth.queries
    ])


def _latency(result: EngineResult) -> dict:
    n = max(1, len(result.paths))
    return {
        "seconds": result.timings,
        "ms_per_photo": {stage: round(1000 * s / n, 2) for stage, s in result.timings.items()},
    }


def headline(scores: dict) -> dict[str, float | None]:
    """The handful of numbers worth watching from run to run."""
    h: dict[str, float | None] = {}
    if "exact" in scores:
        h["exact.f1"] = scores["exact"]["f1"]
    if "near" in scores:
        near = scores["near"]
        h["near.precision"], h["near.recall"], h["near.f1"] = near["precision"], near["recall"], near["f1"]
        h["near.merged_groups"] = near["shape"]["merged_groups"]
        h["near.split_groups"] = near["shape"]["split_groups"]
    if "keeper" in scores:
        h["keeper.accuracy_overall"] = scores["keeper"]["all"]["accuracy_overall"]
        for tag, s in scores["keeper"]["by_tag"].items():
            h[f"keeper.{tag}"] = s["accuracy_overall"]
    for reason, s in scores.get("flags", {}).get("by_reason", {}).items():
        h[f"flag.{reason}.precision"], h[f"flag.{reason}.recall"] = s["precision"], s["recall"]
    if "categories" in scores:
        h["categories.accuracy"] = scores["categories"]["accuracy"]
    if "search" in scores:
        h["search.recall_at_5"], h["search.mrr"] = scores["search"]["recall_at_5"], scores["search"]["mrr"]
    for stage, ms in scores["latency"]["ms_per_photo"].items():
        h[f"latency.{stage}_ms_per_photo"] = ms
    return h
