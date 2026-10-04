"""Atomic operation reservations for the single-process desktop catalog."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
import weakref


class CatalogOperationConflict(ValueError):
    """A conflicting catalog operation must finish before this action starts."""


class CatalogCoordinator:
    def __init__(self):
        self._lock = threading.Lock()
        self._reservation: tuple[str, object] | None = None

    def acquire(self, operation: str) -> object:
        with self._lock:
            if self._reservation is not None:
                raise CatalogOperationConflict(
                    f"Cannot start {operation}: the catalog is busy {self._reservation[0]}. "
                    "Wait for it to finish or cancel the active scan, then retry."
                )
            token = object()
            self._reservation = (operation, token)
            return token

    def release(self, token: object) -> None:
        with self._lock:
            if self._reservation is not None and self._reservation[1] is token:
                self._reservation = None

    def check_scan_preparation(self) -> None:
        with self._lock:
            if self._reservation and self._reservation[0] == "indexing":
                raise CatalogOperationConflict("The catalog is indexing. Wait for indexing to finish, then retry the scan.")

    @contextmanager
    def indexing(self, conn: sqlite3.Connection):
        token = self.acquire("indexing")
        try:
            # Persisted RUNNING state also protects direct/legacy entry points.
            # Normal startup recovery clears sessions from a previous process.
            if conn.execute("SELECT 1 FROM scan_sessions WHERE status = 'RUNNING' LIMIT 1").fetchone():
                raise CatalogOperationConflict("A scan session is running. Finish or cancel it before indexing.")
            yield
        finally:
            self.release(token)


_registry_lock = threading.Lock()
_registry: weakref.WeakValueDictionary[str, CatalogCoordinator] = weakref.WeakValueDictionary()


def coordinator_for(conn: sqlite3.Connection) -> CatalogCoordinator:
    path = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    key = str(Path(path).resolve()).casefold() if path else f"memory:{id(conn)}"
    with _registry_lock:
        coordinator = _registry.get(key)
        if coordinator is None:
            coordinator = CatalogCoordinator()
            _registry[key] = coordinator
        return coordinator
