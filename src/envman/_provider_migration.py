"""Private, resumable progress for explicit storage-provider migration."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator

from ._key_provider import provider_fingerprint
from ._secure_store import (
    SecureStoreError,
    _open_directory,
    _write_all,
    atomic_write_private,
    decrypt_document,
    encrypt_document,
    is_encrypted_document,
    load_or_create_file_key,
    safe_read,
)


PROGRESS_NAME = "storage-provider-migration.json"
PROGRESS_SCHEMA = 1
MAX_PROGRESS_BYTES = 4096
_PHASES = frozenset({"enrollment-pending", "cleanup-pending", "file-activation-pending"})


class ProviderMigrationError(Exception):
    """Raised when provider migration state cannot be reconciled safely."""


@dataclass(frozen=True)
class MigrationProgress:
    source_provider: str
    target_provider: str
    store_id: str
    key_fingerprint: str
    phase: str
    recovery_export_path: str | None = None
    recovery_export_sha256: str | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "schema": PROGRESS_SCHEMA,
            "source_provider": self.source_provider,
            "target_provider": self.target_provider,
            "store_id": self.store_id,
            "key_fingerprint": self.key_fingerprint,
            "phase": self.phase,
            "recovery_export_path": self.recovery_export_path,
            "recovery_export_sha256": self.recovery_export_sha256,
        }


def migration_progress_path(config_dir: Path) -> Path:
    return Path(config_dir) / "envman" / PROGRESS_NAME


def key_fingerprint(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()


def new_service_progress(key: bytes, store_id: str | None = None) -> MigrationProgress:
    identifier = store_id or str(uuid.uuid4())
    try:
        if str(uuid.UUID(identifier)) != identifier:
            raise ValueError
    except (ValueError, AttributeError):
        raise ProviderMigrationError("Storage migration identifier is invalid.") from None
    return MigrationProgress(
        source_provider="file",
        target_provider="service",
        store_id=identifier,
        key_fingerprint=key_fingerprint(key),
        phase="enrollment-pending",
    )


def new_file_progress(key: bytes, store_id: str) -> MigrationProgress:
    try:
        if str(uuid.UUID(store_id)) != store_id:
            raise ValueError
    except (ValueError, AttributeError):
        raise ProviderMigrationError("Storage migration identifier is invalid.") from None
    return MigrationProgress(
        source_provider="service",
        target_provider="file",
        store_id=store_id,
        key_fingerprint=key_fingerprint(key),
        phase="file-activation-pending",
    )


def read_migration_progress(config_dir: Path) -> MigrationProgress | None:
    path = migration_progress_path(config_dir)
    if path.is_symlink():
        raise ProviderMigrationError("Storage migration progress path is unsafe.")
    try:
        if not path.exists():
            return None
        raw = safe_read(path, MAX_PROGRESS_BYTES, expected_mode=0o600)
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, SecureStoreError):
        raise ProviderMigrationError("Storage migration progress is malformed or unsafe.") from None
    if not isinstance(document, dict) or set(document) != {
        "schema",
        "source_provider",
        "target_provider",
        "store_id",
        "key_fingerprint",
        "phase",
        "recovery_export_path",
        "recovery_export_sha256",
    }:
        raise ProviderMigrationError("Storage migration progress is malformed.")
    source = document.get("source_provider")
    target = document.get("target_provider")
    store_id = document.get("store_id")
    fingerprint = document.get("key_fingerprint")
    phase = document.get("phase")
    export_path = document.get("recovery_export_path")
    export_hash = document.get("recovery_export_sha256")
    try:
        if type(document.get("schema")) is not int or document["schema"] != PROGRESS_SCHEMA:
            raise ValueError
        if source not in {"file", "service"} or target not in {"file", "service"} or source == target:
            raise ValueError
        if not isinstance(store_id, str) or str(uuid.UUID(store_id)) != store_id:
            raise ValueError
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise ValueError
        if phase not in _PHASES:
            raise ValueError
        if export_path is not None and (not isinstance(export_path, str) or not Path(export_path).is_absolute()):
            raise ValueError
        if export_hash is not None and (
            not isinstance(export_hash, str)
            or len(export_hash) != 64
            or any(character not in "0123456789abcdef" for character in export_hash)
        ):
            raise ValueError
        if (export_path is None) != (export_hash is None):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ProviderMigrationError("Storage migration progress is invalid.") from None
    return MigrationProgress(
        source,
        target,
        store_id,
        fingerprint,
        phase,
        export_path,
        export_hash,
    )


def write_migration_progress(config_dir: Path, progress: MigrationProgress) -> None:
    try:
        payload = json.dumps(progress.as_json(), sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
        atomic_write_private(migration_progress_path(config_dir), payload)
    except (OSError, SecureStoreError, UnicodeEncodeError):
        raise ProviderMigrationError("Cannot persist storage migration progress safely.") from None


def attach_recovery_export(
    progress: MigrationProgress,
    path: Path,
    digest: str,
) -> MigrationProgress:
    resolved = Path(path).absolute()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ProviderMigrationError("Recovery export fingerprint is invalid.")
    return replace(progress, recovery_export_path=str(resolved), recovery_export_sha256=digest)


def remove_migration_progress(config_dir: Path) -> None:
    path = migration_progress_path(config_dir)
    try:
        if path.is_symlink():
            raise ProviderMigrationError("Storage migration progress path is unsafe.")
        if not path.exists():
            return
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ProviderMigrationError("Storage migration progress file is unsafe.")
        directory_fd = _open_directory(path.parent, private=True)
        try:
            os.unlink(path.name, dir_fd=directory_fd)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except ProviderMigrationError:
        raise
    except OSError:
        raise ProviderMigrationError("Cannot clear storage migration progress safely.") from None


@contextmanager
def environment_store_lock(lock_path: Path) -> Iterator[None]:
    """Serialize document/provider checks and migration activation and cleanup."""
    descriptor: int | None = None
    try:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise ProviderMigrationError("Environment write lock is not a private regular file.")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except ProviderMigrationError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        raise ProviderMigrationError("Cannot lock the environment store for provider migration.") from None
    try:
        yield
    finally:
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def revalidate_loaded_store(store: object) -> None:
    """Fail if the document or provider changed after this store was loaded."""
    target = Path(getattr(store, "target"))
    expected_document = getattr(store, "_loaded_fingerprint")
    expected_provider = getattr(store, "_loaded_provider_fingerprint")
    try:
        current = safe_read(target, 8 * 1024 * 1024) if target.exists() else None
        current_document = hashlib.sha256(current).digest() if current is not None else None
        current_provider = provider_fingerprint(Path(getattr(store, "config_home")))
    except (OSError, SecureStoreError, ValueError):
        raise ProviderMigrationError("Cannot safely revalidate the environment store.") from None
    if current_document != expected_document or current_provider != expected_provider:
        raise ProviderMigrationError("Managed environment or storage provider changed; reload before migrating.")


def verify_encrypted_snapshots(backup_dir: Path, key: bytes) -> int:
    """Authenticate every environment snapshot without changing the archive set."""
    from . import _snapshot_migration as snapshots

    try:
        encrypt_document(b"", key)
        directory_fd = snapshots._open_backup_directory(Path(backup_dir))
        if directory_fd is None:
            return 0
        try:
            names = sorted(name for name in os.listdir(directory_fd) if snapshots._is_snapshot_name(name))
            for name in names:
                archive = snapshots._read_archive(directory_fd, name)
                contents, _ = snapshots._read_environment_member(archive)
                if not is_encrypted_document(contents):
                    raise ProviderMigrationError("Plaintext environment snapshots remain; migrate them before activation.")
                decrypt_document(contents, key)
            return len(names)
        finally:
            os.close(directory_fd)
    except ProviderMigrationError:
        raise
    except (OSError, SecureStoreError, ValueError):
        raise ProviderMigrationError("Cannot verify historical environment snapshots safely.") from None


def install_file_key_if_missing(path: Path, key: bytes) -> None:
    """Install the existing service key for explicit return to file mode."""
    try:
        encrypt_document(b"", key)
        key_path = Path(path)
        if key_path.name in {"", ".", ".."} or key_path.is_symlink():
            raise ProviderMigrationError("Storage key destination is unsafe.")
        if key_path.exists():
            existing = load_or_create_file_key(key_path, create=False)
            if existing != key:
                raise ProviderMigrationError("An existing file storage key differs; it was preserved.")
            return
        directory_fd = _open_directory(key_path.parent, create=True, private=True)
        descriptor: int | None = None
        temporary_name: str | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            for _ in range(16):
                candidate = f".envman-storage-key-{secrets.token_hex(16)}.tmp"
                try:
                    descriptor = os.open(candidate, flags, 0o600, dir_fd=directory_fd)
                    temporary_name = candidate
                    break
                except FileExistsError:
                    continue
            if descriptor is None or temporary_name is None:
                raise ProviderMigrationError("Cannot allocate a private storage-key temporary file.")
            _write_all(descriptor, key)
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            try:
                os.link(
                    temporary_name,
                    key_path.name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                os.fsync(directory_fd)
            except FileExistsError:
                existing = load_or_create_file_key(key_path, create=False)
                if existing != key:
                    raise ProviderMigrationError("An existing file storage key differs; it was preserved.")
            os.unlink(temporary_name, dir_fd=directory_fd)
            temporary_name = None
            os.fsync(directory_fd)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name, dir_fd=directory_fd)
                    os.fsync(directory_fd)
                except OSError:
                    pass
            os.close(directory_fd)
    except ProviderMigrationError:
        raise
    except (OSError, SecureStoreError):
        raise ProviderMigrationError("Cannot safely install the existing storage key for file mode.") from None


def remove_file_key(path: Path, expected_fingerprint: str) -> bool:
    """Remove only the old file key after service activation and verification."""
    key_path = Path(path)
    try:
        try:
            metadata = key_path.lstat()
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise ProviderMigrationError("Storage key file is unsafe; cleanup was not performed.")
        key = load_or_create_file_key(key_path, create=False)
        if key_fingerprint(key) != expected_fingerprint:
            raise ProviderMigrationError("Storage key changed since migration preparation; cleanup was not performed.")
        directory_fd = _open_directory(key_path.parent, private=True)
        try:
            current = os.stat(key_path.name, dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode) or current.st_uid != os.getuid() or stat.S_IMODE(current.st_mode) != 0o600:
                raise ProviderMigrationError("Storage key file is unsafe; cleanup was not performed.")
            os.unlink(key_path.name, dir_fd=directory_fd)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return True
    except ProviderMigrationError:
        raise
    except (OSError, SecureStoreError):
        raise ProviderMigrationError("Cannot remove the old storage key safely.") from None
