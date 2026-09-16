"""Perceptual hashing and representation similarity utilities using Pillow."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union
from PIL import Image, ImageOps

DHASH_UNAVAILABLE: str = ""
DHASH_CANDIDATE_THRESHOLD = 10


def compute_dhash(image_input: Union[str, Path, Image.Image]) -> Optional[str]:
    """Computes a 64-bit difference hash (dHash) for an image.

    Downsamples the image to 9x8 grayscale and computes horizontal pixel gradients.
    Returns a 16-character lowercase hexadecimal string, or None if unreadable.
    """
    try:
        if isinstance(image_input, (str, Path)):
            path = Path(image_input)
            if not path.is_file():
                return None
            with Image.open(path) as img:
                transposed = ImageOps.exif_transpose(img)
                return _dhash_from_pil(transposed)
        elif isinstance(image_input, Image.Image):
            transposed = ImageOps.exif_transpose(image_input)
            return _dhash_from_pil(transposed)
        return None
    except Exception:
        return None


def _dhash_from_pil(img: Image.Image) -> str:
    """Internal helper to compute 64-bit dHash from an open PIL image."""
    gray = img.convert("L")
    resized = gray.resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(resized.tobytes())

    diff_bits = 0
    for row in range(8):
        row_offset = row * 9
        for col in range(8):
            left = pixels[row_offset + col]
            right = pixels[row_offset + col + 1]
            diff_bits = (diff_bits << 1) | (1 if right > left else 0)

    return f"{diff_bits:016x}"


def hamming_distance(hash1: str, hash2: str) -> int:
    """Computes the Hamming distance (number of differing bits) between two 16-char hex dHashes."""
    val1 = int(hash1, 16)
    val2 = int(hash2, 16)
    return (val1 ^ val2).bit_count()


def is_candidate_representation(
    hash1: str, hash2: str, threshold: int = DHASH_CANDIDATE_THRESHOLD
) -> bool:
    """Returns True if two hashes are within the perceptual candidate similarity threshold."""
    return hamming_distance(hash1, hash2) <= threshold
