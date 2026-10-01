import { GroupCandidatePair, PhotoGroup } from '../../types';
import { addImageToGroup, createPhotoGroup } from '../../api/client';

export type CandidateSide = 'A' | 'B';

/** Preferred selection in the candidate modal; null keeps an existing group's current primary. */
export type PreferredSelection = CandidateSide | null;

const isGroupPrimary = (image: GroupCandidatePair['image_a']) =>
  Boolean(image.photo_group_id) && image.is_primary_representation === 1;

/** True when one photo of the pair already belongs to a group (the other would join it). */
export const pairJoinsExistingGroup = (pair: GroupCandidatePair): boolean =>
  Boolean(pair.image_a.photo_group_id || pair.image_b.photo_group_id);

/**
 * Initial preferred selection for a candidate pair.
 * - New group: Candidate A (one photo must be chosen as primary).
 * - Existing group whose primary is one of the cards: that card (no change).
 * - Existing group whose primary is not shown: no selection, so adding a photo never changes the
 *   group's searched representation unless the user explicitly picks a card.
 */
export const defaultPreferredSelection = (pair: GroupCandidatePair): PreferredSelection => {
  if (!pairJoinsExistingGroup(pair)) return 'A';
  if (isGroupPrimary(pair.image_a)) return 'A';
  if (isGroupPrimary(pair.image_b)) return 'B';
  return null;
};

/**
 * Applies the user's grouping decision for a candidate pair. When joining an existing group,
 * `preferredId` (if given) becomes the group's primary representation whichever side of the pair
 * it is on, applied atomically by the backend; when omitted the current primary is kept.
 */
export const groupCandidatePair = (pair: GroupCandidatePair, preferredId?: number): Promise<PhotoGroup> => {
  const { image_a, image_b } = pair;
  if (image_a.photo_group_id) {
    return addImageToGroup(image_a.photo_group_id, image_b.id, preferredId);
  }
  if (image_b.photo_group_id) {
    return addImageToGroup(image_b.photo_group_id, image_a.id, preferredId);
  }
  return createPhotoGroup({
    image_ids: [image_a.id, image_b.id],
    preferred_image_id: preferredId ?? image_a.id,
  });
};
