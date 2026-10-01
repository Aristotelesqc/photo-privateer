"""Repository for photo groups and representation deduplication candidates."""
from __future__ import annotations

import sqlite3
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, List, Set, Tuple

from backend.models import (
    PhotoGroupOut,
    GroupCandidatePairOut,
    ImageOut,
)
from backend.repositories.image_repo import ImageRepository
from backend.services.perceptual import DHASH_CANDIDATE_THRESHOLD, is_informative_dhash_value


class PhotoGroupNotFoundError(LookupError):
    pass


# (priority, hamming_distance, min_image_id, max_image_id, is_exact_duplicate)
# priority 0 = exact SHA-256 duplicate, 1 = perceptual dHash variant. Tuples sort naturally.
CandidateTuple = Tuple[int, int, int, int, bool]

# Process-wide cache of fully sorted candidate tuples, keyed by database instance, threshold and
# library scope. Each entry stores the group_candidate_state generation it was computed at;
# SQLite triggers (migration 010) bump the generation whenever any search input changes.
_CANDIDATE_CACHE_MAX_ENTRIES = 16
_candidate_cache: dict[tuple[str, int, Optional[int]], tuple[int, list[CandidateTuple]]] = {}
_candidate_cache_lock = threading.Lock()


def _band_layout(threshold: int) -> list[tuple[int, int]]:
    """Splits the 64 hash bits into threshold + 1 contiguous bands as (shift, mask) pairs.

    Pigeonhole principle: if two hashes differ in at most `threshold` bits, at least one of the
    threshold + 1 bands is bit-identical, so bucketing by each band finds every such pair.
    """
    bands = threshold + 1
    base, extra = divmod(64, bands)
    layout: list[tuple[int, int]] = []
    shift = 0
    for b in range(bands):
        width = base + (1 if b < extra else 0)
        layout.append((shift, (1 << width) - 1))
        shift += width
    return layout


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
                    raise ValueError(f"Image #{img_id} was concurrently modified or already belongs to a group.")

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return self.get_group(group_id)  # type: ignore

    def _apply_preferred(self, cur: sqlite3.Cursor, group_id: int, image_id: int, now: str) -> None:
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

    def set_preferred_image(self, group_id: int, image_id: int) -> PhotoGroupOut:
        group = self.get_group(group_id)
        if not group:
            raise PhotoGroupNotFoundError(f"Photo group #{group_id} not found.")

        member_ids = [img.id for img in group.images]
        if image_id not in member_ids:
            raise ValueError(f"Image #{image_id} is not a member of group #{group_id}.")

        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        try:
            self._apply_preferred(cur, group_id, image_id, now)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.get_group(group_id)  # type: ignore

    def add_image_to_group(
        self,
        group_id: int,
        image_id: int,
        set_preferred: bool = False,
        preferred_image_id: Optional[int] = None,
    ) -> PhotoGroupOut:
        """Adds an ungrouped image to an existing group in a single transaction.

        `preferred_image_id` may name the added image or any existing member, so a user's choice of
        primary representation is applied atomically whichever side of the candidate pair it was.
        `set_preferred=True` is shorthand for `preferred_image_id=image_id`.
        """
        group = self.get_group(group_id)
        if not group:
            raise PhotoGroupNotFoundError(f"Photo group #{group_id} not found.")

        if set_preferred and preferred_image_id is None:
            preferred_image_id = image_id
        member_ids = {img.id for img in group.images}
        if preferred_image_id is not None and preferred_image_id != image_id and preferred_image_id not in member_ids:
            raise ValueError(
                f"Preferred image #{preferred_image_id} is neither the added image nor a member of group #{group_id}."
            )

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
                raise ValueError(
                    f"Failed to add image #{image_id} to group #{group_id}: already grouped or conflicting update."
                )

            if preferred_image_id is not None and preferred_image_id != group.preferred_image_id:
                self._apply_preferred(cur, group_id, preferred_image_id, now)
            else:
                cur.execute("UPDATE photo_groups SET updated_at = ? WHERE id = ?", (now, group_id))

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return self.get_group(group_id)  # type: ignore

    def remove_image_from_group(self, group_id: int, image_id: int) -> Optional[PhotoGroupOut]:
        group = self.get_group(group_id)
        if not group:
            raise PhotoGroupNotFoundError(f"Photo group #{group_id} not found.")

        member_ids = [img.id for img in group.images]
        if image_id not in member_ids:
            raise ValueError(f"Image #{image_id} is not a member of group #{group_id}.")

        cur = self.conn.cursor()
        try:
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

            # If the removed image was preferred, select first remaining as preferred
            cur.execute("SELECT preferred_image_id FROM photo_groups WHERE id = ?", (group_id,))
            grp_row = cur.fetchone()
            if grp_row and grp_row["preferred_image_id"] == image_id:
                self._apply_preferred(cur, group_id, remaining[0], datetime.now(timezone.utc).isoformat())
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.get_group(group_id)

    def delete_group(self, group_id: int) -> bool:
        cur = self.conn.cursor()
        try:
            cur.execute(
                "UPDATE images SET photo_group_id = NULL, is_primary_representation = 1 WHERE photo_group_id = ?",
                (group_id,),
            )
            cur.execute("DELETE FROM photo_groups WHERE id = ?", (group_id,))
            deleted = cur.rowcount > 0
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return deleted

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

    def _candidate_state(self) -> Optional[tuple[str, int]]:
        """Returns (instance_token, generation) of the candidate search inputs, if tracked."""
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT instance_token, generation FROM group_candidate_state WHERE id = 1")
            row = cur.fetchone()
        except sqlite3.Error:
            return None
        return (row["instance_token"], row["generation"]) if row else None

    def _compute_candidate_tuples(self, threshold: int, library_id: Optional[int]) -> list[CandidateTuple]:
        """Computes every candidate pair, sorted exact duplicates first then by ascending distance.

        Perceptual matching buckets hashes by threshold + 1 bit bands (pigeonhole), so only pairs
        sharing at least one identical band are compared. This is exact: no pair within the
        threshold is missed. Low-information hashes (uniform frames, flat ramps) are skipped.
        """
        cur = self.conn.cursor()
        query = """
            SELECT i.id, i.sha256, i.dhash, i.photo_group_id FROM images i
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
        candidates: list[CandidateTuple] = []
        exact_pairs_seen: Set[Tuple[int, int]] = set()

        # 1. Exact SHA-256 duplicates
        sha_groups: dict[str, list[tuple[int, Optional[int]]]] = defaultdict(list)
        for r in rows:
            if r["sha256"]:
                sha_groups[r["sha256"]].append((r["id"], r["photo_group_id"]))

        for members in sha_groups.values():
            if len(members) < 2:
                continue
            for i in range(len(members)):
                id_a, g_a = members[i]
                for j in range(i + 1, len(members)):
                    id_b, g_b = members[j]
                    if g_a is not None and g_b is not None:
                        continue
                    pair_key = (id_a, id_b) if id_a < id_b else (id_b, id_a)
                    if pair_key in dismissed:
                        continue
                    exact_pairs_seen.add(pair_key)
                    candidates.append((0, 0, pair_key[0], pair_key[1], True))

        # 2. Perceptual dHash variants via pigeonhole band bucketing
        entries: list[tuple[int, int, Optional[int]]] = []
        for r in rows:
            dh = r["dhash"]
            if not dh:
                continue
            try:
                value = int(dh, 16)
            except ValueError:
                continue
            if is_informative_dhash_value(value):
                entries.append((r["id"], value, r["photo_group_id"]))

        found: dict[Tuple[int, int], int] = {}
        for shift, mask in _band_layout(threshold):
            buckets: dict[int, list[int]] = defaultdict(list)
            for pos, entry in enumerate(entries):
                buckets[(entry[1] >> shift) & mask].append(pos)
            for bucket in buckets.values():
                size = len(bucket)
                if size < 2:
                    continue
                hashes = [entries[pos][1] for pos in bucket]
                for i in range(size - 1):
                    h_a = hashes[i]
                    # Distance first: by far the most selective and cheapest test
                    hits = [j for j in range(i + 1, size) if (h_a ^ hashes[j]).bit_count() <= threshold]
                    if not hits:
                        continue
                    id_a, _h, g_a = entries[bucket[i]]
                    for j in hits:
                        id_b, h_b, g_b = entries[bucket[j]]
                        if g_a is not None and g_b is not None:
                            continue
                        pair_key = (id_a, id_b) if id_a < id_b else (id_b, id_a)
                        if pair_key in found or pair_key in exact_pairs_seen or pair_key in dismissed:
                            continue
                        found[pair_key] = (h_a ^ h_b).bit_count()

        candidates.extend((1, dist, a, b, False) for (a, b), dist in found.items())
        candidates.sort()
        return candidates

    def _get_candidate_tuples(self, threshold: int, library_id: Optional[int]) -> list[CandidateTuple]:
        state = None if self.conn.in_transaction else self._candidate_state()
        if state is None:
            return self._compute_candidate_tuples(threshold, library_id)

        token, generation = state
        key = (token, threshold, library_id)
        with _candidate_cache_lock:
            cached = _candidate_cache.get(key)
        if cached is not None and cached[0] == generation:
            return cached[1]

        tuples = self._compute_candidate_tuples(threshold, library_id)
        with _candidate_cache_lock:
            if len(_candidate_cache) >= _CANDIDATE_CACHE_MAX_ENTRIES and key not in _candidate_cache:
                _candidate_cache.clear()
            _candidate_cache[key] = (generation, tuples)
        return tuples

    def find_candidates_page(
        self,
        threshold: int = DHASH_CANDIDATE_THRESHOLD,
        limit: int = 50,
        library_id: Optional[int] = None,
    ) -> tuple[List[GroupCandidatePairOut], int]:
        """Returns (top `limit` candidate pairs, total number of candidate pairs).

        Pairs where both images are already grouped or that the user dismissed are excluded.
        Results are cached until any search input changes (see migration 010).
        """
        tuples = self._get_candidate_tuples(threshold, library_id)
        top = tuples[:limit]
        if not top:
            return [], len(tuples)

        # Fetch fresh row data for the selected pairs only
        needed_ids = sorted({t[2] for t in top} | {t[3] for t in top})
        images = {img.id: img for img in self.image_repo.get_by_ids(needed_ids)}

        result: List[GroupCandidatePairOut] = []
        for _priority, dist, min_id, max_id, is_exact in top:
            img_a = images.get(min_id)
            img_b = images.get(max_id)
            if img_a is None or img_b is None:
                continue
            result.append(
                GroupCandidatePairOut(
                    image_a=img_a,
                    image_b=img_b,
                    hamming_distance=dist,
                    is_exact_duplicate=is_exact,
                )
            )
        return result, len(tuples)

    def find_candidate_pairs(
        self,
        threshold: int = DHASH_CANDIDATE_THRESHOLD,
        limit: int = 50,
        library_id: Optional[int] = None,
    ) -> List[GroupCandidatePairOut]:
        """Returns the top `limit` candidate representation pairs (exact SHA-256 or dHash variants)."""
        pairs, _total = self.find_candidates_page(threshold=threshold, limit=limit, library_id=library_id)
        return pairs

    def repair_groups(self) -> None:
        """Repairs and maintains database integrity for photo groups and representations:
        1. Dissolves groups with < 2 members into singletons.
        2. Deletes orphan groups that have no images.
        3. Re-elects preferred_image_id for groups if missing or invalid (MIN(id)).
        4. Synchronizes is_primary_representation = 1 for preferred and 0 for sibling variants.
        5. Resets is_primary_representation = 1 for all ungrouped photos.

        Does not commit: callers run it inside their own transaction.
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
