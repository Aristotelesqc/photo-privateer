"""Perceptual hashing and representation similarity utilities using Pillow."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union
from PIL import Image, ImageOps

DHASH_UNAVAILABLE: str = ""
DHASH_CANDIDATE_THRESHOLD = 10

# A dHash encodes 64 horizontal brightness gradients. Uniform frames (lens-cap shots, flat
# backdrops, blank exports) produce near-all-zero hashes and smooth horizontal ramps produce
# near-all-one hashes. Two hashes with at most k set bits each are always within 2k bits of
# each other, so such low-information hashes would match one another regardless of content;
# they are excluded from perceptual matching (exact SHA-256 duplicates are still reported).
DHASH_MIN_INFORMATIVE_BITS = 8
DHASH_MAX_INFORMATIVE_BITS = 56

# JPEG draft decoding: the decoder downsamples by up to 1/8 in the DCT domain, which is
# far cheaper than a full decode and is ample resolution for a 9x8 gradient hash.
_DRAFT_TARGET_SIZE = (128, 128)


def compute_dhash(image_input: Union[str, Path, Image.Image]) -> Optional[str]:
    """Computes a 64-bit difference hash (dHash) for an image.

    Downsamples the image to 9x8 grayscale and computes horizontal pixel gradients.
    Returns a 16-character lowercase hexadecimal string, or None if unreadable.
    File inputs are opened read-only and JPEGs are decoded in reduced-size draft mode.
    """
    try:
        if isinstance(image_input, (str, Path)):
            path = Path(image_input)
            if not path.is_file():
                return None
            with Image.open(path) as img:
                img.draft("L", _DRAFT_TARGET_SIZE)
                transposed = ImageOps.exif_transpose(img)
                return _dhash_from_pil(transposed)
        elif isinstance(image_input, Image.Image):
            transposed = ImageOps.exif_transpose(image_input)
            return _dhash_from_pil(transposed)
        return None
    except Exception:
        return None


def _flatten_alpha(img: Image.Image) -> Image.Image:
    """Composites images with transparency onto an opaque white matte. Fully transparent pixels
    may store any RGB value (black in one export, white in another); without a matte those hidden
    values would drive the luminance gradients and make two exports of one cut-out unrelated."""
    has_alpha = img.mode in ("RGBA", "LA", "PA", "La", "RGBa") or (
        img.mode == "P" and "transparency" in img.info
    )
    if not has_alpha:
        return img
    rgba = img.convert("RGBA")
    matte = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    matte.alpha_composite(rgba)
    return matte.convert("RGB")


def _dhash_from_pil(img: Image.Image) -> str:
    """Internal helper to compute 64-bit dHash from an open PIL image."""
    gray = _flatten_alpha(img).convert("L")
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


def is_informative_dhash_value(value: int) -> bool:
    """Returns True if a parsed 64-bit dHash carries enough gradient information to be compared."""
    return DHASH_MIN_INFORMATIVE_BITS <= value.bit_count() <= DHASH_MAX_INFORMATIVE_BITS


def is_informative_dhash(hash_hex: Optional[str]) -> bool:
    """Returns True if a hex dHash is present, parseable and not a low-information hash."""
    if not hash_hex:
        return False
    try:
        return is_informative_dhash_value(int(hash_hex, 16))
    except ValueError:
        return False


def hamming_distance(hash1: str, hash2: str) -> int:
    """Computes the Hamming distance (number of differing bits) between two 16-char hex dHashes."""
    val1 = int(hash1, 16)
    val2 = int(hash2, 16)
    return (val1 ^ val2).bit_count()


def is_candidate_representation(
    hash1: str, hash2: str, threshold: int = DHASH_CANDIDATE_THRESHOLD
) -> bool:
    """Returns True if two hashes are within the perceptual candidate similarity threshold
    and both carry enough information to be meaningfully compared."""
    if not (is_informative_dhash(hash1) and is_informative_dhash(hash2)):
        return False
    return hamming_distance(hash1, hash2) <= threshold
