"""Scoring functions. Pure: they take plain Python data and return plain numbers, so
every one of them is unit-tested without touching photos or the app."""
from __future__ import annotations

from itertools import combinations
from typing import Iterable


def _ratio(num: float, den: float) -> float | None:
    return num / den if den else None


def prf(tp: int, fp: int, fn: int) -> dict:
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = _ratio(2 * precision * recall, precision + recall) if precision and recall else (0.0 if tp + fp + fn else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def _pairs(groups: Iterable[Iterable[str]]) -> set[frozenset[str]]:
    out: set[frozenset[str]] = set()
    for members in groups:
        for a, b in combinations(sorted(set(members)), 2):
            out.add(frozenset((a, b)))
    return out


def pairwise_grouping(truth: list[list[str]], predicted: list[list[str]]) -> dict:
    """Did the engine put the same pairs of photos together as a person would?
    Counting pairs makes a group that swallowed its neighbour cost as much as it should."""
    t, p = _pairs(truth), _pairs(predicted)
    return prf(len(t & p), len(p - t), len(t - p))


def bcubed(truth: list[list[str]], predicted: list[list[str]], universe: Iterable[str]) -> dict:
    """B-cubed precision and recall over every photo, singletons included. It rewards
    leaving unrelated photos alone, which pair counting barely notices."""
    t_of: dict[str, frozenset[str]] = {}
    p_of: dict[str, frozenset[str]] = {}
    for members in truth:
        for m in members:
            t_of[m] = frozenset(members)
    for members in predicted:
        for m in members:
            p_of[m] = frozenset(members)
    items = list(universe)
    if not items:
        return {"precision": None, "recall": None}
    precision = recall = 0.0
    for item in items:
        t_set = t_of.get(item, frozenset((item,)))
        p_set = p_of.get(item, frozenset((item,)))
        overlap = len(t_set & p_set)
        precision += overlap / len(p_set)
        recall += overlap / len(t_set)
    return {"precision": precision / len(items), "recall": recall / len(items)}


def group_shape_errors(truth: list[list[str]], predicted: list[list[str]]) -> dict:
    """The two ways a grouping goes wrong in the review screen: a set that merges
    different moments (the person must pull them apart) and a moment split across
    sets (the person reviews it twice)."""
    t_index = {m: i for i, members in enumerate(truth) for m in members}
    p_index = {m: i for i, members in enumerate(predicted) for m in members}
    merged = sum(1 for members in predicted if len({t_index.get(m, f"solo:{m}") for m in members}) > 1)
    split = sum(1 for members in truth if len({p_index.get(m, f"solo:{m}") for m in members}) > 1)
    largest = max((len(g) for g in predicted), default=0)
    return {
        "predicted_groups": len(predicted),
        "truth_groups": len(truth),
        "merged_groups": merged,
        "split_groups": split,
        "largest_predicted_group": largest,
        "largest_truth_group": max((len(g) for g in truth), default=0),
    }


# ---------------------------------------------------------------------------
# Keeper choice
# ---------------------------------------------------------------------------


def keeper_accuracy(cases: list[dict]) -> dict:
    """Each case: {"id", "best": [...], "chosen": path|None, "tags": [...]}.
    A case where the engine never formed the group has chosen=None and counts as wrong,
    but is reported separately so a grouping miss isn't blamed on keeper logic."""
    def score(subset: list[dict]) -> dict:
        answered = [c for c in subset if c["chosen"] is not None]
        right = sum(1 for c in answered if c["chosen"] in c["best"])
        return {
            "cases": len(subset),
            "answered": len(answered),
            "correct": right,
            "accuracy_when_answered": _ratio(right, len(answered)),
            "accuracy_overall": _ratio(right, len(subset)),
        }

    result = {"all": score(cases)}
    tags = sorted({t for c in cases for t in c.get("tags", [])})
    result["by_tag"] = {t: score([c for c in cases if t in c.get("tags", [])]) for t in tags}
    result["wrong"] = [c["id"] for c in cases if c["chosen"] is not None and c["chosen"] not in c["best"]]
    return result


# ---------------------------------------------------------------------------
# Flags (one yes/no decision per photo per reason)
# ---------------------------------------------------------------------------


def binary_flag(universe: Iterable[str], positives: set[str], flagged: set[str], unsure: set[str] = frozenset()) -> dict:
    scored = [p for p in universe if p not in unsure]
    tp = sum(1 for p in scored if p in positives and p in flagged)
    fp = sum(1 for p in scored if p not in positives and p in flagged)
    fn = sum(1 for p in scored if p in positives and p not in flagged)
    tn = len(scored) - tp - fp - fn
    out = prf(tp, fp, fn)
    out.update({
        "tn": tn,
        "false_positive_rate": _ratio(fp, fp + tn),
        "positives": sum(1 for p in scored if p in positives),
        "ignored_unsure": len(set(unsure) & set(universe)),
        "false_positive_paths": sorted(p for p in scored if p not in positives and p in flagged),
        "missed_paths": sorted(p for p in scored if p in positives and p not in flagged),
    })
    return out


def average_precision(scores: dict[str, float], positives: set[str], ignore: set[str] = frozenset()) -> float | None:
    """How well a raw score ranks the positives above the negatives, whatever threshold is
    later chosen. Higher score = more likely positive."""
    ranked = sorted((p for p in scores if p not in ignore), key=lambda p: scores[p], reverse=True)
    total = sum(1 for p in ranked if p in positives)
    if not total:
        return None
    hits, running = 0, 0.0
    for rank, path in enumerate(ranked, start=1):
        if path in positives:
            hits += 1
            running += hits / rank
    return running / total


# ---------------------------------------------------------------------------
# Categories (one label per photo)
# ---------------------------------------------------------------------------


def multiclass(truth: dict[str, str], predicted: dict[str, str], other: str = "other") -> dict:
    """Both maps are path -> label; a missing prediction means `other`."""
    paths = sorted(truth)
    labels = sorted({truth[p] for p in paths} | {predicted.get(p, other) for p in paths})
    confusion: dict[str, dict[str, int]] = {t: {} for t in labels}
    for p in paths:
        guess = predicted.get(p, other)
        confusion[truth[p]][guess] = confusion[truth[p]].get(guess, 0) + 1
    per_class = {}
    for label in labels:
        tp = confusion[label].get(label, 0)
        fn = sum(n for g, n in confusion[label].items() if g != label)
        fp = sum(row.get(label, 0) for t, row in confusion.items() if t != label)
        per_class[label] = prf(tp, fp, fn)
    correct = sum(confusion[l].get(l, 0) for l in labels)
    return {
        "photos": len(paths),
        "accuracy": _ratio(correct, len(paths)),
        "per_class": per_class,
        "confusion": confusion,
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def retrieval(queries: list[dict], ks: tuple[int, ...] = (1, 5, 10)) -> dict:
    """Each query: {"text", "relevant": [...], "ranked": [...]} with `ranked` best first."""
    recalls = {k: [] for k in ks}
    reciprocal = []
    for q in queries:
        relevant = set(q["relevant"])
        if not relevant:
            continue
        for k in ks:
            recalls[k].append(len(relevant & set(q["ranked"][:k])) / len(relevant))
        first = next((i for i, p in enumerate(q["ranked"], 1) if p in relevant), None)
        reciprocal.append(1 / first if first else 0.0)
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    return {
        "queries": len(reciprocal),
        **{f"recall_at_{k}": mean(v) for k, v in recalls.items()},
        "mrr": mean(reciprocal),
    }
