"""Focused provider migration, interruption, and recovery regressions."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet

from envman import cli
from envman._key_provider import read_provider, write_provider
from envman._provider_migration import (
    ProviderMigrationError,
    attach_recovery_export,
    install_file_key_if_missing,
    key_fingerprint,
    new_file_progress,
    new_service_progress,
    read_migration_progress,
    write_migration_progress,
)
from envman._secure_store import (
    _write_all as secure_write_all,
    atomic_write_private,
    encrypt_document,
    load_or_create_file_key,
    safe_read,
)


class _ServiceClient:
    def __init__(self, keys: dict[str, bytes]) -> None:
        self.keys = keys

    def get_key(self, store_id: str) -> bytes:
        try:
            return self.keys[store_id]
        except KeyError:
            raise ValueError("synthetic service key unavailable") from None


class ProviderMigrationTests(unittest.TestCase):
    def _store(self, root: Path, *, client: _ServiceClient | None = None) -> cli.EnvironmentStore:
        home = root / "home"
        home.mkdir(parents=True, exist_ok=True)
        store = cli.EnvironmentStore(home, home / ".config", _service_client=client)
        store.utility_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        store.utility_dir.chmod(0o700)
        store.install_loaders = mock.Mock()  # Keep CLI migration tests inside the synthetic home.
        return store

    def _arguments(
        self,
        *,
        provider: str,
        apply: bool = True,
        prepare: bool = False,
        recovery_export: Path | None = None,
        remove_file_key: bool = False,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            command="migrate-storage",
            provider=provider,
            apply=apply,
            prepare=prepare,
            recovery_export=None if recovery_export is None else str(recovery_export),
            remove_file_key=remove_file_key,
            json=True,
        )

    def test_file_to_service_migration_and_clean_home_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            recovery = root / "independent-recovery.json"
            env = {
                "XDG_STATE_HOME": str(root / "state"),
                cli.BACKUP_KEY_ENV: "synthetic recovery password",
            }
            with mock.patch.dict(os.environ, env):
                store = self._store(root)
                store.target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                store.backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
                legacy_snapshot = store.backup_dir / "environment.conf.20200101T000000Z.tar.gz"
                with tarfile.open(legacy_snapshot, "w:gz") as archive:
                    old_content = b"API_TOKEN=older-value\n"
                    old_member = tarfile.TarInfo("environment.conf")
                    old_member.size = len(old_content)
                    archive.addfile(old_member, io.BytesIO(old_content))
                legacy_snapshot.chmod(0o600)
                store.target.write_bytes(b"API_TOKEN=active-value\nEMPTY=\n")
                store.target.chmod(0o600)
                store.load(allow_legacy_with_key=True)

                prepared_output = io.StringIO()
                with contextlib.redirect_stdout(prepared_output):
                    self.assertEqual(
                        cli.run_cli(
                            self._arguments(provider="service", prepare=True),
                            store,
                        ),
                        cli.EXIT_SUCCESS,
                    )
                prepared = json.loads(prepared_output.getvalue())
                self.assertEqual(prepared["action"], "enrollment-prepared")
                self.assertIn("admin-enroll", prepared["admin_command"])
                progress = read_migration_progress(store.config_home)
                self.assertIsNotNone(progress)
                assert progress is not None
                key = load_or_create_file_key(store.storage_key_path, create=False)
                self.assertEqual(progress.key_fingerprint, key_fingerprint(key))
                store._service_client = _ServiceClient({progress.store_id: key})

                interrupted_output = io.StringIO()
                with (
                    contextlib.redirect_stdout(interrupted_output),
                    mock.patch.object(
                        cli,
                        "remove_file_key",
                        side_effect=ProviderMigrationError("synthetic cleanup interruption"),
                    ),
                    self.assertRaises(cli.CommandError),
                ):
                    cli.run_cli(
                        self._arguments(
                            provider="service",
                            recovery_export=recovery,
                            remove_file_key=True,
                        ),
                        store,
                    )
                self.assertEqual(interrupted_output.getvalue(), "")
                self.assertEqual(read_provider(store.config_home).provider, "service")
                self.assertTrue(store.storage_key_path.exists())
                cleanup_progress = read_migration_progress(store.config_home)
                self.assertIsNotNone(cleanup_progress)
                assert cleanup_progress is not None
                self.assertEqual(cleanup_progress.phase, "cleanup-pending")

                # A fresh CLI store resumes the same persisted identity and
                # export, completing only the explicit old-key cleanup.
                store = self._store(root, client=store._service_client)
                store.load()
                activated_output = io.StringIO()
                with contextlib.redirect_stdout(activated_output):
                    self.assertEqual(
                        cli.run_cli(
                            self._arguments(
                                provider="service",
                                recovery_export=recovery,
                                remove_file_key=True,
                            ),
                            store,
                        ),
                        cli.EXIT_SUCCESS,
                    )
                activated = json.loads(activated_output.getvalue())
                self.assertEqual(activated["action"], "provider-activated")
                self.assertEqual(read_provider(store.config_home).provider, "service")
                self.assertEqual(read_provider(store.config_home).store_id, progress.store_id)
                self.assertFalse(store.storage_key_path.exists())
                self.assertIsNone(read_migration_progress(store.config_home))
                self.assertEqual(
                    cli.encrypted_backup_variables(recovery, key_path=None),
                    {"API_TOKEN": "active-value", "EMPTY": ""},
                )
                with tarfile.open(legacy_snapshot, "r:gz") as archive:
                    member = archive.extractfile("environment.conf")
                    assert member is not None
                    encrypted_old = member.read()
                self.assertTrue(cli.is_encrypted_document(encrypted_old))
                self.assertEqual(cli.decrypt_document(encrypted_old, key), old_content)

                # Restore from the independent export into a clean home using
                # only the explicit recovery credential.
                with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(root / "restore-state")}):
                    clean_home = self._store(root / "restore")
                    clean_home.load()
                    restore_args = argparse.Namespace(
                        command="import-backup",
                        names=[],
                        all=True,
                        apply=True,
                        replace=False,
                        force=False,
                        json=True,
                        path=str(recovery),
                    )
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(cli.run_cli(restore_args, clean_home), cli.EXIT_SUCCESS)
                    restored = self._store(root / "restore")
                    restored.load()
                    self.assertEqual(restored.values, {"API_TOKEN": "active-value", "EMPTY": ""})

    def test_service_key_failure_creates_no_export_and_emits_no_partial_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            recovery = root / "must-not-exist.json"
            env = {
                "XDG_STATE_HOME": str(root / "state"),
                cli.BACKUP_KEY_ENV: "synthetic recovery password",
            }
            with mock.patch.dict(os.environ, env):
                store = self._store(root)
                store.target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                store.target.write_bytes(b"SECRET_VALUE=synthetic\n")
                store.target.chmod(0o600)
                store.load(allow_legacy_with_key=True)
                with contextlib.redirect_stdout(io.StringIO()):
                    cli.run_cli(self._arguments(provider="service", prepare=True), store)
                progress = read_migration_progress(store.config_home)
                assert progress is not None
                store._service_client = _ServiceClient({})

                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(cli.CommandError):
                    cli.run_cli(
                        self._arguments(
                            provider="service",
                            recovery_export=recovery,
                            remove_file_key=True,
                        ),
                        store,
                    )
                self.assertEqual(output.getvalue(), "")
                self.assertFalse(recovery.exists())
                self.assertTrue(store.storage_key_path.exists())
                self.assertEqual(read_provider(store.config_home).provider, "file")

    def test_unrecorded_existing_recovery_export_is_verified_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "recovery.json"
            env = {cli.BACKUP_KEY_ENV: "synthetic recovery password"}
            key = Fernet.generate_key()
            values = {"NAME": "current", "EMPTY": ""}
            with mock.patch.dict(os.environ, env):
                cli.write_encrypted_backup(destination, values, key_path=None, exclusive=True)
                before = safe_read(destination, cli.MAX_ENCRYPTED_BACKUP_BYTES, expected_mode=0o600)
                progress = new_service_progress(key, str(uuid.uuid4()))

                reconciled, digest, summary = cli._recovery_export(str(destination), values, progress)

                self.assertEqual(reconciled, destination)
                self.assertEqual(summary["sha256"], digest)
                self.assertEqual(before, safe_read(destination, cli.MAX_ENCRYPTED_BACKUP_BYTES, expected_mode=0o600))
                self.assertEqual(cli.encrypted_backup_variables(destination, key_path=None), values)

    def test_interrupted_file_activation_is_reconciled_and_reports_retirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            recovery = root / "recovery.json"
            env = {
                "XDG_STATE_HOME": str(root / "state"),
                cli.BACKUP_KEY_ENV: "synthetic recovery password",
            }
            with mock.patch.dict(os.environ, env):
                store = self._store(root)
                store.target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                store.values = {"SERVICE_VALUE": "kept"}
                key = Fernet.generate_key()
                atomic_write_private(store.target, encrypt_document(b"SERVICE_VALUE=kept\n", key))
                store.target.chmod(0o600)
                store_id = str(uuid.uuid4())
                write_provider(store.config_home, "file")
                install_file_key_if_missing(store.storage_key_path, key)
                cli.write_encrypted_backup(recovery, store.values, key_path=None, exclusive=True)
                raw_export = safe_read(recovery, cli.MAX_ENCRYPTED_BACKUP_BYTES, expected_mode=0o600)
                progress = attach_recovery_export(
                    new_file_progress(key, store_id),
                    recovery,
                    hashlib.sha256(raw_export).hexdigest(),
                )
                write_migration_progress(store.config_home, progress)
                store.load()

                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    cli.run_cli(
                        self._arguments(provider="file", recovery_export=recovery),
                        store,
                    )
                result = json.loads(output.getvalue())
                self.assertEqual(result["action"], "provider-returned-to-file")
                self.assertEqual(result["retired_store_id"], store_id)
                self.assertIn("admin-retire", result["admin_retirement_command"])
                self.assertEqual(result["provider"], "file")
                self.assertIsNone(read_migration_progress(store.config_home))

    def test_provider_legacy_snapshot_migration_never_creates_file_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            key = Fernet.generate_key()
            store_id = str(uuid.uuid4())
            env = {"XDG_STATE_HOME": str(root / "state")}
            with mock.patch.dict(os.environ, env):
                store = self._store(root, client=_ServiceClient({store_id: key}))
                write_provider(store.config_home, "service", store_id)
                store.backup_dir.mkdir(parents=True, mode=0o700)
                archive_path = store.backup_dir / "environment.conf.20200101T000000Z.tar.gz"
                with tarfile.open(archive_path, "w:gz") as archive:
                    content = b"OLD_VALUE=historical\n"
                    member = tarfile.TarInfo("environment.conf")
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
                archive_path.chmod(0o600)
                store.load(allow_legacy_with_key=True)

                with contextlib.redirect_stdout(io.StringIO()):
                    cli.run_cli(
                        argparse.Namespace(
                            command="migrate-storage",
                            provider=None,
                            apply=True,
                            prepare=False,
                            recovery_export=None,
                            remove_file_key=False,
                            json=True,
                        ),
                        store,
                    )

                self.assertFalse(store.storage_key_path.exists())
                with tarfile.open(archive_path, "r:gz") as archive:
                    member = archive.extractfile("environment.conf")
                    assert member is not None
                    content = member.read()
                self.assertTrue(cli.is_encrypted_document(content))
                self.assertEqual(cli.decrypt_document(content, key), b"OLD_VALUE=historical\n")

    def test_file_key_install_interruption_leaves_no_partial_destination_and_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            key_path = Path(temporary_directory) / "state" / "envman" / "storage.key"
            key = Fernet.generate_key()
            original_write = secure_write_all
            calls = 0

            def interrupted_write(descriptor: int, content: bytes) -> None:
                nonlocal calls
                calls += 1
                original_write(descriptor, content)
                if calls == 1:
                    raise OSError("synthetic interrupted write")

            with mock.patch("envman._provider_migration._write_all", side_effect=interrupted_write):
                with self.assertRaises(ProviderMigrationError):
                    install_file_key_if_missing(key_path, key)
            self.assertFalse(key_path.exists())
            self.assertEqual(list(key_path.parent.glob(".envman-storage-key-*.tmp")), [])

            install_file_key_if_missing(key_path, key)
            self.assertEqual(load_or_create_file_key(key_path, create=False), key)


if __name__ == "__main__":
    unittest.main()
