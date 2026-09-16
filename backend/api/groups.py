"""Photo groups and representation deduplication API router."""
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.models import (
    PhotoGroupOut,
    PhotoGroupCreate,
    GroupCandidatePairOut,
    DismissCandidateRequest,
    SetPreferredRequest,
    AddImageToGroupRequest,
)
from backend.repositories.group_repo import PhotoGroupRepository, PhotoGroupNotFoundError
from backend.api.deps import get_group_repo

router = APIRouter(prefix="/api/groups", tags=["groups"])


@router.get("/candidates", response_model=List[GroupCandidatePairOut])
def get_group_candidates(
    threshold: int = Query(default=10, ge=0, le=16),
    limit: int = Query(default=50, ge=1, le=500),
    library_id: Optional[int] = Query(default=None),
    repo: PhotoGroupRepository = Depends(get_group_repo),
):
    """Returns candidate photo representation pairs (perceptual distance <= threshold or exact SHA)."""
    try:
        return repo.find_candidate_pairs(threshold=threshold, limit=limit, library_id=library_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed finding candidate pairs: {str(e)}")


@router.post("/candidates/dismiss")
def dismiss_candidate_pair(
    payload: DismissCandidateRequest,
    repo: PhotoGroupRepository = Depends(get_group_repo),
):
    """Dismisses a candidate pair so they are kept separate in future reviews."""
    try:
        repo.dismiss_candidate_pair(payload.image_a_id, payload.image_b_id)
        return {"status": "dismissed", "image_a_id": payload.image_a_id, "image_b_id": payload.image_b_id}
    except (PhotoGroupNotFoundError, KeyError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("", response_model=PhotoGroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: PhotoGroupCreate,
    repo: PhotoGroupRepository = Depends(get_group_repo),
):
    """Creates a photo group uniting candidate image representations."""
    try:
        return repo.create_group(
            image_ids=payload.image_ids,
            preferred_image_id=payload.preferred_image_id,
            name=payload.name,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=List[PhotoGroupOut])
def list_groups(
    repo: PhotoGroupRepository = Depends(get_group_repo),
):
    """Lists all photo groups with their member representations."""
    return repo.list_groups()


@router.get("/{group_id}", response_model=PhotoGroupOut)
def get_group(
    group_id: int,
    repo: PhotoGroupRepository = Depends(get_group_repo),
):
    """Retrieves a single photo group by ID."""
    grp = repo.get_group(group_id)
    if not grp:
        raise HTTPException(status_code=404, detail=f"Photo group #{group_id} not found.")
    return grp


@router.put("/{group_id}/preferred", response_model=PhotoGroupOut)
def set_preferred_image(
    group_id: int,
    payload: SetPreferredRequest,
    repo: PhotoGroupRepository = Depends(get_group_repo),
):
    """Sets the preferred (primary) image representation for a photo group."""
    try:
        return repo.set_preferred_image(group_id, payload.preferred_image_id)
    except (PhotoGroupNotFoundError, KeyError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{group_id}/images", response_model=PhotoGroupOut)
def add_image_to_group(
    group_id: int,
    payload: AddImageToGroupRequest,
    repo: PhotoGroupRepository = Depends(get_group_repo),
):
    """Adds an image representation to an existing photo group."""
    try:
        return repo.add_image_to_group(
            group_id=group_id,
            image_id=payload.image_id,
            set_preferred=payload.set_preferred,
        )
    except (PhotoGroupNotFoundError, KeyError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{group_id}")
def delete_group(
    group_id: int,
    repo: PhotoGroupRepository = Depends(get_group_repo),
):
    """Deletes a photo group, reverting all members to singleton representations."""
    success = repo.delete_group(group_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Photo group #{group_id} not found.")
    return {"status": "deleted", "group_id": group_id}


@router.delete("/{group_id}/images/{image_id}", response_model=Optional[PhotoGroupOut])
def remove_image_from_group(
    group_id: int,
    image_id: int,
    repo: PhotoGroupRepository = Depends(get_group_repo),
):
    """Removes an image representation from a group. Dissolves group if <= 1 member remains."""
    try:
        return repo.remove_image_from_group(group_id, image_id)
    except (PhotoGroupNotFoundError, KeyError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

