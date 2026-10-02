"""Logical discoveries over physical provider observations (non-destructive coalescence).

Every `matches` row is a physical observation: a provider search of one photo found one web use.
When photo identities become one (photos grouped as representations of one source photograph, or
a validated re-export adopting the lineage of the record it replaced), observations of the same
deterministic identity (source_kind, page_url, candidate_image_url) must surface once. They are
*folded*, never deleted:

- the surviving row (`canonical_match_id IS NULL`) is the logical discovery shown in review and
  counted, and carries the merged logical triage;
- folded rows point to it (`canonical_match_id`), keep their own image_id and their own original
  classification / notes / timestamps as inspectable provenance, and are excluded from review
  lists and counts;
- a row that carries a logical discovery (the canonical row, or a row that received a handover)
  first keeps its own original triage in the obs_* columns (migration 012), so every physical
  observation, canonical or folded, still exposes the decision it had on its own.

Folding is reversible:
- when a group is dissolved or a photo leaves it, its folded observations become independent
  logical discoveries again with their own preserved triage;
- when the photo holding a logical discovery leaves a group (or is purged) while folded
  observations remain in the group, the logical triage is handed over to one of them, so the
  group keeps its discovery and decisions.

Merge rules mirror migration 004 (which stays self-contained, as migrations must not depend on
evolving application code): earliest first_seen_at, latest last_seen_at, all notes kept,
acknowledgement and "not new" state kept, a reviewed classification beats UNREVIEWED. Conflicting
reviewed classifications are never resolved silently: the logical discovery returns to UNREVIEWED,
flagged new, with a note listing every previous decision (each folded observation still holds its
own decision).
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable, Optional

CLASS_UNREVIEWED = "UNREVIEWED"
CONFLICT_NOTE_PREFIX = "[Merged discovery: conflicting decisions]"
FOLD_GROUP = "GROUP"
FOLD_LINEAGE = "LINEAGE"

_LOGICAL_FIELDS = (
    "first_seen_at", "last_seen_at", "scan_session_id", "page_title", "page_score",
    "classification", "classified_at", "auto_classified_by_rule_id", "notes", "is_new", "acknowledged_at",
    "triage_conflict",
)


def _identity(r: sqlite3.Row) -> tuple[str, str, str]:
    return (r["source_kind"], r["page_url"] or "", r["candidate_image_url"] or "")


def _merge_notes(rows: list[sqlite3.Row]) -> Optional[str]:
    seen: list[str] = []
    for r in rows:
        note = (r["notes"] or "").strip()
        if note and note not in seen:
            seen.append(note)
    return "\n---\n".join(seen) if seen else None


def _merged_state(rows: list[sqlite3.Row], survivor: sqlite3.Row) -> dict[str, object]:
    first_seen = min((r["first_seen_at"] for r in rows if r["first_seen_at"]), default=survivor["first_seen_at"])
    latest = max(rows, key=lambda r: (r["last_seen_at"] or "", r["id"]))
    reviewed = [r for r in rows if r["classification"] != CLASS_UNREVIEWED]
    decisions = sorted({r["classification"] for r in reviewed})
    notes = _merge_notes(rows)
    acknowledged = [r["acknowledged_at"] for r in rows if r["acknowledged_at"]]

    # An unresolved conflict carried by any merged discovery stays unresolved: only an explicit
    # classification by the user clears it (MatchRepository.update_classification_and_notes)
    unresolved = any(r["triage_conflict"] for r in rows)
    if len(decisions) > 1 or unresolved:
        if reviewed:
            detail = ", ".join(
                f"{r['classification']} (photo #{r['image_id']})" for r in sorted(reviewed, key=lambda r: r["id"])
            )
            conflict = f"{CONFLICT_NOTE_PREFIX} Previous decisions: {detail}. Please review again."
            notes = f"{conflict}\n---\n{notes}" if notes else conflict
        classification, classified_at, rule_id = CLASS_UNREVIEWED, None, None
        is_new, acknowledged_at, triage_conflict = 1, None, 1
    else:
        triage_conflict = 0
        if decisions:
            same = [r for r in reviewed if r["classification"] == decisions[0]]
            classification = decisions[0]
            classified_at = max((r["classified_at"] or "" for r in same), default="") or None
            # A manual decision (no rule provenance) always wins over rule provenance
            rule_id = (
                None if any(r["auto_classified_by_rule_id"] is None for r in same)
                else same[0]["auto_classified_by_rule_id"]
            )
        else:
            classification, classified_at, rule_id = CLASS_UNREVIEWED, None, None
        is_new = 0 if (reviewed or acknowledged or any(r["is_new"] == 0 for r in rows)) else 1
        acknowledged_at = min(acknowledged) if acknowledged else None

    return {
        "first_seen_at": first_seen,
        "last_seen_at": latest["last_seen_at"],
        "scan_session_id": latest["scan_session_id"],
        "page_title": survivor["page_title"] if survivor["page_title"] is not None else latest["page_title"],
        "page_score": survivor["page_score"] if survivor["page_score"] is not None else latest["page_score"],
        "classification": classification,
        "classified_at": classified_at,
        "auto_classified_by_rule_id": rule_id,
        "notes": notes,
        "is_new": is_new,
        "acknowledged_at": acknowledged_at,
        "triage_conflict": triage_conflict,
    }


def _capture_observation_triage(cur: sqlite3.Cursor, match_id: int) -> None:
    """Before a physical row starts carrying merged logical state, keep its own original triage
    (once) in the obs_* provenance columns."""
    cur.execute(
        """
        UPDATE matches
        SET obs_classification = classification,
            obs_classified_at = classified_at,
            obs_rule_id = auto_classified_by_rule_id,
            obs_notes = notes,
            obs_is_new = is_new,
            obs_acknowledged_at = acknowledged_at,
            obs_captured_at = ?
        WHERE id = ? AND obs_captured_at IS NULL
        """,
        (datetime.now(timezone.utc).isoformat(), match_id),
    )


def _restore_observation_triage(cur: sqlite3.Cursor, match_id: int) -> None:
    """When a row stops carrying a logical discovery (it becomes an independent discovery again
    after ungrouping), it returns to its own original triage."""
    cur.execute(
        """
        UPDATE matches
        SET classification = obs_classification,
            classified_at = obs_classified_at,
            auto_classified_by_rule_id = obs_rule_id,
            notes = obs_notes,
            is_new = obs_is_new,
            acknowledged_at = obs_acknowledged_at,
            triage_conflict = 0,
            obs_classification = NULL, obs_classified_at = NULL, obs_rule_id = NULL,
            obs_notes = NULL, obs_is_new = NULL, obs_acknowledged_at = NULL, obs_captured_at = NULL
        WHERE id = ? AND obs_captured_at IS NOT NULL
        """,
        (match_id,),
    )


def _write_state(cur: sqlite3.Cursor, match_id: int, state: dict[str, object]) -> None:
    _capture_observation_triage(cur, match_id)
    cur.execute(
        f"UPDATE matches SET {', '.join(f'{k} = ?' for k in _LOGICAL_FIELDS)} WHERE id = ?",
        tuple(state[k] for k in _LOGICAL_FIELDS) + (match_id,),
    )


def _fold(cur: sqlite3.Cursor, head_id: int, match_id: int, kind: str, now: str) -> None:
    """Folds a logical discovery (and anything already folded under it) under another one."""
    cur.execute(
        "UPDATE matches SET canonical_match_id = ?, fold_kind = ?, folded_at = ? WHERE id = ?",
        (head_id, kind, now, match_id),
    )
    cur.execute("UPDATE matches SET canonical_match_id = ? WHERE canonical_match_id = ?", (head_id, match_id))


def refresh_match_counts(conn: sqlite3.Connection, image_ids: Iterable[int]) -> None:
    """Recomputes images.match_count / unreviewed_count from logical discoveries only."""
    cur = conn.cursor()
    for image_id in set(image_ids):
        cur.execute(
            """
            UPDATE images
            SET match_count = (
                    SELECT COUNT(*) FROM matches WHERE image_id = ? AND canonical_match_id IS NULL
                ),
                unreviewed_count = (
                    SELECT COUNT(*) FROM matches
                    WHERE image_id = ? AND canonical_match_id IS NULL AND classification = 'UNREVIEWED'
                )
            WHERE id = ?
            """,
            (image_id, image_id, image_id),
        )


def coalesce_discoveries(
    conn: sqlite3.Connection,
    image_ids: Iterable[int],
    target_image_id: Optional[int] = None,
) -> set[int]:
    """Folds duplicate logical discoveries across `image_ids` (no row is deleted).

    With `target_image_id` (validated re-export lineage), the replaced record's logical
    discoveries are moved to the target; where the target already observed the same identity,
    the replaced record's observation is folded under the target's instead (it keeps its own
    image_id as provenance). Returns the affected image IDs. Does not commit.
    """
    ids = sorted(set(image_ids) | ({target_image_id} if target_image_id is not None else set()))
    if not ids:
        return set()
    kind = FOLD_LINEAGE if target_image_id is not None else FOLD_GROUP
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in ids)
    cur.execute(
        f"SELECT * FROM matches WHERE image_id IN ({placeholders}) AND canonical_match_id IS NULL",
        tuple(ids),
    )
    clusters: dict[tuple[str, str, str], list[sqlite3.Row]] = defaultdict(list)
    for r in cur.fetchall():
        clusters[_identity(r)].append(r)

    affected: set[int] = set()
    for identity, rows in clusters.items():
        rows.sort(key=lambda r: (
            target_image_id is not None and r["image_id"] != target_image_id,
            r["first_seen_at"] or "",
            r["id"],
        ))
        survivor = rows[0]
        if len(rows) > 1:
            _write_state(cur, survivor["id"], _merged_state(rows, survivor))
            for other in rows[1:]:
                _fold(cur, survivor["id"], other["id"], kind, now)
            affected.update(r["image_id"] for r in rows)

        if target_image_id is not None and survivor["image_id"] != target_image_id:
            # The target may hold this identity as an observation folded under another member's
            # discovery (unique per image): join that discovery instead of moving the row.
            cur.execute(
                """
                SELECT id, canonical_match_id FROM matches
                WHERE image_id = ? AND source_kind = ?
                  AND COALESCE(page_url, '') = ? AND COALESCE(candidate_image_url, '') = ?
                """,
                (target_image_id, *identity),
            )
            existing = cur.fetchone()
            if existing is None:
                cur.execute("UPDATE matches SET image_id = ? WHERE id = ?", (target_image_id, survivor["id"]))
            else:
                head_id = existing["canonical_match_id"] or existing["id"]
                cur.execute("SELECT * FROM matches WHERE id = ?", (head_id,))
                head = cur.fetchone()
                _write_state(cur, head_id, _merged_state([head, survivor], head))
                _fold(cur, head_id, survivor["id"], kind, now)
                affected.add(head["image_id"])
            affected.update((survivor["image_id"], target_image_id))
    return affected


def coalesce_group_discoveries(conn: sqlite3.Connection, group_id: int) -> set[int]:
    """Folds duplicate logical discoveries across all current members of a photo group."""
    cur = conn.cursor()
    cur.execute("SELECT id FROM images WHERE photo_group_id = ?", (group_id,))
    member_ids = [r["id"] for r in cur.fetchall()]
    if len(member_ids) < 2:
        return set()
    return coalesce_discoveries(conn, member_ids)


def _promote(cur: sqlite3.Cursor, head: sqlite3.Row, new_head_id: int, sibling_ids: list[int]) -> None:
    """Makes `new_head_id` the logical discovery in place of `head`, carrying its logical triage."""
    state = {k: head[k] for k in _LOGICAL_FIELDS}
    cur.execute("SELECT first_seen_at FROM matches WHERE id = ?", (new_head_id,))
    own_first = cur.fetchone()["first_seen_at"]
    if own_first and (not state["first_seen_at"] or own_first < state["first_seen_at"]):
        state["first_seen_at"] = own_first
    cur.execute(
        "UPDATE matches SET canonical_match_id = NULL, fold_kind = NULL, folded_at = NULL WHERE id = ?",
        (new_head_id,),
    )
    _write_state(cur, new_head_id, state)
    for sid in sibling_ids:
        cur.execute("UPDATE matches SET canonical_match_id = ? WHERE id = ?", (new_head_id, sid))


def release_discoveries(conn: sqlite3.Connection, image_ids: Iterable[int]) -> set[int]:
    """Before `image_ids` are permanently deleted: every logical discovery they hold that has
    observations on other photos is handed over to one of those observations (with its logical
    triage), so no other photo loses a discovery it observed. Returns affected image IDs."""
    ids = sorted(set(image_ids))
    if not ids:
        return set()
    cur = conn.cursor()
    # A temp table keeps this independent of SQLite's bound-parameter limit for large libraries
    cur.execute("CREATE TEMP TABLE IF NOT EXISTS _released_images (id INTEGER PRIMARY KEY)")
    cur.execute("DELETE FROM _released_images")
    cur.executemany("INSERT INTO _released_images (id) VALUES (?)", [(i,) for i in ids])
    cur.execute(
        """
        SELECT f.id AS fid, f.image_id AS fimg, f.first_seen_at AS ffirst, h.id AS hid
        FROM matches f JOIN matches h ON f.canonical_match_id = h.id
        WHERE h.image_id IN (SELECT id FROM _released_images)
          AND f.image_id NOT IN (SELECT id FROM _released_images)
        """
    )
    by_head: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for r in cur.fetchall():
        by_head[r["hid"]].append(r)
    cur.execute("DELETE FROM _released_images")
    affected: set[int] = set()
    for hid, children in by_head.items():
        children.sort(key=lambda r: (r["ffirst"] or "", r["fid"]))
        cur.execute("SELECT * FROM matches WHERE id = ?", (hid,))
        head = cur.fetchone()
        _promote(cur, head, children[0]["fid"], [c["fid"] for c in children[1:]])
        affected.update(c["fimg"] for c in children)
    return affected


def reconcile_group_folds(conn: sqlite3.Connection) -> set[int]:
    """Re-establishes folding after group membership changed (photo removed, group dissolved,
    photo detached or purged). Group folds stay only while the observation's photo is the
    logical discovery's photo or in the same group:

    - an observation whose photo is no longer grouped becomes an independent logical discovery
      again, with its own preserved triage;
    - observations still grouped together while the logical discovery's photo left their group
      receive the logical triage (handover), and the group is coalesced again.

    Returns affected image IDs. Does not commit.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT f.id AS fid, f.image_id AS fimg, f.first_seen_at AS ffirst, fi.photo_group_id AS fgrp,
               h.id AS hid, h.image_id AS himg, hi.photo_group_id AS hgrp
        FROM matches f
        JOIN matches h ON f.canonical_match_id = h.id
        JOIN images fi ON fi.id = f.image_id
        JOIN images hi ON hi.id = h.image_id
        WHERE f.fold_kind = ?
        """,
        (FOLD_GROUP,),
    )
    broken: dict[tuple[int, Optional[int]], list[sqlite3.Row]] = defaultdict(list)
    for r in cur.fetchall():
        if r["fimg"] == r["himg"] or (r["fgrp"] is not None and r["fgrp"] == r["hgrp"]):
            continue
        broken[(r["hid"], r["fgrp"])].append(r)

    affected: set[int] = set()
    regroup: set[int] = set()
    for (hid, fgrp), children in broken.items():
        if fgrp is None:
            for c in children:
                cur.execute(
                    "UPDATE matches SET canonical_match_id = NULL, fold_kind = NULL, folded_at = NULL WHERE id = ?",
                    (c["fid"],),
                )
                _restore_observation_triage(cur, c["fid"])
        else:
            children.sort(key=lambda r: (r["ffirst"] or "", r["fid"]))
            cur.execute("SELECT * FROM matches WHERE id = ?", (hid,))
            head = cur.fetchone()
            _promote(cur, head, children[0]["fid"], [c["fid"] for c in children[1:]])
            regroup.add(fgrp)
        affected.update(c["fimg"] for c in children)
        affected.add(children[0]["himg"])

    for gid in regroup:
        affected |= coalesce_group_discoveries(conn, gid)
    return affected
