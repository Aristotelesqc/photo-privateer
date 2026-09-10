"""Common utility functions for Photo Privateer."""
from __future__ import annotations

from typing import Sequence, TypeVar, Generator

T = TypeVar("T")

def chunked(seq: Sequence[T], size: int = 500) -> Generator[Sequence[T], None, None]:
    """Yields successive chunks of maximum `size` from `seq` to protect against SQLite parameter limits."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
