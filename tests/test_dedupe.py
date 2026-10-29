"""Similar-photo grouping and keeper choice, on hand-built rows (no image files needed)."""
from __future__ import annotations

import unittest

import imagehash

from app import dedupe
from app.db import connect


def _hash(bits: int) -> str:
    return f"{bits:016x}"


def _apart(base: int, flips: int, offset: int = 0) -> int:
    """A hash `flips` bits away from `base`, flipping bits starting at `offset`."""
    for i in range(flips):
        base ^= 1 << ((offset + i) % 64)
    return base


class ChainTests(unittest.TestCase):
    def hashes(self, *values: int) -> dict[int, imagehash.ImageHash]:
        return {i: imagehash.hex_to_hash(_hash(v)) for i, v in enumerate(values, 1)}

    def test_a_tight_set_stays_together(self) -> None:
        base = 0x0F0F0F0F0F0F0F0F
        hashes = self.hashes(base, _apart(base, 3), _apart(base, 3, 20))
        self.assertEqual(dedupe._split_chains([1, 2, 3], hashes, 10), [[1, 2, 3]])

    def test_a_chain_is_cut_instead_of_dragging_strangers_in(self) -> None:
        a = 0x0F0F0F0F0F0F0F0F
        b = _apart(a, 6)                 # 6 from a
        c = _apart(b, 6, 6)              # 6 from b, 12 from a
        d = _apart(c, 6, 12)             # 6 from c, 18 from a
        hashes = self.hashes(a, b, c, d)
        self.assertEqual(max(hashes[1] - hashes[i] for i in (2, 3, 4)), 18)
        sets = dedupe._split_chains([1, 2, 3, 4], hashes, 10)
        for members in sets:
            for x in members:
                for y in members:
                    self.assertLessEqual(hashes[x] - hashes[y], 10)
        self.assertGreater(len(sets), 1)
        self.assertEqual(sorted(i for s in sets for i in s), [1, 2, 3, 4])


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        self.next_id = 0

    def add(self, phash: int, w: int = 4000, h: int = 3000, focus: float = 300.0, detail: float = 40.0) -> int:
        self.next_id += 1
        self.conn.execute(
            "INSERT INTO photos (id, path, size_bytes, mtime, sha256, phash, width, height, blur_score, "
            "detail_score, status, indexed_at, media_type) VALUES (?, ?, 1, 0, ?, ?, ?, ?, ?, ?, 'active', 'now', 'photo')",
            (self.next_id, f"p{self.next_id}.jpg", f"sha{self.next_id}", _hash(phash), w, h, focus, detail),
        )
        self.conn.commit()
        return self.next_id

    def groups(self) -> list[tuple[list[int], int]]:
        out = []
        for g in self.conn.execute("SELECT id FROM dup_groups WHERE kind = 'near'").fetchall():
            rows = self.conn.execute(
                "SELECT photo_id, is_keeper FROM dup_group_members WHERE group_id = ?", (g["id"],)
            ).fetchall()
            out.append((sorted(r["photo_id"] for r in rows), next(r["photo_id"] for r in rows if r["is_keeper"])))
        return sorted(out)

    def test_plain_pictures_are_not_called_alike(self) -> None:
        sky = 0x8000000000000000
        a, b = self.add(sky, detail=0.4), self.add(sky, detail=0.5)
        self.assertEqual(dedupe.cluster_near_duplicates(self.conn, 6), 0)
        self.assertEqual(self.groups(), [])
        c, d = self.add(0x0123456789ABCDEF), self.add(_apart(0x0123456789ABCDEF, 2))
        self.assertEqual(dedupe.cluster_near_duplicates(self.conn, 6), 1)
        self.assertEqual([m for m, _ in self.groups()], [[c, d]])
        self.assertNotIn(a, [i for m, _ in self.groups() for i in m])

    def test_crisp_small_copy_beats_a_soft_large_one(self) -> None:
        base = 0x13579BDF02468ACE
        soft_large = self.add(base, 4000, 3000, focus=3.0)
        crisp_small = self.add(_apart(base, 2), 2200, 1650, focus=250.0)
        dedupe.cluster_near_duplicates(self.conn, 6)
        self.assertEqual(self.groups(), [([soft_large, crisp_small], crisp_small)])

    def test_between_equally_sharp_shots_the_larger_wins(self) -> None:
        base = 0x13579BDF02468ACE
        small = self.add(base, 2200, 1650, focus=300.0)
        large = self.add(_apart(base, 1), 4000, 3000, focus=240.0)  # slightly softer, still sharp enough
        dedupe.cluster_near_duplicates(self.conn, 6)
        self.assertEqual(self.groups(), [([small, large], large)])

    def test_between_same_size_shots_the_sharper_wins(self) -> None:
        base = 0x13579BDF02468ACE
        soft, sharp = self.add(base, focus=180.0), self.add(_apart(base, 1), focus=320.0)
        dedupe.cluster_near_duplicates(self.conn, 6)
        self.assertEqual(self.groups(), [([soft, sharp], sharp)])

    def test_a_long_chain_becomes_several_sets(self) -> None:
        a = 0x0F0F0F0F0F0F0F0F
        b = _apart(a, 6)
        c = _apart(b, 6, 6)
        d = _apart(c, 6, 12)
        ids = [self.add(h) for h in (a, b, c, d)]
        dedupe.cluster_near_duplicates(self.conn, 6)
        sets = [m for m, _ in self.groups()]
        self.assertTrue(sets)
        self.assertNotIn(ids, sets)  # never one set of all four


if __name__ == "__main__":
    unittest.main()
