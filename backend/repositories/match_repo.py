"""Repository for reverse image search matches."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional
from backend.models import MatchOut
from backend.config import CLASS_UNREVIEWED

# Photo to preview for a discovery: the owning record when present on disk in an active (enabled,
# non-archived) library, the same rule the original-file service applies, otherwise such a member
# of its photo group (primary first), so a discovery rediscovered through a fallback member
# still previews when its original owner is missing. `image_id` stays the provenance owner.
DISPLAY_IMAGE_SQL = """
    COALESCE(
        CASE WHEN i.is_present_on_disk = 1 AND EXISTS (
            SELECT 1 FROM libraries il WHERE il.id = i.library_id AND il.enabled = 1 AND il.is_archived = 0
        ) THEN i.id END,
        (
            SELECT g.id FROM images g
            JOIN libraries gl ON gl.id = g.library_id
            WHERE i.photo_group_id IS NOT NULL
              AND g.photo_group_id = i.photo_group_id
              AND g.is_present_on_disk = 1
              AND gl.enabled = 1 AND gl.is_archived = 0
            ORDER BY g.is_primary_representation DESC, g.id ASC
            LIMIT 1
        ),
        m.image_id
    ) AS display_image_id
"""

# Number of physical observations behind a logical discovery (itself plus folded observations)
OBSERVATION_COUNT_SQL = """
    (1 + (SELECT COUNT(*) FROM matches o WHERE o.canonical_match_id = m.id)) AS observation_count
"""

class MatchRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _row_to_match(self, r: sqlite3.Row) -> MatchOut:
        return MatchOut(
            id=r["id"],
            image_id=r["image_id"],
            scan_session_id=r["scan_session_id"],
            source_kind=r["source_kind"] if ("source_kind" in r.keys() and r["source_kind"]) else "PAGE",
            page_url=r["page_url"],
            page_title=r["page_title"],
            page_score=r["page_score"],
            domain=r["domain"],
            candidate_image_url=r["candidate_image_url"],
            match_type=r["match_type"],
            provider=r["provider"],
            first_seen_at=r["first_seen_at"],
            last_seen_at=r["last_seen_at"],
            is_new=bool(r["is_new"]),
            acknowledged_at=r["acknowledged_at"] if "acknowledged_at" in r.keys() else None,
            classification=r["classification"],
            classified_at=r["classified_at"],
            auto_classified_by_rule_id=r["auto_classified_by_rule_id"],
            notes=r["notes"],
            image_filename=r["filename"] if "filename" in r.keys() else None,
            display_image_id=(
                r["display_image_id"] if "display_image_id" in r.keys() and r["display_image_id"] else r["image_id"]
            ),
            image_thumbnail_url=(
                f"/api/photos/{r['display_image_id'] if 'display_image_id' in r.keys() and r['display_image_id'] else r['image_id']}/thumbnail"
            ),
            image_project=r["project"] if "project" in r.keys() else None,
            canonical_match_id=r["canonical_match_id"] if "canonical_match_id" in r.keys() else None,
            observation_count=r["observation_count"] if "observation_count" in r.keys() else 1,
            observed_classification=(
                r["obs_classification"] if "obs_captured_at" in r.keys() and r["obs_captured_at"] else r["classification"]
            ),
            observed_notes=(
                r["obs_notes"] if "obs_captured_at" in r.keys() and r["obs_captured_at"] else r["notes"]
            ),
            observed_classified_at=(
                r["obs_classified_at"] if "obs_captured_at" in r.keys() and r["obs_captured_at"] else r["classified_at"]
            ),
            observed_rule_id=(
                r["obs_rule_id"] if "obs_captured_at" in r.keys() and r["obs_captured_at"]
                else r["auto_classified_by_rule_id"]
            ),
            triage_conflict=bool(r["triage_conflict"]) if "triage_conflict" in r.keys() else False,
            explicit_review_at=r["explicit_review_at"] if "explicit_review_at" in r.keys() else None,
            inherited_from=r["inherited_from"] if "inherited_from" in r.keys() else None,
        )

    def get_by_id(self, match_id: int) -> Optional[MatchOut]:
        cur = self.conn.cursor()
        cur.execute(f"""
            SELECT m.*, i.filename, i.project, {DISPLAY_IMAGE_SQL}, {OBSERVATION_COUNT_SQL}
            FROM matches m
            LEFT JOIN images i ON m.image_id = i.id
            WHERE m.id = ?
        """, (match_id,))
        r = cur.fetchone()
        return self._row_to_match(r) if r else None

    def list_matches(
        self,
        image_id: Optional[int] = None,
        project: Optional[str] = None,
        classification: Optional[str] = None,
        is_new_only: bool = False,
        domain: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "last_seen_at",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MatchOut], int]:
        # Logical discoveries only: observations folded into another discovery are provenance
        where_clauses = ["m.canonical_match_id IS NULL"]
        params: list[object] = []

        if image_id is not None:
            # Group-aware: a grouped photo shares one web search with its group, so its
            # discoveries are those recorded against any member of the group.
            where_clauses.append("""
                m.image_id IN (
                    SELECT g.id FROM images g
                    WHERE g.id = ?
                       OR g.photo_group_id = (SELECT photo_group_id FROM images WHERE id = ?)
                )
            """)
            params.extend([image_id, image_id])

        if project:
            # Group-aware: a discovery belongs to a project when its owner or any current member
            # of the owner's photo group does (EXISTS keeps each discovery listed once)
            group_members = """
                SELECT 1 FROM images gi
                WHERE (gi.id = m.image_id
                       OR (i.photo_group_id IS NOT NULL AND gi.photo_group_id = i.photo_group_id))
            """
            if project == "__unassigned__":
                where_clauses.append(f"EXISTS ({group_members} AND (gi.project IS NULL OR gi.project = ''))")
            else:
                where_clauses.append(f"EXISTS ({group_members} AND gi.project = ?)")
                params.append(project)

        if classification:
            where_clauses.append("m.classification = ?")
            params.append(classification)

        if is_new_only:
            where_clauses.append("m.is_new = 1")

        if domain:
            where_clauses.append("m.domain LIKE ?")
            params.append(f"%{domain}%")

        if search:
            where_clauses.append("(m.page_title LIKE ? OR m.page_url LIKE ? OR m.domain LIKE ?)")
            term = f"%{search}%"
            params.extend([term, term, term])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Total count
        cur = self.conn.cursor()
        cur.execute(f"""
            SELECT COUNT(*)
            FROM matches m
            LEFT JOIN images i ON m.image_id = i.id
            {where_sql}
        """, tuple(params))
        total = cur.fetchone()[0]

        # Allowed sorts
        allowed_sorts = {
            "last_seen_at": "m.last_seen_at",
            "first_seen_at": "m.first_seen_at",
            "domain": "m.domain",
            "page_title": "m.page_title",
            "classification": "m.classification",
            "match_type": "m.match_type",
        }
        order_col = allowed_sorts.get(sort_by, "m.last_seen_at")
        direction = "ASC" if sort_dir.lower() == "asc" else "DESC"

        data_params = list(params)
        data_params.extend([limit, offset])
        cur.execute(f"""
            SELECT m.*, i.filename, i.project, {DISPLAY_IMAGE_SQL}, {OBSERVATION_COUNT_SQL}
            FROM matches m
            LEFT JOIN images i ON m.image_id = i.id
            {where_sql}
            ORDER BY {order_col} {direction}
            LIMIT ? OFFSET ?
        """, tuple(data_params))
        rows = cur.fetchall()
        return [self._row_to_match(r) for r in rows], total

    def list_observations(self, match_id: int) -> list[MatchOut]:
        """Returns the physical observations behind a logical discovery: the discovery's own row
        first, then observations folded into it (each with its own photo and original triage)."""
        cur = self.conn.cursor()
        cur.execute("SELECT COALESCE(canonical_match_id, id) FROM matches WHERE id = ?", (match_id,))
        row = cur.fetchone()
        if not row:
            return []
        logical_id = row[0]
        cur.execute(f"""
            SELECT m.*, i.filename, i.project, {DISPLAY_IMAGE_SQL}
            FROM matches m
            LEFT JOIN images i ON m.image_id = i.id
            WHERE m.id = ? OR m.canonical_match_id = ?
            ORDER BY (m.id = ?) DESC, m.first_seen_at ASC, m.id ASC
        """, (logical_id, logical_id, logical_id))
        return [self._row_to_match(r) for r in cur.fetchall()]

    def upsert_match(
        self,
        image_id: int,
        scan_session_id: Optional[int],
        domain: str,
        match_type: str,
        provider: str,
        source_kind: str = "PAGE",
        page_url: Optional[str] = None,
        page_title: Optional[str] = None,
        page_score: Optional[float] = None,
        candidate_image_url: Optional[str] = None,
        default_classification: str = CLASS_UNREVIEWED,
        rule_id: Optional[int] = None,
    ) -> tuple[MatchOut, bool]:
        """Upsert a match. Preserves prior classification, human notes, and review status if known."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()

        # Check existing match using deterministic identity that works even with NULL page_url or candidate_image_url.
        # Group-aware: members of a photo group are representations of one source photograph, so a
        # discovery already recorded against any current member (e.g. a previous primary, or the
        # member scanned when the preferred one was unavailable) is the same logical discovery and
        # is updated in place, preserving its triage, instead of being duplicated. Observations
        # folded into a logical discovery resolve to it (canonical_match_id).
        cur.execute("""
            SELECT id, image_id, canonical_match_id
            FROM matches
            WHERE image_id IN (
                    SELECT g.id FROM images g
                    WHERE g.id = ?
                       OR g.photo_group_id = (SELECT photo_group_id FROM images WHERE id = ?)
                  )
              AND source_kind = ?
              AND COALESCE(page_url, '') = COALESCE(?, '')
              AND COALESCE(candidate_image_url, '') = COALESCE(?, '')
            ORDER BY (image_id = ?) DESC, (canonical_match_id IS NULL) DESC, id ASC
            LIMIT 1
        """, (image_id, image_id, source_kind, page_url, candidate_image_url, image_id))
        found = cur.fetchone()
        existing = None
        if found:
            logical_id = found["canonical_match_id"] or found["id"]
            if found["image_id"] == image_id and found["canonical_match_id"] is not None:
                # Keep the searched photo's own folded observation current as provenance
                cur.execute(
                    "UPDATE matches SET last_seen_at = ?, scan_session_id = ? WHERE id = ?",
                    (now, scan_session_id, found["id"]),
                )
            elif found["image_id"] != image_id:
                # The provider physically searched this photo and returned a web use its group
                # already knows: record this photo's own observation, folded into the group's
                # logical discovery, so the fact survives ungrouping or purging the other member.
                cur.execute("""
                    INSERT INTO matches (
                        image_id, scan_session_id, source_kind, page_url, page_title, page_score,
                        domain, candidate_image_url, match_type, provider,
                        first_seen_at, last_seen_at, is_new, classification,
                        classified_at, auto_classified_by_rule_id, notes,
                        canonical_match_id, fold_kind, folded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, NULL, ?, 'GROUP', ?)
                """, (
                    image_id, scan_session_id, source_kind, page_url, page_title, page_score,
                    domain, candidate_image_url, match_type, provider,
                    now, now, default_classification,
                    now if default_classification != CLASS_UNREVIEWED else None,
                    rule_id, logical_id, now,
                ))
            cur.execute("""
                SELECT id, classification, notes, auto_classified_by_rule_id, is_new, acknowledged_at
                FROM matches WHERE id = ?
            """, (logical_id,))
            existing = cur.fetchone()

        if existing:
            # Rediscovery: preserve user's human classification and notes!
            # If already classified or acknowledged, do not re-flag as new.
            is_new = 0 if (existing["classification"] != CLASS_UNREVIEWED or existing["acknowledged_at"] is not None) else existing["is_new"]
            cur.execute("""
                UPDATE matches
                SET last_seen_at = ?,
                    scan_session_id = ?,
                    page_title = COALESCE(?, page_title),
                    page_score = COALESCE(?, page_score),
                    is_new = ?
                WHERE id = ?
            """, (now, scan_session_id, page_title, page_score, is_new, existing["id"]))
            return self.get_by_id(existing["id"]), False  # type: ignore

        # Genuinely new match
        cur.execute("""
            INSERT INTO matches (
                image_id, scan_session_id, source_kind, page_url, page_title, page_score,
                domain, candidate_image_url, match_type, provider,
                first_seen_at, last_seen_at, is_new, classification,
                classified_at, auto_classified_by_rule_id, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, NULL)
        """, (
            image_id, scan_session_id, source_kind, page_url, page_title, page_score,
            domain, candidate_image_url, match_type, provider,
            now, now, default_classification,
            now if default_classification != CLASS_UNREVIEWED else None,
            rule_id
        ))
        new_id = cur.lastrowid
        return self.get_by_id(new_id), True  # type: ignore

    def update_classification_and_notes(
        self,
        match_id: int,
        classification: Optional[str] = None,
        notes: Optional[str] = None,
        clear_notes: bool = False,
        acknowledged: Optional[bool] = None,
    ) -> Optional[MatchOut]:
        cur = self.conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        fields = []
        params: list[object] = []

        if classification is not None:
            fields.append("classification = ?")
            params.append(classification)
            fields.append("classified_at = ?")
            params.append(now)
            # Manual user classification clears auto_classified_by_rule_id provenance
            fields.append("auto_classified_by_rule_id = NULL")
            # An explicit decision by the user resolves a merged triage conflict
            fields.append("triage_conflict = 0")
            if classification != CLASS_UNREVIEWED:
                fields.append("is_new = 0")
                fields.append("acknowledged_at = COALESCE(acknowledged_at, ?)")
                params.append(now)

        if acknowledged is not None and acknowledged:
            fields.append("is_new = 0")
            fields.append("acknowledged_at = COALESCE(acknowledged_at, ?)")
            params.append(now)

        if clear_notes:
            fields.append("notes = NULL")
        elif notes is not None:
            fields.append("notes = ?")
            params.append(notes)

        if not fields:
            return self.get_by_id(match_id)

        # Any review action by the user counts as explicit, even when it re-selects the value
        # already displayed (values alone cannot tell an explicit review from an automatic merge)
        fields.append("explicit_review_at = ?")
        params.append(now)

        params.append(match_id)
        cur.execute(f"UPDATE matches SET {', '.join(fields)} WHERE id = ?", tuple(params))

        # Retrieve image_id to refresh image match counts
        cur.execute("SELECT image_id FROM matches WHERE id = ?", (match_id,))
        r = cur.fetchone()
        if r:
            image_id = r["image_id"]
            cur.execute("""
                UPDATE images
                SET unreviewed_count = (
                    SELECT COUNT(*) FROM matches
                    WHERE image_id = ? AND canonical_match_id IS NULL AND classification = 'UNREVIEWED'
                ),
                match_count = (
                    SELECT COUNT(*) FROM matches WHERE image_id = ? AND canonical_match_id IS NULL
                )
                WHERE id = ?
            """, (image_id, image_id, image_id))

        self.conn.commit()
        return self.get_by_id(match_id)

    def apply_rule_to_unreviewed_matches(self, domain: str, classification: str, rule_id: int) -> int:
        """Applies a newly created domain rule to existing UNREVIEWED matches for that domain and its subdomains."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        # Matches exact domain OR subdomains (e.g. blog.foo.com for rule foo.com)
        cur.execute("""
            UPDATE matches
            SET classification = ?,
                classified_at = ?,
                auto_classified_by_rule_id = ?
            WHERE (domain = ? OR domain LIKE '%.' || ?) 
              AND classification = 'UNREVIEWED'
              AND canonical_match_id IS NULL
              AND triage_conflict = 0
        """, (classification, now, rule_id, domain, domain))
        updated_count = cur.rowcount

        # Refresh affected images' match counts
        cur.execute("""
            UPDATE images
            SET unreviewed_count = (
                SELECT COUNT(*) FROM matches
                WHERE matches.image_id = images.id AND canonical_match_id IS NULL AND classification = 'UNREVIEWED'
            )
            WHERE id IN (SELECT DISTINCT image_id FROM matches WHERE domain = ? OR domain LIKE '%.' || ?)
        """, (domain, domain))
        self.conn.commit()
        return updated_count

    def cascade_rule_update(self, rule_id: int, new_classification: str) -> int:
        """Updates classification on all matches that were auto-classified by this rule,
        preserving matches that were manually classified by user (auto_classified_by_rule_id IS NULL)."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE matches
            SET classification = ?,
                classified_at = ?
            WHERE auto_classified_by_rule_id = ?
              AND canonical_match_id IS NULL
        """, (new_classification, now, rule_id))
        updated = cur.rowcount

        # Refresh affected images
        cur.execute("""
            UPDATE images
            SET unreviewed_count = (
                SELECT COUNT(*) FROM matches
                WHERE matches.image_id = images.id AND canonical_match_id IS NULL AND classification = 'UNREVIEWED'
            )
            WHERE id IN (SELECT DISTINCT image_id FROM matches WHERE auto_classified_by_rule_id = ?)
        """, (rule_id,))
        self.conn.commit()
        return updated

