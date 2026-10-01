import { GroupCandidatePair, PhotoGroup } from '../../types';
import { addImageToGroup, createPhotoGroup } from '../../api/client';

export type CandidateSide = 'A' | 'B';

const isGroupPrimary = (image: GroupCandidatePair['image_a']) =>
  Boolean(image.photo_group_id) && image.is_primary_representation === 1;

/**
 * Initial preferred side for a candidate pair: when one photo is already the primary
 * representation of its group, keep it selected so grouping does not change the group's
 * searched photo unless the user picks the other card.
 */
export const defaultPreferredSide = (pair: GroupCandidatePair): CandidateSide =>
  !isGroupPrimary(pair.image_a) && isGroupPrimary(pair.image_b) ? 'B' : 'A';

/**
 * Applies the user's grouping decision for a candidate pair. The chosen preferred photo becomes
 * the group's primary representation whichever side of the pair it is on, including when it is
 * the photo that already belongs to the group (applied atomically by the backend).
 */
export const groupCandidatePair = (pair: GroupCandidatePair, preferredId: number): Promise<PhotoGroup> => {
  const { image_a, image_b } = pair;
  if (image_a.photo_group_id) {
    return addImageToGroup(image_a.photo_group_id, image_b.id, preferredId);
  }
  if (image_b.photo_group_id) {
    return addImageToGroup(image_b.photo_group_id, image_a.id, preferredId);
  }
  return createPhotoGroup({
    image_ids: [image_a.id, image_b.id],
    preferred_image_id: preferredId,
  });
};
