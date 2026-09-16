"""Repository for photo groups and representation deduplication candidates."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Set, Tuple

from backend.models import (
    PhotoGroupOut,
    GroupCandidatePairOut,
    ImageOut,
)
from backend.repositories.image_repo import ImageRepository
from backend.services.perceptual import hamming_distance, DHASH_CANDIDATE_THRESHOLD


class PhotoGroupNotFoundError(LookupError):
    pass


class PhotoGroupRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.image_repo = ImageRepository(conn)

    def get_preferred_image_id(self, group_id: int) -> Optional[int]:
        """Returns the preferred image ID for a group in O(1) without loading images."""
        cur = self.conn.cursor()
        cur.execute("SELECT preferred_image_id FROM photo_groups WHERE id = ?", (group_id,))
        row = cur.fetchone()
        return row["preferred_image_id"] if row else None

    def _row_to_group(self, r: sqlite3.Row, images: Optional[List[ImageOut]] = None) -> PhotoGroupOut:
        return PhotoGroupOut(
            id=r["id"],
            name=r["name"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            preferred_image_id=r["preferred_image_id"],
            notes=r["notes"],
            images=images if images is not None else [],
        )

    def get_group(self, group_id: int) -> Optional[PhotoGroupOut]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM photo_groups WHERE id = ?", (group_id,))
        row = cur.fetchone()
        if not row:
            return None
        images = self.image_repo.get_images_for_group(group_id)
        return self._row_to_group(row, images)

    def list_groups(self) -> List[PhotoGroupOut]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM photo_groups ORDER BY updated_at DESC, id DESC")
        rows = cur.fetchall()
        result = []
        for row in rows:
            images = self.image_repo.get_images_for_group(row["id"])
            result.append(self._row_to_group(row, images))
        return result

    def create_group(
        self,
        image_ids: List[int],
        preferred_image_id: Optional[int] = None,
        name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> PhotoGroupOut:
        unique_ids = list(dict.fromkeys(image_ids))
        if len(unique_ids) < 2:
            raise ValueError("A photo group requires at least two distinct images.")

        if preferred_image_id is None or preferred_image_id not in unique_ids:
            preferred_image_id = unique_ids[0]

        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()

        # Validate that all requested image IDs exist and are not already grouped
        placeholders = ",".join("?" for _ in unique_ids)
        cur.execute(f"SELECT id, photo_group_id FROM images WHERE id IN ({placeholders})", tuple(unique_ids))
        existing_rows = cur.fetchall()
        if len(existing_rows) != len(unique_ids):
            raise ValueError("One or more images do not exist.")
        for r in existing_rows:
            if r["photo_group_id"] is not None:
                raise ValueError(f"Image #{r['id']} already belongs to a photo group.")

        try:
            cur.execute(
                """
                INSERT INTO photo_groups (name, created_at, updated_at, preferred_image_id, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, now, now, preferred_image_id, notes),
            )
            group_id = cur.lastrowid
            assert group_id is not None

            # Assign images to the new group conditionally
            for img_id in unique_ids:
                is_primary = 1 if img_id == preferred_image_id else 0
                cur.execute(
                    """
                    UPDATE images
                    SET photo_group_id = ?, is_primary_representation = ?
                    WHERE id = ? AND photo_group_id IS NULL
                    """,
                    (group_id, is_primary, img_id),
                )
                if cur.rowcount != 1:
                    self.conn.rollback()
                    raise ValueError(f"Image #{img_id} was concurrently modified or already belongs to a group.")

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return self.get_group(group_id)  # type: ignore

    def set_preferred_image(self, group_id: int, image_id: int) -> PhotoGroupOut:
        group = self.get_group(group_id)
        if not group:
            raise PhotoGroupNotFoundError(f"Photo group #{group_id} not found.")

        member_ids = [img.id for img in group.images]
        if image_id not in member_ids:
            raise ValueError(f"Image #{image_id} is not a member of group #{group_id}.")

        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE photo_groups SET preferred_image_id = ?, updated_at = ? WHERE id = ?",
            (image_id, now, group_id),
        )
        cur.execute(
            """
            UPDATE images
            SET is_primary_representation = CASE WHEN id = ? THEN 1 ELSE 0 END
            WHERE photo_group_id = ?
            """,
            (image_id, group_id),
        )
        self.conn.commit()
        return self.get_group(group_id)  # type: ignore

    def add_image_to_group(
        self, group_id: int, image_id: int, set_preferred: bool = False
    ) -> PhotoGroupOut:
        group = self.get_group(group_id)
        if not group:
            raise PhotoGroupNotFoundError(f"Photo group #{group_id} not found.")

        cur = self.conn.cursor()
        cur.execute("SELECT id, photo_group_id FROM images WHERE id = ?", (image_id,))
        img_row = cur.fetchone()
        if not img_row:
            raise ValueError(f"Image #{image_id} does not exist.")
        if img_row["photo_group_id"] is not None:
            raise ValueError(f"Image #{image_id} already belongs to a photo group.")

        now = datetime.now(timezone.utc).isoformat()
        try:
            cur.execute(
                """
                UPDATE images
                SET photo_group_id = ?, is_primary_representation = 0
                WHERE id = ? AND photo_group_id IS NULL
                """,
                (group_id, image_id),
            )
            if cur.rowcount != 1:
                self.conn.rollback()
                raise ValueError(
                    f"Failed to add image #{image_id} to group #{group_id}: already grouped or conflicting update."
                )

            if set_preferred:
                cur.execute(
                    "UPDATE photo_groups SET preferred_image_id = ?, updated_at = ? WHERE id = ?",
                    (image_id, now, group_id),
                )
                cur.execute(
                    """
                    UPDATE images
                    SET is_primary_representation = CASE WHEN id = ? THEN 1 ELSE 0 END
                    WHERE photo_group_id = ?
                    """,
                    (image_id, group_id),
                )
            else:
                cur.execute("UPDATE photo_groups SET updated_at = ? WHERE id = ?", (now, group_id))

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return self.get_group(group_id)  # type: ignore

    def add_images_to_group(self, group_id: int, image_ids: List[int]) -> PhotoGroupOut:
        group = self.get_group(group_id)
        if not group:
            raise PhotoGroupNotFoundError(f"Photo group #{group_id} not found.")

        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        for img_id in image_ids:
            cur.execute(
                """
                UPDATE images
                SET photo_group_id = ?, is_primary_representation = 0
                WHERE id = ?
                """,
                (group_id, img_id),
            )
        cur.execute("UPDATE photo_groups SET updated_at = ? WHERE id = ?", (now, group_id))
        self.conn.commit()
        return self.get_group(group_id)  # type: ignore

    def remove_image_from_group(self, group_id: int, image_id: int) -> Optional[PhotoGroupOut]:
        group = self.get_group(group_id)
        if not group:
            raise PhotoGroupNotFoundError(f"Photo group #{group_id} not found.")

        member_ids = [img.id for img in group.images]
        if image_id not in member_ids:
            raise ValueError(f"Image #{image_id} is not a member of group #{group_id}.")

        cur = self.conn.cursor()
        # Detach image
        cur.execute(
            "UPDATE images SET photo_group_id = NULL, is_primary_representation = 1 WHERE id = ?",
            (image_id,),
        )

        # Check remaining group members
        cur.execute("SELECT id FROM images WHERE photo_group_id = ? ORDER BY id ASC", (group_id,))
        remaining = [r["id"] for r in cur.fetchall()]

        if len(remaining) <= 1:
            # Dissolve group if 1 or 0 members remain
            if remaining:
                cur.execute(
                    "UPDATE images SET photo_group_id = NULL, is_primary_representation = 1 WHERE id = ?",
                    (remaining[0],),
                )
            cur.execute("DELETE FROM photo_groups WHERE id = ?", (group_id,))
            self.conn.commit()
            return None
        else:
            # If the removed image was preferred, select first remaining as preferred
            cur.execute("SELECT preferred_image_id FROM photo_groups WHERE id = ?", (group_id,))
            grp_row = cur.fetchone()
            if grp_row and grp_row["preferred_image_id"] == image_id:
                new_pref = remaining[0]
                now = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    "UPDATE photo_groups SET preferred_image_id = ?, updated_at = ? WHERE id = ?",
                    (new_pref, now, group_id),
                )
                cur.execute(
                    """
                    UPDATE images
                    SET is_primary_representation = CASE WHEN id = ? THEN 1 ELSE 0 END
                    WHERE photo_group_id = ?
                    """,
                    (new_pref, group_id),
                )
            self.conn.commit()
            return self.get_group(group_id)

    def delete_group(self, group_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE images SET photo_group_id = NULL, is_primary_representation = 1 WHERE photo_group_id = ?",
            (group_id,),
        )
        cur.execute("DELETE FROM photo_groups WHERE id = ?", (group_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def dismiss_candidate_pair(self, image_a_id: int, image_b_id: int) -> None:
        if image_a_id == image_b_id:
            raise ValueError("Cannot dismiss candidate pair with identical image IDs.")
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM images WHERE id IN (?, ?)", (image_a_id, image_b_id))
        found_ids = {r["id"] for r in cur.fetchall()}
        if image_a_id not in found_ids or image_b_id not in found_ids:
            raise PhotoGroupNotFoundError("One or both images not found.")

        a, b = min(image_a_id, image_b_id), max(image_a_id, image_b_id)
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT OR IGNORE INTO dismissed_group_candidates (image_a_id, image_b_id, created_at)
            VALUES (?, ?, ?)
            """,
            (a, b, now),
        )
        self.conn.commit()

    def get_dismissed_pairs(self) -> Set[Tuple[int, int]]:
        cur = self.conn.cursor()
        cur.execute("SELECT image_a_id, image_b_id FROM dismissed_group_candidates")
        return {(r["image_a_id"], r["image_b_id"]) for r in cur.fetchall()}

    def find_candidate_pairs(
        self,
        threshold: int = DHASH_CANDIDATE_THRESHOLD,
        limit: int = 50,
        library_id: Optional[int] = None,
    ) -> List[GroupCandidatePairOut]:
        """Scans indexed photos with dHash or exact SHA-256 equality to detect candidate representations.

        Pairs that are already in the same group or have been dismissed by the user are excluded.
        Optimized with 64-bit integer bitwise Hamming distance and flat heapq tuple ordering.
        """
        import heapq
        from collections import defaultdict

        cur = self.conn.cursor()
        query = """
            SELECT i.* FROM images i
            JOIN libraries l ON i.library_id = l.id
            WHERE i.is_present_on_disk = 1
              AND l.enabled = 1
              AND l.is_archived = 0
              AND (i.dhash IS NOT NULL OR i.sha256 IS NOT NULL)
        """
        params: list[object] = []
        if library_id is not None:
            query += " AND i.library_id = ?"
            params.append(library_id)

        query += " ORDER BY i.id ASC"
        cur.execute(query, tuple(params))
        rows = cur.fetchall()

        dismissed = self.get_dismissed_pairs()
        row_map = {r["id"]: r for r in rows}

        exact_pairs_seen: Set[Tuple[int, int]] = set()
        candidate_tuples: list[tuple[int, int, int, int, bool]] = []

        # 1. Fast O(N) detection of exact SHA-256 duplicates
        sha_groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in rows:
            if r["sha256"]:
                sha_groups[r["sha256"]].append(r)

        for sha, group_rows in sha_groups.items():
            if len(group_rows) > 1:
                for i in range(len(group_rows)):
                    r_a = group_rows[i]
                    g_a = r_a["photo_group_id"]
                    for j in range(i + 1, len(group_rows)):
                        r_b = group_rows[j]
                        g_b = r_b["photo_group_id"]
                        if g_a is not None and g_b is not None:
                            continue
                        min_id, max_id = (r_a["id"], r_b["id"]) if r_a["id"] < r_b["id"] else (r_b["id"], r_a["id"])
                        pair_key = (min_id, max_id)
                        if pair_key in dismissed:
                            continue
                        exact_pairs_seen.add(pair_key)
                        candidate_tuples.append((0, 0, min_id, max_id, True))

        # 2. Perceptual dHash matching on photos with valid dHash
        parsed_dhash_rows: list[tuple[int, int, Optional[int]]] = []
        for r in rows:
            dh = r["dhash"]
            if dh:
                try:
                    parsed_dhash_rows.append((r["id"], int(dh, 16), r["photo_group_id"]))
                except ValueError:
                    pass

        n = len(parsed_dhash_rows)
        for i in range(n):
            id_a, h_a, g_a = parsed_dhash_rows[i]
            for j in range(i + 1, n):
                id_b, h_b, g_b = parsed_dhash_rows[j]
                if g_a is not None and g_b is not None:
                    continue

                min_id, max_id = (id_a, id_b) if id_a < id_b else (id_b, id_a)
                pair_key = (min_id, max_id)
                if pair_key in exact_pairs_seen or pair_key in dismissed:
                    continue

                dist = (h_a ^ h_b).bit_count()
                if dist <= threshold:
                    candidate_tuples.append((1, dist, min_id, max_id, False))

        top_candidates = heapq.nsmallest(limit, candidate_tuples)

        # Lazy conversion: only instantiate ImageOut for the final selected candidates
        result: List[GroupCandidatePairOut] = []
        for priority, dist, min_id, max_id, is_exact in top_candidates:
            img_a = self.image_repo._row_to_image(row_map[min_id])
            img_b = self.image_repo._row_to_image(row_map[max_id])
            result.append(
                GroupCandidatePairOut(
                    image_a=img_a,
                    image_b=img_b,
                    hamming_distance=dist,
                    is_exact_duplicate=is_exact,
                )
            )
        return result

    def repair_groups(self) -> None:
        """Repairs and maintains database integrity for photo groups and representations:
        1. Dissolves groups with < 2 members into singletons.
        2. Deletes orphan groups that have no images.
        3. Re-elects preferred_image_id for groups if missing or invalid (MIN(id)).
        4. Synchronizes is_primary_representation = 1 for preferred and 0 for sibling variants.
        5. Resets is_primary_representation = 1 for all ungrouped photos.
        """
        cur = self.conn.cursor()

        # 1. Dissolve groups with < 2 members into singletons
        cur.execute(
            """
            UPDATE images
            SET photo_group_id = NULL, is_primary_representation = 1
            WHERE photo_group_id IN (
                SELECT photo_group_id
                FROM images
                WHERE photo_group_id IS NOT NULL
                GROUP BY photo_group_id
                HAVING COUNT(*) < 2
            )
            """
        )

        # 2. Delete empty/orphan photo_groups
        cur.execute(
            """
            DELETE FROM photo_groups
            WHERE NOT EXISTS (
                SELECT 1 FROM images WHERE images.photo_group_id = photo_groups.id
            )
            """
        )

        # 3. Re-elect preferred_image_id if missing or pointing to an image not in the group
        cur.execute(
            """
            UPDATE photo_groups
            SET preferred_image_id = (
                SELECT MIN(id) FROM images WHERE photo_group_id = photo_groups.id
            )
            WHERE preferred_image_id IS NULL
               OR preferred_image_id NOT IN (
                   SELECT id FROM images WHERE photo_group_id = photo_groups.id
               )
            """
        )

        # 4. Synchronize is_primary_representation = 1 for preferred, 0 for variants
        cur.execute(
            """
            UPDATE images
            SET is_primary_representation = CASE
                WHEN images.id = (
                    SELECT preferred_image_id FROM photo_groups WHERE photo_groups.id = images.photo_group_id
                ) THEN 1
                ELSE 0
            END
            WHERE photo_group_id IS NOT NULL
            """
        )

        # 5. Reset is_primary_representation = 1 for any images without a group
        cur.execute(
            """
            UPDATE images
            SET is_primary_representation = 1
            WHERE photo_group_id IS NULL AND is_primary_representation != 1
            """
        )

