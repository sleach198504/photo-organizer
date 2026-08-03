from __future__ import annotations

import numpy as np


def search_library(conn, backend, query: str, top_k: int = 60) -> list[dict]:
    """Ranks active photos and videos by CLIP text-image relevance against a
    free-text query. Uses backend.match_probabilities (a paired softmax against
    an explicit negation of the query, per CLIP's own zero-shot methodology) rather
    than a raw cosine-similarity top-K - see match_probabilities' docstring for why
    a bare top-K can't tell "genuinely relevant" from "merely the least-bad guess."
    Anything at or below 50% - i.e. the query lost its own paired comparison - is
    dropped, so a query with nothing real to match against can correctly return
    zero results instead of always padding out to top_k. Photos are scored
    directly off their stored embedding; videos are scored by their single
    best-matching sampled frame (not an average across the whole clip), so a short
    relevant moment in a longer video isn't diluted - that best frame's
    offset_seconds is returned too, to jump playback straight to it. Returns
    [{id, media_type, score, offset_seconds}, ...] sorted best-first - callers
    fetch the full photo rows themselves, same pattern as the rest of this app's
    list views."""
    results: list[dict] = []

    photo_rows = conn.execute(
        "SELECT id, clip_embedding FROM photos "
        "WHERE status = 'active' AND media_type = 'photo' AND clip_embedding IS NOT NULL"
    ).fetchall()
    if photo_rows:
        ids = [row["id"] for row in photo_rows]
        matrix = np.stack([np.frombuffer(row["clip_embedding"], dtype=np.float32) for row in photo_rows])
        probs = backend.match_probabilities(query, matrix)
        results.extend(
            {"id": ids[i], "media_type": "photo", "score": float(probs[i]), "offset_seconds": None}
            for i in range(len(ids))
            if probs[i] > 0.5
        )

    frame_rows = conn.execute(
        """
        SELECT vfe.photo_id, vfe.offset_seconds, vfe.embedding
        FROM video_frame_embeddings vfe
        JOIN photos p ON p.id = vfe.photo_id
        WHERE p.status = 'active'
        """
    ).fetchall()
    if frame_rows:
        photo_ids = [row["photo_id"] for row in frame_rows]
        offsets = [row["offset_seconds"] for row in frame_rows]
        matrix = np.stack([np.frombuffer(row["embedding"], dtype=np.float32) for row in frame_rows])
        probs = backend.match_probabilities(query, matrix)

        best_by_video: dict[int, tuple[float, float]] = {}
        for photo_id, offset, prob in zip(photo_ids, offsets, probs):
            prob = float(prob)
            if prob <= 0.5:
                continue
            current = best_by_video.get(photo_id)
            if current is None or prob > current[0]:
                best_by_video[photo_id] = (prob, offset)
        results.extend(
            {"id": photo_id, "media_type": "video", "score": prob, "offset_seconds": offset}
            for photo_id, (prob, offset) in best_by_video.items()
        )

    results.sort(key=lambda r: -r["score"])
    return results[:top_k]
