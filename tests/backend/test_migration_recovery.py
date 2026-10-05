"""Recovery gates execute before catalog mutations and retain profile ownership."""
import asyncio
from contextlib import closing
import sqlite3
from types import SimpleNamespace

import pytest

from backend.database import init_db, get_connection
from backend.migrations import runner
from backend.services import catalog_backup as backups
from backend.services.catalog_coordinator import coordinator_for
from backend.services.profile_lock import ProfileBusyError, profile_lease


def old_catalog(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(get_connection(path)) as conn:
        original = runner.MIGRATIONS
        try:
            runner.MIGRATIONS = original[:20]
            runner.run_migrations(conn)
        finally:
            runner.MIGRATIONS = original
        conn.execute("INSERT INTO settings VALUES ('review-marker', 'preserved')")
        conn.commit()


def test_upgrade_backed_up_before_first_mutation_and_restorable(tmp_path, monkeypatch):
    path = tmp_path / 'profile' / backups.DATABASE_NAME
    old_catalog(path)
    original = runner.run_migrations
    observed = []

    def require_recovery(conn):
        bundles = list((path.parent / 'backups').glob('pre-migration-*'))
        assert len(bundles) == 1
        manifest = backups.verify_backup(bundles[0])
        assert manifest['schema_versions'] == list(range(1, 21))
        with closing(backups.readonly_database(bundles[0] / 'catalog.sqlite', immutable=True)) as before:
            assert before.execute("SELECT value FROM settings WHERE key='review-marker'").fetchone()[0] == 'preserved'
            assert before.execute("SELECT name FROM sqlite_master WHERE name='catalog_artifacts'").fetchone() is None
        observed.append(bundles[0])
        return original(conn)

    monkeypatch.setattr(runner, 'run_migrations', require_recovery)
    assert init_db(path) == [21]
    assert len(observed) == 1
    recovered = tmp_path / 'recovered'
    backups.restore_backup(observed[0], recovered)
    with closing(backups.readonly_database(recovered / backups.DATABASE_NAME)) as conn:
        assert runner.get_applied_migrations(conn) == list(range(1, 21))
    monkeypatch.setattr(runner, 'run_migrations', original)
    assert init_db(path) == []
    assert len(list((path.parent / 'backups').glob('pre-migration-*'))) == 1


def test_backup_failure_aborts_upgrade_without_catalog_mutation(tmp_path, monkeypatch):
    path = tmp_path / 'profile' / backups.DATABASE_NAME
    old_catalog(path)
    def fail(*args, **kwargs):
        raise backups.BackupError('disk full')
    monkeypatch.setattr(backups, 'backup_catalog', fail)
    with pytest.raises(backups.BackupError, match='disk full'):
        init_db(path)
    with closing(backups.readonly_database(path)) as conn:
        assert runner.get_applied_migrations(conn) == list(range(1, 21))
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='catalog_artifacts'").fetchone() is None
        assert conn.execute("SELECT value FROM settings WHERE key='review-marker'").fetchone()[0] == 'preserved'


def test_partially_committed_failing_migration_has_verified_recovery(tmp_path, monkeypatch):
    path = tmp_path / 'profile' / backups.DATABASE_NAME
    init_db(path)
    with closing(get_connection(path)) as conn:
        conn.execute("INSERT INTO settings VALUES ('review-marker', 'before')")
        conn.commit()
    def failing(conn):
        conn.execute("UPDATE settings SET value='after' WHERE key='review-marker'")
        conn.commit()  # Simulate a migration with independently committed DDL/DML.
        raise RuntimeError('upgrade failed')
    monkeypatch.setattr(runner, 'MIGRATIONS', runner.MIGRATIONS + [runner.Migration(22, 'failure', failing)])
    with pytest.raises(RuntimeError, match='upgrade failed'):
        init_db(path)
    bundle, = list((path.parent / 'backups').glob('pre-migration-*'))
    backups.verify_backup(bundle)
    backups.restore_backup(bundle, tmp_path / 'recovered')
    with closing(backups.readonly_database(tmp_path / 'recovered' / backups.DATABASE_NAME)) as conn:
        assert conn.execute("SELECT value FROM settings WHERE key='review-marker'").fetchone()[0] == 'before'
    with closing(backups.readonly_database(path)) as conn:
        assert conn.execute("SELECT value FROM settings WHERE key='review-marker'").fetchone()[0] == 'after'


def test_new_catalog_and_current_catalog_skip_recovery_bundles(tmp_path):
    path = tmp_path / backups.DATABASE_NAME
    assert init_db(path) == list(range(1, 22))
    assert init_db(path) == []
    assert not (tmp_path / 'backups').exists()


def test_future_schema_refused_before_migration(tmp_path):
    path = tmp_path / backups.DATABASE_NAME
    init_db(path)
    with closing(get_connection(path)) as conn:
        conn.execute("INSERT INTO schema_migrations VALUES (999, 'future', 'now')")
        conn.commit()
    with pytest.raises(backups.BackupError, match='Unsupported catalog schema'):
        init_db(path)
    assert not (tmp_path / 'backups').exists()


def test_migrator_requires_exclusive_profile_lease(tmp_path):
    path = tmp_path / backups.DATABASE_NAME
    init_db(path)
    with profile_lease(tmp_path), pytest.raises(ProfileBusyError):
        init_db(path)


@pytest.mark.parametrize('failure', ['none', 'sqlite', 'cancelled'])
def test_server_lease_survives_shutdown_until_worker_exits(tmp_path, monkeypatch, failure):
    from backend.main import lifespan
    path = tmp_path / backups.DATABASE_NAME
    fail_shutdown = {'enabled': False}
    if failure == 'sqlite':
        import backend.database
        original = backend.database.get_connection
        def blocked(*args, **kwargs):
            if fail_shutdown['enabled']:
                raise sqlite3.OperationalError('database is locked')
            return original(*args, **kwargs)
        monkeypatch.setattr(backend.database, 'get_connection', blocked)
    async def exercise():
        context = lifespan(SimpleNamespace(state=SimpleNamespace(db_path=path)))
        await context.__aenter__()
        with closing(get_connection(path)) as conn:
            coordinator = coordinator_for(conn)
        token = coordinator.acquire('scanning')
        fail_shutdown['enabled'] = True
        with pytest.raises(ProfileBusyError):
            with profile_lease(tmp_path):
                pass
        shutdown = asyncio.create_task(context.__aexit__(None, None, None))
        try:
            await asyncio.sleep(0.05)
            if failure == 'cancelled':
                shutdown.cancel()
                await asyncio.sleep(0.05)
            assert not shutdown.done()
            with pytest.raises(ProfileBusyError):
                with profile_lease(tmp_path):
                    pass
        finally:
            coordinator.release(token)
            if failure == 'cancelled':
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(shutdown, 5)
            else:
                await asyncio.wait_for(shutdown, 5)
        with profile_lease(tmp_path):
            pass
    asyncio.run(exercise())


def test_registered_artifact_metadata_cannot_be_overwritten(tmp_path):
    path = tmp_path / backups.DATABASE_NAME
    init_db(path)
    with closing(get_connection(path)) as conn:
        conn.execute("INSERT INTO catalog_artifacts VALUES ('id', 'artifacts/evidence', ?, 1, 'evidence', 'now')", ('a' * 64,))
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            conn.execute("UPDATE catalog_artifacts SET sha256=?", ('b' * 64,))
        conn.rollback()
