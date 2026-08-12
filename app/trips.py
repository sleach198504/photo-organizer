from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone

log = logging.getLogger(__name__)

# "Home" is the largest cluster of GPS points among all active photos - grid cells
# this many decimal degrees wide (~1.1km at this precision), so nearby-but-not-
# identical coordinates (GPS jitter) still count as the same place.
HOME_GRID_PRECISION = 2

AWAY_DISTANCE_MILES = 20.0
MAX_DAY_GAP = 2  # away-dates within this many days of each other count as one trip

# Day-trip detection is a much noisier signal than multi-day trip detection - a
# multi-day stretch away from home rarely happens by accident, but a single day
# could just be a regional errand. Requiring more photos before calling it a
# deliberate "day trip" is the main defense against that noise.
MIN_VACATION_PHOTOS = 3
MIN_DAYTRIP_PHOTOS = 8


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_miles = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * earth_radius_miles * math.asin(math.sqrt(a))


def detect_home_location(conn) -> tuple[float, float] | None:
    rows = conn.execute(
        "SELECT gps_lat, gps_lon FROM photos WHERE status = 'active' "
        "AND gps_lat IS NOT NULL AND gps_lon IS NOT NULL"
    ).fetchall()
    if not rows:
        return None

    buckets: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for row in rows:
        key = (round(row["gps_lat"], HOME_GRID_PRECISION), round(row["gps_lon"], HOME_GRID_PRECISION))
        buckets.setdefault(key, []).append((row["gps_lat"], row["gps_lon"]))

    largest = max(buckets.values(), key=len)
    lat = sum(p[0] for p in largest) / len(largest)
    lon = sum(p[1] for p in largest) / len(largest)
    return lat, lon


def _photo_date(row) -> date:
    if row["taken_at"]:
        try:
            return datetime.fromisoformat(row["taken_at"]).date()
        except ValueError:
            pass
    return datetime.fromtimestamp(row["mtime"]).date()


def _place_name(result: dict) -> str:
    name = (result.get("name") or "").strip()
    admin1 = (result.get("admin1") or "").strip()
    if name and admin1:
        return f"{name}, {admin1}"
    return name or admin1 or "Unknown Location"


def run_trip_detection(conn) -> dict:
    """Recomputes trip/day-trip candidates from scratch each time it's called
    (cheap - it's just grouping and distance math, not machine learning). Already-
    'ignored' candidates are preserved across recomputation and never silently
    reappear; 'pending' ones are refreshed or dropped if they no longer match."""
    home = detect_home_location(conn)
    if home is None:
        return {"vacations": 0, "day_trips": 0, "skipped": "no photos with GPS data"}
    home_lat, home_lon = home

    rows = conn.execute(
        "SELECT id, gps_lat, gps_lon, taken_at, mtime FROM photos "
        "WHERE status = 'active' AND gps_lat IS NOT NULL AND gps_lon IS NOT NULL"
    ).fetchall()

    away_by_date: dict[date, list] = {}
    for row in rows:
        distance = haversine_miles(home_lat, home_lon, row["gps_lat"], row["gps_lon"])
        if distance < AWAY_DISTANCE_MILES:
            continue
        away_by_date.setdefault(_photo_date(row), []).append(row)

    if not away_by_date:
        return {"vacations": 0, "day_trips": 0}

    sorted_dates = sorted(away_by_date.keys())
    runs: list[list[date]] = [[sorted_dates[0]]]
    for d in sorted_dates[1:]:
        if (d - runs[-1][-1]).days <= MAX_DAY_GAP:
            runs[-1].append(d)
        else:
            runs.append([d])

    candidates = []
    for run in runs:
        members = [row for d in run for row in away_by_date[d]]
        kind = "vacation" if len(run) > 1 else "day_trip"
        min_photos = MIN_VACATION_PHOTOS if kind == "vacation" else MIN_DAYTRIP_PHOTOS
        if len(members) < min_photos:
            continue
        candidates.append((kind, run[0], run[-1], members))

    if not candidates:
        return {"vacations": 0, "day_trips": 0}

    # One batched reverse-geocode call for every candidate's centroid - each call to
    # this library has several seconds of fixed startup overhead regardless of batch
    # size, so doing it once here instead of once per candidate matters a lot.
    import reverse_geocoder as rg

    centroids = [
        (
            sum(m["gps_lat"] for m in members) / len(members),
            sum(m["gps_lon"] for m in members) / len(members),
        )
        for _, _, _, members in candidates
    ]
    place_results = rg.search(centroids)

    now = datetime.now(timezone.utc).isoformat()
    stats = {"vacations": 0, "day_trips": 0}
    seen_keys = set()

    for (kind, start, end, members), (lat, lon), place in zip(candidates, centroids, place_results):
        place_name = _place_name(place)
        suggested_name = f"{start.year} {place_name}" if kind == "vacation" else f"{start.isoformat()} {place_name}"
        start_str, end_str = start.isoformat(), end.isoformat()
        seen_keys.add((kind, start_str, end_str))

        existing = conn.execute(
            "SELECT id FROM trip_candidates WHERE kind = ? AND start_date = ? AND end_date = ?",
            (kind, start_str, end_str),
        ).fetchone()
        if existing:
            trip_id = existing["id"]
            conn.execute(
                "UPDATE trip_candidates SET suggested_name = ?, centroid_lat = ?, centroid_lon = ? WHERE id = ?",
                (suggested_name, lat, lon, trip_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO trip_candidates "
                "(kind, start_date, end_date, suggested_name, status, centroid_lat, centroid_lon, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
                (kind, start_str, end_str, suggested_name, lat, lon, now),
            )
            trip_id = cur.lastrowid

        conn.execute("DELETE FROM trip_candidate_members WHERE trip_id = ?", (trip_id,))
        for member in members:
            conn.execute(
                "INSERT OR IGNORE INTO trip_candidate_members (trip_id, photo_id) VALUES (?, ?)",
                (trip_id, member["id"]),
            )
        stats["vacations" if kind == "vacation" else "day_trips"] += 1

    # Pending candidates from a previous run that no longer match anything detected
    # this time are stale - remove them. Ignored ones are left alone regardless, so
    # a dismissal is never silently undone by re-running detection.
    stale = conn.execute(
        "SELECT id, kind, start_date, end_date FROM trip_candidates WHERE status = 'pending'"
    ).fetchall()
    for row in stale:
        if (row["kind"], row["start_date"], row["end_date"]) not in seen_keys:
            conn.execute("DELETE FROM trip_candidates WHERE id = ?", (row["id"],))

    conn.commit()
    return stats


def get_trip_candidates(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM trip_candidates WHERE status = 'pending' ORDER BY start_date DESC"
    ).fetchall()
    results = []
    for row in rows:
        count = conn.execute(
            "SELECT COUNT(*) c FROM trip_candidate_members WHERE trip_id = ?", (row["id"],)
        ).fetchone()["c"]
        # media_type comes along here too - trip membership is GPS/date-based
        # with no media_type filter, so a video can legitimately end up as one
        # of the samples and needs a video-aware thumbnail, not a plain <img>.
        samples = [
            {"id": r["photo_id"], "media_type": r["media_type"]}
            for r in conn.execute(
                """
                SELECT tcm.photo_id AS photo_id, p.media_type AS media_type
                FROM trip_candidate_members tcm
                JOIN photos p ON p.id = tcm.photo_id
                WHERE tcm.trip_id = ? LIMIT 4
                """,
                (row["id"],),
            )
        ]
        results.append({**dict(row), "photo_count": count, "sample_photos": samples})
    return results


def set_trip_name(conn, trip_id: int, name: str) -> None:
    conn.execute("UPDATE trip_candidates SET custom_name = ? WHERE id = ?", (name.strip() or None, trip_id))
    conn.commit()


def ignore_trip(conn, trip_id: int) -> None:
    conn.execute("UPDATE trip_candidates SET status = 'ignored' WHERE id = ?", (trip_id,))
    conn.commit()


def get_trip_folder_for_photo(conn, photo_id: int) -> str | None:
    """Returns the folder name ('Trips/<name>' or 'Day Trips/<name>') a photo
    should be organized into, or None if it's not part of any confirmed trip."""
    row = conn.execute(
        """
        SELECT tc.kind, COALESCE(tc.custom_name, tc.suggested_name) AS name
        FROM trip_candidate_members tcm
        JOIN trip_candidates tc ON tc.id = tcm.trip_id
        WHERE tcm.photo_id = ? AND tc.status = 'pending'
        """,
        (photo_id,),
    ).fetchone()
    if not row:
        return None
    top = "Trips" if row["kind"] == "vacation" else "Day Trips"
    return f"{top}/{row['name']}"
