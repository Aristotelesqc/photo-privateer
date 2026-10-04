"""Deterministic reservation races without timing sleeps or paid providers."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from fastapi.testclient import TestClient

from backend.database import get_connection
from backend.main import app
from backend.repositories.usage_repo import UsageRepository
from backend.services.catalog_coordinator import CatalogOperationConflict, coordinator_for


def setup_catalog(repos, sample_images_dir):
    library = repos["lib_repo"].create(str(sample_images_dir))
    repos["indexer"].index_library(library.id)
    photos, _ = repos["img_repo"].list_images(library_id=library.id)
    return library, [photo.id for photo in photos]


def complete_worker(**kwargs):
    with get_connection(kwargs["db_path"]) as conn:
        repo = UsageRepository(conn)
        status = "CANCELLED" if repo.is_cancel_requested(kwargs["session_id"]) else "COMPLETED"
        repo.update_scan_session_progress(kwargs["session_id"], 0, 0, 0, status=status)


@pytest.mark.parametrize("winner", ["index", "scan"])
def test_both_start_orders_block_the_conflicting_operation(repos, sample_images_dir, monkeypatch, winner):
    library, ids = setup_catalog(repos, sample_images_dir)
    admitted = threading.Event()
    finish = threading.Event()
    indexer, scanner = repos["indexer"], repos["scan_engine"]
    original_index = indexer._index_library

    def paused_index(library_id):
        admitted.set()
        assert finish.wait(timeout=5)
        return original_index(library_id)

    def paused_scan(**kwargs):
        admitted.set()
        assert finish.wait(timeout=5)
        complete_worker(**kwargs)

    monkeypatch.setattr(indexer, "_index_library", paused_index)
    monkeypatch.setattr(scanner, "_run_scan_worker", paused_scan)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(indexer.index_library, library.id) if winner == "index" else pool.submit(scanner.execute_scan, ids, "mock")
        try:
            assert admitted.wait(timeout=5)
            with pytest.raises(CatalogOperationConflict):
                if winner == "index":
                    scanner.start_background_scan(ids, "mock")
                else:
                    indexer.index_library(library.id)
        finally:
            finish.set()
        future.result(timeout=5)
    # A failure response must not poison the next operation.
    indexer.index_library(library.id)
    assert scanner.execute_scan(ids, "mock").status == "COMPLETED"


def test_simultaneous_start_admits_exactly_one(repos, sample_images_dir, monkeypatch):
    library, ids = setup_catalog(repos, sample_images_dir)
    barrier = threading.Barrier(2)
    admitted = threading.Event()
    refused = threading.Event()
    finish = threading.Event()

    def paused_index(library_id):
        admitted.set()
        assert finish.wait(timeout=5)
        return {"scanned": 0}

    def paused_scan(**kwargs):
        admitted.set()
        assert finish.wait(timeout=5)
        complete_worker(**kwargs)

    monkeypatch.setattr(repos["indexer"], "_index_library", paused_index)
    monkeypatch.setattr(repos["scan_engine"], "_run_scan_worker", paused_scan)

    def run(operation):
        barrier.wait(timeout=5)
        try:
            operation()
            return "admitted"
        except CatalogOperationConflict:
            refused.set()
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        index = pool.submit(run, lambda: repos["indexer"].index_library(library.id))
        scan = pool.submit(run, lambda: repos["scan_engine"].execute_scan(ids, "mock"))
        try:
            assert admitted.wait(timeout=5)
            assert refused.wait(timeout=5)
        finally:
            finish.set()
        assert sorted([index.result(timeout=5), scan.result(timeout=5)]) == ["admitted", "refused"]


def test_reservation_shared_by_independent_connections(repos, db_path):
    with get_connection(db_path) as other:
        assert coordinator_for(other) is repos["indexer"].coordinator
        assert coordinator_for(other) is repos["scan_engine"].coordinator


def test_index_exception_and_invalid_scan_release_reservations(repos, sample_images_dir, monkeypatch):
    library, ids = setup_catalog(repos, sample_images_dir)
    with monkeypatch.context() as patch:
        def fail(library_id):
            raise RuntimeError("injected index failure")
        patch.setattr(repos["indexer"], "_index_library", fail)
        with pytest.raises(RuntimeError):
            repos["indexer"].index_library(library.id)
    with pytest.raises(ValueError):
        repos["scan_engine"].start_background_scan([], "mock")
    repos["indexer"].index_library(library.id)


@pytest.mark.parametrize("failure", ["thread_start", "response_query"])
def test_launch_failure_marks_session_failed_and_releases(repos, sample_images_dir, monkeypatch, failure):
    library, ids = setup_catalog(repos, sample_images_dir)
    def fail(*args, **kwargs):
        raise RuntimeError("injected launch failure")
    with monkeypatch.context() as patch:
        if failure == "thread_start":
            patch.setattr(threading.Thread, "start", fail)
        else:
            patch.setattr(repos["usage_repo"], "get_scan_session", fail)
        with pytest.raises(RuntimeError):
            repos["scan_engine"].start_background_scan(ids, "mock")
    assert repos["usage_repo"].list_scan_sessions()[0].status == "FAILED"
    repos["indexer"].index_library(library.id)


def test_worker_bootstrap_failure_releases(repos, sample_images_dir, monkeypatch):
    library, ids = setup_catalog(repos, sample_images_dir)
    def fail(**kwargs):
        raise RuntimeError("injected bootstrap failure")
    monkeypatch.setattr(repos["scan_engine"], "_run_scan_worker", fail)
    assert repos["scan_engine"].execute_scan(ids, "mock").status == "FAILED"
    repos["indexer"].index_library(library.id)


def test_background_cancellation_holds_reservation_until_worker_exits(repos, sample_images_dir, monkeypatch):
    library, ids = setup_catalog(repos, sample_images_dir)
    admitted = threading.Event()
    finish = threading.Event()
    def paused(**kwargs):
        admitted.set()
        assert finish.wait(timeout=5)
        complete_worker(**kwargs)
    monkeypatch.setattr(repos["scan_engine"], "_run_scan_worker", paused)
    session = repos["scan_engine"].start_background_scan(ids, "mock")
    try:
        assert admitted.wait(timeout=5)
        repos["scan_engine"].cancel_scan(session.id)
        with pytest.raises(CatalogOperationConflict):
            repos["indexer"].index_library(library.id)
        worker = next(t for t in threading.enumerate() if t.name == f"scan-worker-{session.id}")
    finally:
        finish.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert repos["usage_repo"].get_scan_session(session.id).status == "CANCELLED"
    repos["indexer"].index_library(library.id)


def test_api_conflicts_are_actionable_and_startup_recovers_persisted_state(client, repos, sample_images_dir):
    library, ids = setup_catalog(repos, sample_images_dir)
    token = repos["indexer"].coordinator.acquire("indexing")
    try:
        response = client.post("/api/scans/prepare", json={"image_ids": ids})
        assert response.status_code == 409 and "indexing" in response.json()["detail"]
        response = client.post(f"/api/libraries/{library.id}/index")
        assert response.status_code == 409 and "retry" in response.json()["detail"]
    finally:
        repos["indexer"].coordinator.release(token)
    repos["usage_repo"].create_scan_session(provider="mock", total_images=1)
    assert client.post(f"/api/libraries/{library.id}/index").status_code == 409
    # Startup in a new server lifecycle recovers the persisted previous session.
    with TestClient(app, base_url="http://localhost"):
        pass
    assert client.post(f"/api/libraries/{library.id}/index").status_code == 200
