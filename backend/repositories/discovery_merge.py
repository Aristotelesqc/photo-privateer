"""Coalescence of duplicate discoveries when photo identities become one.

Used when photos are grouped (alternate representations of one source photograph) and when a
validated re-export adopts the discovery lineage of the record it replaced. Rows sharing the
deterministic match identity (source_kind, page_url, candidate_image_url) across the given
images are merged into one survivor, following the same preservation rules as migration 004
(which stays self-contained, as migrations must not depend on evolving application code):

- earliest first_seen_at and latest last_seen_at are kept;
- notes from every row are preserved;
- acknowledgement and "not new" state are preserved;
- a reviewed classification beats UNREVIEWED; identical reviewed classifications merge;
- conflicting reviewed classifications (e.g. APPROVED vs UNAUTHORIZED) are never resolved
  silently: the survivor is reset to UNREVIEWED, flagged new, and its notes record every
  previous decision so the user re-reviews it explicitly.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Iterable, Optional

CLASS_UNREVIEWED = "UNREVIEWED"
CONFLICT_NOTE_PREFIX = "[Merged discovery: conflicting decisions]"


def _merge_notes(rows: list[sqlite3.Row]) -> Optional[str]:
    seen: list[str] = []
    for r in rows:
        note = (r["notes"] or "").strip()
        if note and note not in seen:
            seen.append(note)
    return "\n---\n".join(seen) if seen else None


def coalesce_discoveries(
    conn: sqlite3.Connection,
    image_ids: Iterable[int],
    target_image_id: Optional[int] = None,
) -> int:
    """Merges duplicate discoveries across `image_ids`. Returns the number of rows removed.

    When `target_image_id` is given, every surviving discovery of those images is re-homed to
    it (used to move a replaced record's lineage onto its re-export). Does not commit; callers
    refresh image match counts and commit within their own transaction.
    """
    ids = sorted(set(image_ids) | ({target_image_id} if target_image_id is not None else set()))
    if not ids:
        return 0
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in ids)
    cur.execute(f"SELECT * FROM matches WHERE image_id IN ({placeholders})", tuple(ids))
    identities: dict[tuple[str, str, str], list[sqlite3.Row]] = defaultdict(list)
    for r in cur.fetchall():
        identities[(r["source_kind"], r["page_url"] or "", r["candidate_image_url"] or "")].append(r)

    removed = 0
    for rows in identities.values():
        rows.sort(key=lambda r: (r["first_seen_at"] or "", r["id"]))
        survivor = rows[0]
        others = rows[1:]

        if others:
            first_seen = min(r["first_seen_at"] for r in rows if r["first_seen_at"])
            latest = max(rows, key=lambda r: (r["last_seen_at"] or "", r["id"]))
            reviewed = [r for r in rows if r["classification"] != CLASS_UNREVIEWED]
            decisions = sorted({r["classification"] for r in reviewed})
            notes = _merge_notes(rows)
            acknowledged = [r["acknowledged_at"] for r in rows if r["acknowledged_at"]]

            if len(decisions) > 1:
                # Never pick between incompatible human decisions: require explicit re-review
                detail = ", ".join(
                    f"{r['classification']} (photo #{r['image_id']})"
                    for r in sorted(reviewed, key=lambda r: r["id"])
                )
                conflict = f"{CONFLICT_NOTE_PREFIX} Previous decisions: {detail}. Please review again."
                notes = f"{conflict}\n---\n{notes}" if notes else conflict
                classification, classified_at, rule_id = CLASS_UNREVIEWED, None, None
                is_new, acknowledged_at = 1, None
            else:
                if decisions:
                    same = [r for r in reviewed if r["classification"] == decisions[0]]
                    classification = decisions[0]
                    classified_at = max((r["classified_at"] or "" for r in same), default="") or None
                    # A manual decision (no rule provenance) always wins over rule provenance
                    rule_id = None if any(r["auto_classified_by_rule_id"] is None for r in same) else same[0][
                        "auto_classified_by_rule_id"
                    ]
                else:
                    classification, classified_at, rule_id = CLASS_UNREVIEWED, None, None
                is_new = 0 if (reviewed or acknowledged or any(r["is_new"] == 0 for r in rows)) else 1
                acknowledged_at = min(acknowledged) if acknowledged else None

            cur.execute(
                """
                UPDATE matches
                SET first_seen_at = ?, last_seen_at = ?, scan_session_id = ?,
                    page_title = COALESCE(page_title, ?), page_score = COALESCE(page_score, ?),
                    classification = ?, classified_at = ?, auto_classified_by_rule_id = ?,
                    notes = ?, is_new = ?, acknowledged_at = ?
                WHERE id = ?
                """,
                (
                    first_seen, latest["last_seen_at"], latest["scan_session_id"],
                    latest["page_title"], latest["page_score"],
                    classification, classified_at, rule_id,
                    notes, is_new, acknowledged_at,
                    survivor["id"],
                ),
            )
            other_ids = [r["id"] for r in others]
            cur.execute(
                f"DELETE FROM matches WHERE id IN ({','.join('?' for _ in other_ids)})", tuple(other_ids)
            )
            removed += len(other_ids)

        if target_image_id is not None and survivor["image_id"] != target_image_id:
            cur.execute("UPDATE matches SET image_id = ? WHERE id = ?", (target_image_id, survivor["id"]))

    return removed


def coalesce_group_discoveries(conn: sqlite3.Connection, group_id: int) -> int:
    """Merges duplicate discoveries across all current members of a photo group. Does not commit."""
    cur = conn.cursor()
    cur.execute("SELECT id FROM images WHERE photo_group_id = ?", (group_id,))
    member_ids = [r["id"] for r in cur.fetchall()]
    if len(member_ids) < 2:
        return 0
    return coalesce_discoveries(conn, member_ids)
