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
    "triage_conflict", "explicit_review_at", "merged_at", "inherited_at", "inherited_from",
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
        # One conflict banner: decisions listed by earlier conflict notes are carried into it
        # instead of stacking a new banner on every further merge
        segments = notes.split("\n---\n") if notes else []
        previous: list[str] = []
        kept: list[str] = []
        for seg in segments:
            if seg.startswith(CONFLICT_NOTE_PREFIX):
                body = seg.split("Previous decisions: ", 1)[-1].rsplit(". Please review again.", 1)[0]
                previous.extend(item.strip() for item in body.split(", ") if item.strip())
            else:
                kept.append(seg)
        items = previous + [
            f"{r['classification']} (photo #{r['image_id']})" for r in sorted(reviewed, key=lambda r: r["id"])
        ]
        items = list(dict.fromkeys(items))
        if items:
            conflict = f"{CONFLICT_NOTE_PREFIX} Previous decisions: {', '.join(items)}. Please review again."
            notes = "\n---\n".join([conflict] + kept)
        classification, classified_at, rule_id = CLASS_UNREVIEWED, None, None
        is_new, acknowledged_at, triage_conflict = 1, None, 1
        # A conflict needs a new explicit review: earlier reviews no longer stand for the merge
        explicit_review_at = None
    else:
        triage_conflict = 0
        explicit_review_at = max((r["explicit_review_at"] for r in rows if r["explicit_review_at"]), default=None)
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
        "explicit_review_at": explicit_review_at,
        "merged_at": min(
            (r["merged_at"] for r in rows if r["merged_at"]),
            default=datetime.now(timezone.utc).isoformat(),
        ),
        # A decision inherited from a permanently purged photo stays inherited through every later
        # coalescence, with each original purged source kept
        # inherited_at is the latest inheritance event: a dissolution may roll back only a cycle
        # that started after it (_ROLLBACK_ALLOWED)
        "inherited_at": max((r["inherited_at"] for r in rows if r["inherited_at"]), default=None),
        "inherited_from": _merge_provenance(r["inherited_from"] for r in rows),
    }


def _merge_provenance(values: Iterable[Optional[str]]) -> Optional[str]:
    items: list[str] = []
    for value in values:
        for item in (value or "").split("; "):
            if item and item not in items:
                items.append(item)
    return "; ".join(items) if items else None


def _capture_observation_triage(cur: sqlite3.Cursor, match_id: int) -> None:
    """Before a physical row starts carrying merged logical state, keep its own triage:

    - obs_*: its original observation, captured once and never overwritten (read-only provenance);
    - rb_*: its state right before the current grouping cycle, captured at the start of each
      cycle; this is what a dissolution rolls back to, so a later cycle never undoes a decision
      the user made after an earlier one."""
    now = datetime.now(timezone.utc).isoformat()
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
        (now, match_id),
    )
    cur.execute(
        """
        UPDATE matches
        SET rb_classification = classification,
            rb_classified_at = classified_at,
            rb_rule_id = auto_classified_by_rule_id,
            rb_notes = notes,
            rb_is_new = is_new,
            rb_acknowledged_at = acknowledged_at,
            rb_inherited_at = inherited_at,
            rb_inherited_from = inherited_from,
            rb_triage_conflict = triage_conflict,
            rb_captured_at = ?
        WHERE id = ? AND rb_captured_at IS NULL
        """,
        (now, match_id),
    )


# A row may roll back to its pre-cycle state (rb_*) unless it inherited a decision from a photo
# permanently purged during this cycle: that is a new permanent event, not part of the reversible
# grouping. Inheritance that already existed before the cycle is part of rb_* and rolls back too.
# The cycle starts when the logical discovery began carrying merged state (merged_at, which travels
# with handovers, so a member that took over the discovery after the purge still keeps it).
_ROLLBACK_ALLOWED = "(inherited_at IS NULL OR inherited_at < COALESCE(merged_at, rb_captured_at))"


def _restore_observation_triage(cur: sqlite3.Cursor, match_id: int) -> None:
    """When a row stops carrying a logical discovery (it becomes an independent discovery again
    after ungrouping), it rolls back to its state right before this grouping cycle, inheritance
    provenance included, unless it inherited a purged photo's decision during this cycle
    (_ROLLBACK_ALLOWED). The original observation (obs_*) stays as provenance."""
    cur.execute(
        f"""
        UPDATE matches
        SET classification = rb_classification,
            classified_at = rb_classified_at,
            -- a domain rule deleted since then cannot be referenced again
            auto_classified_by_rule_id = (SELECT id FROM domain_rules WHERE id = rb_rule_id),
            notes = rb_notes,
            is_new = rb_is_new,
            acknowledged_at = rb_acknowledged_at,
            inherited_at = rb_inherited_at,
            inherited_from = rb_inherited_from,
            -- an unresolved conflict that predates the cycle stays unresolved
            triage_conflict = COALESCE(rb_triage_conflict, 0)
        WHERE id = ? AND rb_captured_at IS NOT NULL AND {_ROLLBACK_ALLOWED}
        """,
        (match_id,),
    )
    _end_cycle(cur, match_id)


def _end_cycle(cur: sqlite3.Cursor, match_id: int) -> None:
    """Closes the grouping cycle of a row that is independent again: the next grouping captures a
    fresh rollback state and needs its own explicit review."""
    cur.execute(
        """
        UPDATE matches
        SET explicit_review_at = NULL, merged_at = NULL,
            rb_classification = NULL, rb_classified_at = NULL, rb_rule_id = NULL,
            rb_notes = NULL, rb_is_new = NULL, rb_acknowledged_at = NULL,
            rb_inherited_at = NULL, rb_inherited_from = NULL, rb_triage_conflict = NULL,
            rb_captured_at = NULL
        WHERE id = ?
        """,
        (match_id,),
    )


def _write_state(cur: sqlite3.Cursor, match_id: int, state: dict[str, object]) -> None:
    _capture_observation_triage(cur, match_id)
    cur.execute(
        f"UPDATE matches SET {', '.join(f'{k} = ?' for k in _LOGICAL_FIELDS)} WHERE id = ?",
        tuple(state[k] for k in _LOGICAL_FIELDS) + (match_id,),
    )


def _write_merge(cur: sqlite3.Cursor, match_id: int, state: dict[str, object], kind: str) -> None:
    """Writes a merged logical state. A validated re-export (LINEAGE) is a permanent identity
    transition, not a reversible grouping: unless the row already belongs to an open grouping
    cycle, it does not open one (no rollback state, no cycle markers)."""
    cur.execute("SELECT rb_captured_at FROM matches WHERE id = ?", (match_id,))
    in_cycle = cur.fetchone()["rb_captured_at"] is not None
    _write_state(cur, match_id, state)
    if kind == FOLD_LINEAGE and not in_cycle:
        _end_cycle(cur, match_id)


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
            _write_merge(cur, survivor["id"], _merged_state(rows, survivor), kind)
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
                _write_merge(cur, head_id, _merged_state([head, survivor], head), kind)
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
    """Before `image_ids` are permanently deleted, keep every logical discovery their photo group
    still needs:

    - a discovery that other photos also observed is handed over to one of those observations,
      with its logical triage (explicit decisions included);
    - a discovery only the purged photo observed, but whose group has surviving members, is
      re-homed to a surviving member (the group was searched through the purged photo).

    Both are marked as inherited (inherited_at / inherited_from), so a later group dissolution
    never "restores" them back to a state that would drop decisions about the purged photo.
    Returns affected image IDs. Does not commit."""
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

    # Logical discoveries of purged photos that no surviving photo observed, but whose photo group
    # has surviving members (e.g. the group was only searched through the purged photo)
    cur.execute(
        """
        SELECT h.id AS hid, h.image_id AS himg, i.photo_group_id AS gid
        FROM matches h JOIN images i ON i.id = h.image_id
        WHERE h.image_id IN (SELECT id FROM _released_images)
          AND h.canonical_match_id IS NULL
          AND i.photo_group_id IS NOT NULL
        """
    )
    unobserved = [r for r in cur.fetchall() if r["hid"] not in by_head]
    survivors: dict[int, Optional[int]] = {}
    for r in unobserved:
        if r["gid"] not in survivors:
            cur.execute(
                """
                SELECT g.id FROM images g JOIN libraries l ON l.id = g.library_id
                WHERE g.photo_group_id = ? AND g.id NOT IN (SELECT id FROM _released_images)
                ORDER BY (g.is_present_on_disk = 1 AND l.enabled = 1 AND l.is_archived = 0) DESC,
                         g.is_primary_representation DESC, g.id ASC
                LIMIT 1
                """,
                (r["gid"],),
            )
            row = cur.fetchone()
            survivors[r["gid"]] = row["id"] if row else None
    cur.execute("DELETE FROM _released_images")

    filenames: dict[int, str] = {}

    def provenance(image_id: int) -> str:
        if image_id not in filenames:
            cur.execute("SELECT filename FROM images WHERE id = ?", (image_id,))
            row = cur.fetchone()
            filenames[image_id] = row["filename"] if row else "unknown"
        return f"photo #{image_id} ({filenames[image_id]}), permanently purged"

    def mark_inherited(match_id: int, from_image: int) -> None:
        # Permanent inheritance: never "restored" away when the group later dissolves
        cur.execute("SELECT inherited_from FROM matches WHERE id = ?", (match_id,))
        earlier = cur.fetchone()["inherited_from"]
        # A new inheritance event, timed after any rollback state captured by this handover
        cur.execute(
            "UPDATE matches SET inherited_at = ?, inherited_from = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), _merge_provenance([earlier, provenance(from_image)]), match_id),
        )

    affected: set[int] = set()
    for hid, children in by_head.items():
        children.sort(key=lambda r: (r["ffirst"] or "", r["fid"]))
        cur.execute("SELECT * FROM matches WHERE id = ?", (hid,))
        head = cur.fetchone()
        _promote(cur, head, children[0]["fid"], [c["fid"] for c in children[1:]])
        mark_inherited(children[0]["fid"], head["image_id"])
        affected.update(c["fimg"] for c in children)

    for r in unobserved:
        survivor = survivors.get(r["gid"])
        if survivor is None:
            continue
        cur.execute("SELECT * FROM matches WHERE id = ?", (r["hid"],))
        head = cur.fetchone()
        cur.execute(
            """
            SELECT id, canonical_match_id FROM matches
            WHERE image_id = ? AND source_kind = ?
              AND COALESCE(page_url, '') = ? AND COALESCE(candidate_image_url, '') = ?
            """,
            (survivor, *_identity(head)),
        )
        existing = cur.fetchone()
        if existing is None:
            # The group's discovery (about the shared source photograph) stays with the group,
            # attributed to the surviving member with explicit inheritance provenance
            cur.execute("UPDATE matches SET image_id = ? WHERE id = ?", (survivor, r["hid"]))
            mark_inherited(r["hid"], r["himg"])
        else:
            target_id = existing["canonical_match_id"] or existing["id"]
            cur.execute("SELECT * FROM matches WHERE id = ?", (target_id,))
            target = cur.fetchone()
            _write_state(cur, target_id, _merged_state([target, head], target))
            mark_inherited(target_id, r["himg"])
        affected.add(survivor)
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

    # A former canonical discovery whose photo is no longer grouped and that no longer represents
    # other observations returns to its own original triage, unless the user explicitly reviewed
    # the logical discovery since it began carrying merged state (merged_at, which travels with
    # handovers) (then that decision stays and the original triage
    # remains available as provenance in obs_*).
    cur.execute(
        """
        SELECT m.id, m.image_id,
               ((m.inherited_at IS NULL OR m.inherited_at < COALESCE(m.merged_at, m.rb_captured_at))  -- _ROLLBACK_ALLOWED
                AND (m.explicit_review_at IS NULL
                     OR m.explicit_review_at < COALESCE(m.merged_at, m.rb_captured_at))) AS restorable
        FROM matches m
        JOIN images i ON i.id = m.image_id
        WHERE m.canonical_match_id IS NULL
          AND m.rb_captured_at IS NOT NULL
          AND i.photo_group_id IS NULL
          -- re-export provenance (LINEAGE) is permanent and never keeps a grouping cycle open
          AND NOT EXISTS (SELECT 1 FROM matches f WHERE f.canonical_match_id = m.id AND f.fold_kind = ?)
        """,
        (FOLD_GROUP,),
    )
    for r in cur.fetchall():
        if r["restorable"]:
            _restore_observation_triage(cur, r["id"])
        else:
            _end_cycle(cur, r["id"])
        affected.add(r["image_id"])
    return affected
