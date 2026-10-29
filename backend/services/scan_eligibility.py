"""Shared read-only source policy for browse selection and scan planning."""
from __future__ import annotations

from backend.models import ImageOut, LibraryOut
from backend.repositories.image_repo import ImageRepository
from backend.repositories.library_repo import LibraryRepository
from backend.services.source_availability import source_path_available


def source_available(image: ImageOut, library: LibraryOut | None) -> bool:
    return source_path_available(image.file_path, image.is_present_on_disk, library.path if library else None)


def is_available(image: ImageOut, active_libraries: dict[int, LibraryOut]) -> bool:
    return source_available(image, active_libraries.get(image.library_id))


def annotate_eligibility(images: list[ImageOut], repo: ImageRepository) -> list[ImageOut]:
    """Inactive selections are forbidden even if they have an active group sibling.

    Missing active selections can use an active, available sibling. The result is
    a browse-time snapshot; preparation, launch and the worker validate again.
    """
    libraries = {lib.id: lib for lib in LibraryRepository(repo.conn).list_libraries(include_archived=True)}
    active = {key: lib for key, lib in libraries.items() if lib.enabled and not lib.is_archived}
    groups: dict[int, bool] = {}
    result = []
    for image in images:
        lib = libraries.get(image.library_id)
        available = source_available(image, lib)
        eligible = image.library_id in active and available
        if image.library_id in active and image.photo_group_id is not None:
            gid = image.photo_group_id
            if gid not in groups:
                groups[gid] = any(is_available(member, active) for member in repo.get_images_for_group(gid))
            eligible = groups[gid]
        result.append(image.model_copy(update={
            "library_enabled": bool(lib and lib.enabled),
            "library_archived": bool(lib and lib.is_archived),
            "source_available": available,
            "scan_eligible": eligible,
        }))
    return result
