"""Repository for reverse image search matches."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional
from backend.models import MatchOut
from backend.config import CLASS_UNREVIEWED

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
            image_thumbnail_url=f"/api/photos/{r['image_id']}/thumbnail" if "image_id" in r.keys() else None,
            image_project=r["project"] if "project" in r.keys() else None,
        )

    def get_by_id(self, match_id: int) -> Optional[MatchOut]:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT m.*, i.filename, i.project
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
        where_clauses = []
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
            if project == "__unassigned__":
                where_clauses.append("(i.project IS NULL OR i.project = '')")
            else:
                where_clauses.append("i.project = ?")
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
            SELECT m.*, i.filename, i.project
            FROM matches m
            LEFT JOIN images i ON m.image_id = i.id
            {where_sql}
            ORDER BY {order_col} {direction}
            LIMIT ? OFFSET ?
        """, tuple(data_params))
        rows = cur.fetchall()
        return [self._row_to_match(r) for r in rows], total

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
        # is updated in place, preserving its triage, instead of being duplicated.
        cur.execute("""
            SELECT id, classification, notes, auto_classified_by_rule_id, is_new, acknowledged_at
            FROM matches
            WHERE image_id IN (
                    SELECT g.id FROM images g
                    WHERE g.id = ?
                       OR g.photo_group_id = (SELECT photo_group_id FROM images WHERE id = ?)
                  )
              AND source_kind = ?
              AND COALESCE(page_url, '') = COALESCE(?, '')
              AND COALESCE(candidate_image_url, '') = COALESCE(?, '')
            ORDER BY (image_id = ?) DESC, id ASC
            LIMIT 1
        """, (image_id, image_id, source_kind, page_url, candidate_image_url, image_id))
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
                    SELECT COUNT(*) FROM matches WHERE image_id = ? AND classification = 'UNREVIEWED'
                ),
                match_count = (
                    SELECT COUNT(*) FROM matches WHERE image_id = ?
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
        """, (classification, now, rule_id, domain, domain))
        updated_count = cur.rowcount

        # Refresh affected images' match counts
        cur.execute("""
            UPDATE images
            SET unreviewed_count = (
                SELECT COUNT(*) FROM matches WHERE matches.image_id = images.id AND classification = 'UNREVIEWED'
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
        """, (new_classification, now, rule_id))
        updated = cur.rowcount

        # Refresh affected images
        cur.execute("""
            UPDATE images
            SET unreviewed_count = (
                SELECT COUNT(*) FROM matches WHERE matches.image_id = images.id AND classification = 'UNREVIEWED'
            )
            WHERE id IN (SELECT DISTINCT image_id FROM matches WHERE auto_classified_by_rule_id = ?)
        """, (rule_id,))
        self.conn.commit()
        return updated

