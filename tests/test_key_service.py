from __future__ import annotations

import json
import os
import socket
import struct
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

from envman._key_provider import (
    StorageKeyProviderError,
    provider_fingerprint,
    read_provider,
    resolve_storage_key,
    write_provider,
)
from envman._key_service import (
    DirectoryKeyRegistry,
    KeyServiceClient,
    KeyServiceError,
    KeyServiceServer,
    KeyUnavailable,
    ServiceEndpoint,
)


def _raw_response(socket_path: Path, payload: bytes | None = None, *, declared_size: int | None = None) -> dict[str, object]:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(1)
    try:
        connection.connect(str(socket_path))
        if declared_size is not None:
            connection.sendall(struct.pack("!H", declared_size))
        elif payload is not None:
            connection.sendall(struct.pack("!H", len(payload)) + payload)
        header = connection.recv(2)
        if len(header) != 2:
            raise AssertionError("server did not return a framed response")
        size = struct.unpack("!H", header)[0]
        body = bytearray()
        while len(body) < size:
            part = connection.recv(size - len(body))
            if not part:
                raise AssertionError("server response ended early")
            body.extend(part)
        return json.loads(body.decode("utf-8"))
    finally:
        connection.close()


class ProviderResolverTests(unittest.TestCase):
    def test_absent_metadata_keeps_the_file_provider_and_existing_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_dir = root / "config"
            state_dir = root / "state"
            config_dir.mkdir()
            metadata_dir = config_dir / "envman"
            metadata_dir.mkdir(mode=0o755)
            metadata_dir.chmod(0o755)
            first = resolve_storage_key(config_dir, state_dir, create=True)

            self.assertEqual(read_provider(config_dir).provider, "file")
            self.assertEqual(resolve_storage_key(config_dir, state_dir), first)
            absent_fingerprint = provider_fingerprint(config_dir)
            metadata_dir.chmod(0o700)
            write_provider(config_dir, "file")
            self.assertEqual(provider_fingerprint(config_dir), absent_fingerprint)

    def test_explicit_metadata_requires_private_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_dir = Path(temporary_directory) / "config"
            metadata_dir = config_dir / "envman"
            metadata_dir.mkdir(parents=True, mode=0o755)
            metadata_dir.chmod(0o755)
            metadata_path = metadata_dir / "storage-provider.json"
            metadata_path.write_text(
                json.dumps({"schema": 1, "provider": "file"}),
                encoding="utf-8",
            )
            metadata_path.chmod(0o600)

            with self.assertRaises(StorageKeyProviderError):
                read_provider(config_dir)

    def test_provider_metadata_is_private_strict_and_changes_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_dir = Path(temporary_directory) / "config"
            metadata_dir = config_dir / "envman"
            metadata_dir.mkdir(parents=True, mode=0o700)
            metadata_dir.chmod(0o700)
            absent_fingerprint = provider_fingerprint(config_dir)
            store_id = str(uuid.uuid4())

            write_provider(config_dir, "service", store_id)

            self.assertEqual(read_provider(config_dir).provider, "service")
            self.assertEqual(read_provider(config_dir).store_id, store_id)
            self.assertNotEqual(provider_fingerprint(config_dir), absent_fingerprint)
            self.assertEqual((metadata_dir / "storage-provider.json").stat().st_mode & 0o777, 0o600)

    def test_malformed_selected_service_never_falls_back_to_file_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_dir = root / "config"
            metadata_dir = config_dir / "envman"
            metadata_dir.mkdir(parents=True, mode=0o700)
            metadata_path = metadata_dir / "storage-provider.json"
            metadata_path.write_text(
                json.dumps({"schema": 1, "provider": "service", "store_id": "bad"}),
                encoding="utf-8",
            )
            metadata_path.chmod(0o600)
            state_dir = root / "state"

            with self.assertRaises(StorageKeyProviderError):
                resolve_storage_key(config_dir, state_dir, create=True)
            self.assertFalse((state_dir / "envman" / "storage.key").exists())

    def test_unavailable_selected_service_never_creates_or_reads_a_file_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_dir = root / "config"
            (config_dir / "envman").mkdir(parents=True, mode=0o700)
            state_dir = root / "state"
            write_provider(config_dir, "service", str(uuid.uuid4()))

            with self.assertRaises(StorageKeyProviderError):
                resolve_storage_key(
                    config_dir,
                    state_dir,
                    service_client=_UnavailableClient(),
                )
            with self.assertRaises(StorageKeyProviderError):
                resolve_storage_key(config_dir, state_dir, create=True)
            self.assertFalse((state_dir / "envman" / "storage.key").exists())


class _UnavailableClient:
    def get_key(self, store_id: str) -> bytes:
        raise KeyUnavailable("fixture unavailable")


class KeyServiceTests(unittest.TestCase):
    def test_registry_admin_gate_rejects_non_admin_enrollment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_dir = Path(temporary_directory) / "registry"
            state_dir.mkdir(mode=0o700)
            registry = DirectoryKeyRegistry.for_test(
                state_dir,
                os.getuid(),
                identity_for_uid=lambda _uid: "e" * 64,
                admin_authorizer=lambda: False,  # explicit denied fixture trust
            )
            with self.assertRaises(KeyServiceError):
                registry.enroll(os.getuid(), str(uuid.uuid4()), Fernet.generate_key())

    def test_real_unix_socket_retrieves_only_enrolled_uid_store_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "registry"
            state_dir.mkdir(mode=0o700)
            store_id = str(uuid.uuid4())
            other_store = str(uuid.uuid4())
            key = Fernet.generate_key()
            identity = "a" * 64
            registry = DirectoryKeyRegistry.for_test(
                state_dir,
                os.getuid(),
                identity_for_uid=lambda _uid: identity,
                admin_authorizer=lambda: True,  # explicit fixture trust injection
            )
            self.assertTrue(registry.enroll(os.getuid(), store_id, key))
            self.assertFalse(registry.enroll(os.getuid(), store_id, key))
            with self.assertRaises(KeyServiceError):
                registry.enroll(os.getuid(), store_id, Fernet.generate_key())

            socket_path = root / "key-service.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_path))
            listener.listen(8)
            server = KeyServiceServer(listener, registry)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            endpoint = ServiceEndpoint.for_test(
                socket_path,
                state_dir=state_dir,
                service_uid=os.getuid(),
            )
            client = KeyServiceClient(endpoint, timeout=1.0)
            try:
                # SO_PEERCRED is real kernel data for this local socket. The
                # registry account fingerprint and admin gate are fixture-injected.
                self.assertEqual(client.get_key(store_id), key)
                with self.assertRaises(KeyUnavailable):
                    client.get_key(other_store)

                config_dir = root / "config"
                (config_dir / "envman").mkdir(parents=True, mode=0o700)
                write_provider(config_dir, "service", store_id)
                self.assertEqual(
                    resolve_storage_key(config_dir, root / "user-state", service_client=client),
                    key,
                )
                forged_uid = json.dumps(
                    {"v": 1, "uid": os.getuid(), "store_id": store_id},
                    separators=(",", ":"),
                ).encode("ascii")
                self.assertEqual(
                    _raw_response(socket_path, forged_uid),
                    {"error": "unavailable", "v": 1},
                )
                self.assertEqual(
                    _raw_response(socket_path, declared_size=129),
                    {"error": "unavailable", "v": 1},
                )

                with self.assertRaises(KeyServiceError):
                    KeyServiceClient(
                        ServiceEndpoint.for_test(
                            socket_path,
                            state_dir=state_dir,
                            service_uid=os.getuid() + 1,
                        ),
                        timeout=1.0,
                    ).get_key(store_id)
            finally:
                server.close()
                server_thread.join(timeout=2)

    def test_retirement_denies_retrieval_and_account_change_requires_fresh_enrollment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_dir = Path(temporary_directory) / "registry"
            state_dir.mkdir(mode=0o700)
            current = {"fingerprint": "b" * 64}
            registry = DirectoryKeyRegistry.for_test(
                state_dir,
                os.getuid(),
                identity_for_uid=lambda _uid: current["fingerprint"],
                admin_authorizer=lambda: True,  # explicit fixture trust injection
            )
            store_id = str(uuid.uuid4())
            key = Fernet.generate_key()
            registry.enroll(os.getuid(), store_id, key)
            self.assertEqual(registry.retrieve(os.getuid(), store_id), key)

            current["fingerprint"] = "c" * 64
            with self.assertRaises(KeyUnavailable):
                registry.retrieve(os.getuid(), store_id)
            self.assertTrue(registry.retire(os.getuid(), store_id))
            self.assertFalse(registry.retire(os.getuid(), store_id))
            with self.assertRaises(KeyUnavailable):
                registry.retrieve(os.getuid(), store_id)
            with self.assertRaises(KeyServiceError):
                registry.enroll(os.getuid(), store_id, Fernet.generate_key())
            fresh_store_id = str(uuid.uuid4())
            fresh_key = Fernet.generate_key()
            self.assertTrue(registry.enroll(os.getuid(), fresh_store_id, fresh_key))
            self.assertEqual(registry.retrieve(os.getuid(), fresh_store_id), fresh_key)

    def test_client_checks_server_peer_identity_from_kernel_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            registry_dir = root / "registry"
            registry_dir.mkdir(mode=0o700)
            registry = DirectoryKeyRegistry.for_test(
                registry_dir,
                os.getuid(),
                identity_for_uid=lambda _uid: "d" * 64,
                admin_authorizer=lambda: True,
            )
            store_id = str(uuid.uuid4())
            registry.enroll(os.getuid(), store_id, Fernet.generate_key())
            socket_path = root / "key-service.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_path))
            listener.listen(4)
            server = KeyServiceServer(listener, registry)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                wrong_trust = ServiceEndpoint.for_test(
                    socket_path,
                    state_dir=registry_dir,
                    service_uid=os.getuid() + 1,
                )
                with self.assertRaises(KeyServiceError):
                    KeyServiceClient(wrong_trust, timeout=1).get_key(store_id)
            finally:
                server.close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
