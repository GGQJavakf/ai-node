"""SQLite schema migration mechanics used by the repository facade."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def migrate_repository(repository: Any, target_version: int, schema_version: int) -> None:
    """Migrate through repository seams while preserving one writer fence."""

    _validate_target(target_version)
    created_database = _prepare_database(repository.db_path)
    connection = None
    backup_path = None
    current_version = 0
    try:
        connection = repository._connect()
        connection.execute("BEGIN IMMEDIATE")
        current_version = repository._schema_version(connection)
        created_database = created_database and current_version == 0
        _validate_direction(current_version, target_version)
        if current_version == target_version:
            connection.rollback()
            connection.close()
            return
        backup_path = _backup_existing_database(
            repository,
            created_database,
            current_version,
            target_version,
        )
        _apply_versions(repository, connection, current_version, target_version)
        connection.commit()
    except BaseException:
        _close_failed_connection(connection)
        _verify_failed_migration(
            repository,
            created_database,
            backup_path,
            current_version,
        )
        raise
    else:
        connection.close()


def create_migration_backup(
    db_path: Path, backup_path: Path, sqlite_module: Any
) -> None:
    """Create and quick-check one logical SQLite backup."""

    if backup_path.exists():
        raise FileExistsError(f"migration backup already exists: {backup_path}")
    source = None
    destination = None
    backup_complete = False
    backup_created = False
    try:
        source = sqlite_module.connect(db_path)
        destination = sqlite_module.connect(backup_path)
        backup_created = True
        source.backup(destination)
        result = destination.execute("PRAGMA quick_check").fetchone()
        if result is None or str(result[0]).lower() != "ok":
            raise RuntimeError("migration backup failed readback")
        destination.commit()
        backup_complete = True
    finally:
        _close_connections(destination, source)
        if backup_created and not backup_complete:
            _remove_backup_files(backup_path)
    if not backup_path.exists():
        raise RuntimeError("migration backup was not created")


def verify_database_readback(
    db_path: Path,
    expected_version: int,
    sqlite_module: Any,
    schema_version_reader: Callable[[Any], int],
) -> None:
    connection = sqlite_module.connect(db_path)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result is None or str(result[0]).lower() != "ok":
            raise RuntimeError("migration rollback failed readback")
        if schema_version_reader(connection) != expected_version:
            raise RuntimeError("migration rollback did not restore the schema version")
    finally:
        connection.close()


def remove_database_sidecars(db_path: Path) -> None:
    for path in _database_files(db_path)[1:]:
        path.unlink(missing_ok=True)


def remove_failed_database(db_path: Path) -> None:
    db_path.unlink(missing_ok=True)
    remove_database_sidecars(db_path)


def _validate_target(target_version: int) -> None:
    if target_version < 1:
        raise ValueError("target_version must be at least 1")


def _prepare_database(db_path: Path) -> bool:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        return False
    try:
        db_path.touch(exist_ok=False)
    except FileExistsError:
        return False
    return True


def _validate_direction(current_version: int, target_version: int) -> None:
    if current_version > target_version:
        raise ValueError("database downgrades are not supported")


def _backup_existing_database(
    repository: Any,
    created_database: bool,
    current_version: int,
    target_version: int,
) -> Path | None:
    if created_database:
        return None
    repository.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = repository.backup_dir / (
        f"migration-{current_version}-to-{target_version}-{stamp}.db"
    )
    repository._create_migration_backup(backup_path)
    return backup_path


def _apply_versions(
    repository: Any,
    connection: Any,
    current_version: int,
    target_version: int,
) -> None:
    for version in range(current_version + 1, target_version + 1):
        repository._apply_migration(connection, version)
        repository._append_audit_record(
            connection,
            repository._audit_entry(
                action="migration_applied",
                entity_type="schema",
                entity_id=str(version),
                before_hash=str(version - 1),
                after_hash=str(version),
                detail={"from": version - 1, "to": version},
            ),
        )


def _close_failed_connection(connection: Any | None) -> None:
    if connection is None:
        return
    try:
        connection.rollback()
    except BaseException:
        pass
    try:
        connection.close()
    except BaseException:
        pass


def _verify_failed_migration(
    repository: Any,
    created_database: bool,
    backup_path: Path | None,
    current_version: int,
) -> None:
    if created_database:
        repository._remove_failed_database()
        return
    if backup_path is None or not backup_path.exists():
        return
    try:
        repository._verify_database_readback(current_version)
    except BaseException as recovery_error:
        raise RuntimeError(
            "migration rollback verification failed; verified backup retained"
        ) from recovery_error


def _close_connections(*connections: Any | None) -> None:
    for connection in connections:
        if connection is not None:
            connection.close()


def _remove_backup_files(backup_path: Path) -> None:
    for path in _database_files(backup_path):
        path.unlink(missing_ok=True)


def _database_files(db_path: Path) -> tuple[Path, ...]:
    return (
        db_path,
        Path(f"{db_path}-journal"),
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    )
