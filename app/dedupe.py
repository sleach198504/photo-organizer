from __future__ import annotations

import logging
from datetime import datetime, timezone

import imagehash

from .quality import LOW_DETAIL

log = logging.getLogger(__name__)


class _BKNode:
    __slots__ = ("hash_obj", "photo_id", "children")

    def __init__(self, hash_obj: imagehash.ImageHash, photo_id: int):
        self.hash_obj = hash_obj
        self.photo_id = photo_id
        self.children: dict[int, "_BKNode"] = {}


class _BKTree:
    """Groups perceptually-similar photos without comparing every pair against every
    other pair (which doesn't scale past a few thousand photos). A BK-tree indexes by
    Hamming distance so a lookup only has to visit nearby branches."""

    def __init__(self) -> None:
        self.root: _BKNode | None = None

    def add(self, hash_obj: imagehash.ImageHash, photo_id: int) -> None:
        if self.root is None:
            self.root = _BKNode(hash_obj, photo_id)
            return
        node = self.root
        while True:
            dist = node.hash_obj - hash_obj
            child = node.children.get(dist)
            if child is None:
                node.children[dist] = _BKNode(hash_obj, photo_id)
                return
            node = child

    def query(self, hash_obj: imagehash.ImageHash, max_distance: int) -> list[int]:
        if self.root is None:
            return []
        results = []
        stack = [self.root]
        while stack:
            node = stack.pop()
            dist = node.hash_obj - hash_obj
            if dist <= max_distance:
                results.append(node.photo_id)
            for child_dist, child in node.children.items():
                if abs(child_dist - dist) <= max_distance:
                    stack.append(child)
        return results


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def clear_duplicate_analysis(conn) -> None:
    """Duplicate groups are fully recomputed on every analysis pass, so previous
    ones are cleared first, along with any recommendation that isn't a final,
    user-made decision yet. 'approved' here only means "the auto-quarantine policy
    decided this" - not yet acted on - so it's safe to recompute too. A 'rejected'
    recommendation means the user looked at this and said no, so it's preserved and
    _add_recommendation below won't re-flag it."""
    conn.execute("DELETE FROM dup_groups")
    conn.execute(
        "DELETE FROM recommendations WHERE reason IN "
        "('exact_duplicate', 'near_duplicate', 'video_near_duplicate') AND decision != 'rejected'"
    )
    conn.commit()


def _add_recommendation(conn, photo_id: int, reason: str, auto_approve: bool) -> None:
    existing = conn.execute(
        "SELECT id FROM recommendations WHERE photo_id = ? AND reason = ?", (photo_id, reason)
    ).fetchone()
    if existing:
        return  # a 'rejected' decision survived clear_duplicate_analysis - respect it

    now = datetime.now(timezone.utc).isoformat()
    if auto_approve:
        conn.execute(
            "INSERT INTO recommendations (photo_id, reason, confidence, decision, decided_at) "
            "VALUES (?, ?, 1.0, 'approved', ?)",
            (photo_id, reason, now),
        )
    else:
        conn.execute(
            "INSERT INTO recommendations (photo_id, reason, confidence, decision) VALUES (?, ?, 1.0, 'pending')",
            (photo_id, reason),
        )


def _create_group(conn, kind: str, member_ids: list[int], keeper_id: int, reason: str, auto_approve: bool) -> None:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute("INSERT INTO dup_groups (kind, created_at) VALUES (?, ?)", (kind, now))
    group_id = cur.lastrowid
    for photo_id in member_ids:
        conn.execute(
            "INSERT INTO dup_group_members (group_id, photo_id, is_keeper) VALUES (?, ?, ?)",
            (group_id, photo_id, 1 if photo_id == keeper_id else 0),
        )
        if photo_id != keeper_id:
            _add_recommendation(conn, photo_id, reason, auto_approve)


def find_exact_duplicates(conn, auto_approve: bool) -> int:
    rows = conn.execute(
        """
        SELECT sha256, GROUP_CONCAT(id) AS ids
        FROM photos
        WHERE status = 'active'
        GROUP BY sha256
        HAVING COUNT(*) > 1
        """
    ).fetchall()

    group_count = 0
    for row in rows:
        member_ids = [int(x) for x in row["ids"].split(",")]
        keeper_id = min(member_ids)  # byte-identical files - any is fine, pick deterministically
        _create_group(conn, "exact", member_ids, keeper_id, "exact_duplicate", auto_approve)
        group_count += 1
    conn.commit()
    return group_count


def _exact_keeper_map(conn) -> dict[int, int]:
    rows = conn.execute(
        """
        SELECT dgm.photo_id AS photo_id, keeper.photo_id AS keeper_id
        FROM dup_group_members dgm
        JOIN dup_groups dg ON dg.id = dgm.group_id AND dg.kind = 'exact'
        JOIN dup_group_members keeper ON keeper.group_id = dgm.group_id AND keeper.is_keeper = 1
        """
    ).fetchall()
    return {row["photo_id"]: row["keeper_id"] for row in rows}


# A shot counts as "sharp enough to keep" if its focus score is at least this share of the
# best one in its set. Below that, a larger file does not make up for being out of focus.
KEEPER_FOCUS_SHARE = 0.5


def _pick_keeper(conn, member_ids: list[int]) -> int:
    """Quality first, size second. Among the shots that are about as sharp as the best,
    take the biggest; if two are the same size, the sharper one. So a crisp small copy
    beats a soft large one, and between equally sharp shots the higher resolution wins."""
    placeholders = ",".join("?" * len(member_ids))
    rows = conn.execute(
        f"SELECT id, width, height, blur_score FROM photos WHERE id IN ({placeholders})",
        member_ids,
    ).fetchall()

    def focus(row) -> float:
        return row["blur_score"] if row["blur_score"] is not None else -1.0

    best_focus = max(focus(r) for r in rows)
    sharp_enough = [r for r in rows if focus(r) >= KEEPER_FOCUS_SHARE * best_focus] or rows
    return max(sharp_enough, key=lambda r: ((r["width"] or 0) * (r["height"] or 0), focus(r), -r["id"]))["id"]


# Two photos in one set may be this much further apart than the similarity setting allows
# for neighbours, to tolerate burst drift. It stops chains (A looks like B, B like C, C like
# D...) from dragging unrelated pictures into one set.
SET_DIAMETER_SLACK = 4


def _split_chains(members: list[int], hashes: dict[int, imagehash.ImageHash], limit: int) -> list[list[int]]:
    """`members` is one chain-linked component. Returned as-is if every pair is within
    `limit`; otherwise regrouped so that no two photos in a set are further apart than that."""
    ordered = sorted(members)
    if all(hashes[a] - hashes[b] <= limit for i, a in enumerate(ordered) for b in ordered[i + 1:]):
        return [ordered]
    clusters: list[list[int]] = []
    for photo_id in ordered:
        best, best_total = None, None
        for cluster in clusters:
            distances = [hashes[photo_id] - hashes[m] for m in cluster]
            if max(distances) <= limit and (best is None or sum(distances) / len(cluster) < best_total):
                best, best_total = cluster, sum(distances) / len(cluster)
        if best is None:
            clusters.append([photo_id])
        else:
            best.append(photo_id)
    return clusters


def cluster_near_duplicates(conn, max_distance: int) -> int:
    # Pictures with almost no detail (a sky, a plain wall) all hash alike, so a perceptual
    # hash can't tell them apart. They are left out; byte-identical copies still match.
    rows = conn.execute(
        "SELECT id, phash FROM photos WHERE status = 'active' AND media_type = 'photo' AND phash IS NOT NULL "
        "AND (detail_score IS NULL OR detail_score >= ?)",
        (LOW_DETAIL,),
    ).fetchall()

    # Exact-duplicate copies share a phash by definition - collapse each exact-dup
    # group down to its keeper before clustering, so near-dup groups aren't just
    # rediscovering the same byte-identical copies again.
    keeper_map = _exact_keeper_map(conn)
    hash_by_rep: dict[int, imagehash.ImageHash] = {}
    for row in rows:
        rep_id = keeper_map.get(row["id"], row["id"])
        if rep_id not in hash_by_rep:
            hash_by_rep[rep_id] = imagehash.hex_to_hash(row["phash"])

    tree = _BKTree()
    uf = _UnionFind()
    for rep_id, h in hash_by_rep.items():
        for other_id in tree.query(h, max_distance):
            uf.union(rep_id, other_id)
        tree.add(h, rep_id)

    components: dict[int, list[int]] = {}
    for rep_id in hash_by_rep:
        components.setdefault(uf.find(rep_id), []).append(rep_id)

    cluster_count = 0
    for component in components.values():
        if len(component) < 2:
            continue
        for members in _split_chains(component, hash_by_rep, max_distance + SET_DIAMETER_SLACK):
            if len(members) < 2:
                continue
            keeper_id = _pick_keeper(conn, members)
            _create_group(conn, "near", members, keeper_id, "near_duplicate", auto_approve=False)
            cluster_count += 1
    conn.commit()
    return cluster_count


def _pick_video_keeper(conn, member_ids: list[int]) -> int:
    """Blur/resolution aren't meaningful quality signals for video, so keeper
    selection instead prefers the longer clip (more likely the "real" take, not a
    trimmed/aborted retry), then the larger file as a tiebreak."""
    placeholders = ",".join("?" * len(member_ids))
    rows = conn.execute(
        f"SELECT id, duration_seconds, size_bytes FROM photos WHERE id IN ({placeholders})",
        member_ids,
    ).fetchall()

    def score(row) -> tuple[float, int]:
        return (row["duration_seconds"] or 0.0, row["size_bytes"] or 0)

    return max(rows, key=score)["id"]


def cluster_video_near_duplicates(conn, max_distance: int) -> int:
    """Same BK-tree/union-find approach as cluster_near_duplicates, but scoped to
    videos and keyed off each video's representative-frame phash (computed at
    index time from the middle frame) instead of a whole-image hash."""
    rows = conn.execute(
        "SELECT id, phash FROM photos WHERE status = 'active' AND media_type = 'video' AND phash IS NOT NULL"
    ).fetchall()

    keeper_map = _exact_keeper_map(conn)
    hash_by_rep: dict[int, imagehash.ImageHash] = {}
    for row in rows:
        rep_id = keeper_map.get(row["id"], row["id"])
        if rep_id not in hash_by_rep:
            hash_by_rep[rep_id] = imagehash.hex_to_hash(row["phash"])

    tree = _BKTree()
    uf = _UnionFind()
    for rep_id, h in hash_by_rep.items():
        for other_id in tree.query(h, max_distance):
            uf.union(rep_id, other_id)
        tree.add(h, rep_id)

    groups: dict[int, list[int]] = {}
    for rep_id in hash_by_rep:
        root = uf.find(rep_id)
        groups.setdefault(root, []).append(rep_id)

    cluster_count = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        keeper_id = _pick_video_keeper(conn, members)
        _create_group(conn, "video_near", members, keeper_id, "video_near_duplicate", auto_approve=False)
        cluster_count += 1
    conn.commit()
    return cluster_count


def run_dedupe(conn, near_duplicate_hash_distance: int, auto_quarantine_exact_duplicates: bool) -> dict:
    clear_duplicate_analysis(conn)
    exact_groups = find_exact_duplicates(conn, auto_approve=auto_quarantine_exact_duplicates)
    near_groups = cluster_near_duplicates(conn, near_duplicate_hash_distance)
    video_near_groups = cluster_video_near_duplicates(conn, near_duplicate_hash_distance)
    return {"exact_groups": exact_groups, "near_groups": near_groups, "video_near_groups": video_near_groups}
