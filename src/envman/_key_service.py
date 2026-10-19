"""Offline local Unix-socket service for Envman storage keys.

The public socket supports retrieval only. Enrollment and retirement are
root-only local administration operations and are never protocol messages.
This module is designed to be copied with Envman's retained runtime and run
with ``python -I`` from its root-owned installation directory.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import fcntl
import hashlib
import json
import os
import pwd
import re
import resource
import select
import signal
import socket
import stat
import struct
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


SYSTEM_CONFIG_PATH = Path("/etc/envman/key-service.json")
PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 128
MAX_RESPONSE_BYTES = 256
MAX_ACTIVE_CLIENTS = 8
DEFAULT_TIMEOUT_SECONDS = 0.5
_MAX_RECORD_BYTES = 1024
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class KeyServiceError(ValueError):
    """Raised for unsafe service configuration, protocol, or registry state."""


class KeyUnavailable(KeyServiceError):
    """Raised when the peer cannot retrieve its enrolled storage key."""


@dataclass(frozen=True)
class PeerCredentials:
    pid: int
    uid: int
    gid: int


@dataclass(frozen=True)
class ServiceEndpoint:
    """Trusted endpoint parameters read from administrator-owned config."""

    socket_path: Path
    state_dir: Path
    service_uid: int
    allow_root_peer: bool = False
    _from_system_config: bool = field(default=False, repr=False, compare=False)

    @classmethod
    def from_system_config(cls) -> ServiceEndpoint:
        return _load_system_endpoint(SYSTEM_CONFIG_PATH)

    @classmethod
    def for_test(
        cls,
        socket_path: Path,
        *,
        state_dir: Path,
        service_uid: int,
        allow_root_peer: bool = False,
    ) -> ServiceEndpoint:
        """Build explicit local test trust; never use this for installed clients."""
        return cls(
            Path(socket_path),
            Path(state_dir),
            service_uid,
            allow_root_peer,
            _from_system_config=False,
        )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _json_bytes(data: bytes, *, limit: int) -> dict[str, object]:
    if not data or len(data) > limit:
        raise KeyServiceError("Key service message is invalid.")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise KeyServiceError("Key service message is invalid.") from None
    if not isinstance(value, dict):
        raise KeyServiceError("Key service message is invalid.")
    return value


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise KeyServiceError("Store identifier is invalid.")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise KeyServiceError("Store identifier is invalid.") from None
    if str(parsed) != value:
        raise KeyServiceError("Store identifier is invalid.")
    return value


def _validate_key(key: bytes) -> bytes:
    if not isinstance(key, bytes) or len(key) != 44:
        raise KeyServiceError("Storage key is malformed.")
    try:
        decoded = base64.b64decode(key, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise KeyServiceError("Storage key is malformed.") from None
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded) != key:
        raise KeyServiceError("Storage key is malformed.")
    return key


def account_fingerprint(uid: int) -> str:
    """Fingerprint the current passwd identity so changed/reused UIDs fail closed.

    Linux does not expose an account-creation generation number through the
    passwd database. Administrators must retire and freshly enroll a UID when
    its account lifecycle changes; this fingerprint detects changed account
    records and prevents changed passwd identities inheriting an old key.
    """
    if type(uid) is not int or uid < 0:
        raise KeyUnavailable("Account identity is unavailable.")
    try:
        entry = pwd.getpwuid(uid)
    except KeyError:
        raise KeyUnavailable("Account identity is unavailable.") from None
    fields = (
        entry.pw_name,
        str(entry.pw_uid),
        str(entry.pw_gid),
        entry.pw_gecos,
        entry.pw_dir,
        entry.pw_shell,
    )
    content = b"\0".join(value.encode("utf-8", "surrogateescape") for value in fields)
    return hashlib.sha256(content).hexdigest()


def peer_credentials(connection: socket.socket) -> PeerCredentials:
    """Return kernel-authenticated Unix peer credentials; never parse request UID."""
    option = getattr(socket, "SO_PEERCRED", None)
    if option is None:
        raise KeyServiceError("Kernel peer credentials are unavailable.")
    try:
        raw = connection.getsockopt(socket.SOL_SOCKET, option, struct.calcsize("3i"))
    except OSError:
        raise KeyServiceError("Kernel peer credentials are unavailable.") from None
    if len(raw) != struct.calcsize("3i"):
        raise KeyServiceError("Kernel peer credentials are malformed.")
    pid, uid, gid = struct.unpack("3i", raw)
    if pid <= 0 or uid < 0 or gid < 0:
        raise KeyServiceError("Kernel peer credentials are malformed.")
    return PeerCredentials(pid, uid, gid)


def _read_bounded(fd: int, limit: int, *, timeout: float) -> bytes:
    """Read a bounded fd to EOF or its size limit within one wall-clock bound."""
    if type(fd) is not int or fd < 0 or type(limit) is not int or limit <= 0:
        raise KeyServiceError("Private key input descriptor is invalid.")
    deadline = time.monotonic() + timeout
    pieces = bytearray()
    while len(pieces) <= limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise KeyServiceError("Private key input timed out.")
        try:
            readable, _, _ = select.select([fd], [], [], remaining)
        except (OSError, ValueError):
            raise KeyServiceError("Private key input descriptor is invalid.") from None
        if not readable:
            raise KeyServiceError("Private key input timed out.")
        try:
            chunk = os.read(fd, min(256, limit + 1 - len(pieces)))
        except OSError:
            raise KeyServiceError("Cannot read private key input.") from None
        if not chunk:
            return bytes(pieces)
        pieces.extend(chunk)
    raise KeyServiceError("Private key input exceeds its size limit.")


def _safe_absolute_path(path: Path) -> tuple[str, ...]:
    path = Path(path)
    raw = str(path)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or "\0" in raw
        or os.path.normpath(raw) != raw
    ):
        raise KeyServiceError("System key service path is invalid.")
    parts = tuple(part for part in path.parts if part not in ("/", ""))
    if not parts:
        raise KeyServiceError("System key service path is invalid.")
    return parts


def _open_root_directory_chain(parts: tuple[str, ...]) -> int:
    if not _NOFOLLOW or not _DIRECTORY:
        raise KeyServiceError("Safe system path checks are unavailable.")
    try:
        descriptor = os.open("/", os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
    except OSError:
        raise KeyServiceError("Cannot safely open system path.") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0:
            raise KeyServiceError("System path ownership is unsafe.")
        for part in parts:
            next_descriptor = os.open(
                part,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                dir_fd=descriptor,
            )
            next_metadata = os.fstat(next_descriptor)
            if (
                not stat.S_ISDIR(next_metadata.st_mode)
                or next_metadata.st_uid != 0
                or stat.S_IMODE(next_metadata.st_mode) & 0o022
            ):
                os.close(next_descriptor)
                raise KeyServiceError("System path ownership is unsafe.")
            os.close(descriptor)
            descriptor = next_descriptor
        result = descriptor
        descriptor = -1
        return result
    except KeyServiceError:
        raise
    except OSError:
        raise KeyServiceError("Cannot safely open system path.") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_root_config(path: Path) -> bytes:
    parts = _safe_absolute_path(path)
    parent_fd = _open_root_directory_chain(parts[:-1])
    descriptor: int | None = None
    try:
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | _NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise KeyServiceError("System key service configuration is unsafe.")
        content = bytearray()
        while len(content) <= 4096:
            chunk = os.read(descriptor, min(1024, 4097 - len(content)))
            if not chunk:
                return bytes(content)
            content.extend(chunk)
        raise KeyServiceError("System key service configuration is too large.")
    except KeyServiceError:
        raise
    except OSError:
        raise KeyServiceError("Cannot safely read system key service configuration.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def _parse_endpoint(content: bytes, *, from_system_config: bool) -> ServiceEndpoint:
    data = _json_bytes(content, limit=4096)
    expected = {
        "schema",
        "state_dir",
        "socket_path",
        "service_uid",
        "allow_root_peer",
    }
    if set(data) != expected or type(data.get("schema")) is not int or data["schema"] != 1:
        raise KeyServiceError("System key service configuration is invalid.")
    service_uid = data.get("service_uid")
    allow_root_peer = data.get("allow_root_peer")
    state_dir = data.get("state_dir")
    socket_path = data.get("socket_path")
    if (
        type(service_uid) is not int
        or service_uid <= 0
        or service_uid >= 2**32 - 1
        or type(allow_root_peer) is not bool
        or not isinstance(state_dir, str)
        or not isinstance(socket_path, str)
    ):
        raise KeyServiceError("System key service configuration is invalid.")
    state_path = Path(state_dir)
    socket_file = Path(socket_path)
    _safe_absolute_path(state_path)
    _safe_absolute_path(socket_file)
    return ServiceEndpoint(
        socket_file,
        state_path,
        service_uid,
        allow_root_peer,
        _from_system_config=from_system_config,
    )


def _load_system_endpoint(path: Path) -> ServiceEndpoint:
    return _parse_endpoint(_read_root_config(path), from_system_config=True)


def _verify_protected_socket_path(endpoint: ServiceEndpoint) -> os.stat_result:
    if not endpoint._from_system_config:
        try:
            metadata = endpoint.socket_path.lstat()
        except OSError:
            raise KeyServiceError("Key service endpoint is unavailable.") from None
        if not stat.S_ISSOCK(metadata.st_mode):
            raise KeyServiceError("Key service endpoint is unsafe.")
        return metadata

    parts = _safe_absolute_path(endpoint.socket_path)
    parent_fd = _open_root_directory_chain(parts[:-1])
    try:
        metadata = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISSOCK(metadata.st_mode):
            raise KeyServiceError("Key service endpoint is unsafe.")
        if metadata.st_uid not in {0, endpoint.service_uid}:
            raise KeyServiceError("Key service endpoint ownership is unsafe.")
        return metadata
    except KeyServiceError:
        raise
    except OSError:
        raise KeyServiceError("Key service endpoint is unavailable.") from None
    finally:
        os.close(parent_fd)


def _server_peer_is_trusted(
    endpoint: ServiceEndpoint,
    credentials: PeerCredentials,
    socket_metadata: os.stat_result,
) -> bool:
    if credentials.uid == endpoint.service_uid:
        return socket_metadata.st_uid == endpoint.service_uid
    return (
        credentials.uid == 0
        and endpoint.allow_root_peer
        and socket_metadata.st_uid == 0
    )


class KeyServiceClient:
    """Bounded retrieval client that verifies the configured server peer."""

    def __init__(
        self,
        endpoint: ServiceEndpoint,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.endpoint = endpoint
        if type(timeout) not in (int, float) or not 0 < timeout <= 5:
            raise KeyServiceError("Key service timeout is invalid.")
        self.timeout = timeout

    @classmethod
    def from_system_config(cls) -> KeyServiceClient:
        return cls(ServiceEndpoint.from_system_config())

    def get_key(self, store_id: str) -> bytes:
        identifier = _canonical_uuid(store_id)
        socket_metadata = _verify_protected_socket_path(self.endpoint)
        request = json.dumps(
            {"v": PROTOCOL_VERSION, "store_id": identifier},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        if len(request) > MAX_REQUEST_BYTES:
            raise KeyServiceError("Key service request is too large.")
        connection: socket.socket | None = None
        try:
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.settimeout(self.timeout)
            connection.connect(str(self.endpoint.socket_path))
            credentials = peer_credentials(connection)
            if not _server_peer_is_trusted(self.endpoint, credentials, socket_metadata):
                raise KeyServiceError("Key service endpoint identity is untrusted.")
            _send_frame(connection, request, MAX_REQUEST_BYTES, self.timeout)
            response = _receive_frame(connection, MAX_RESPONSE_BYTES, self.timeout)
            result = _json_bytes(response, limit=MAX_RESPONSE_BYTES)
            if (
                set(result) == {"v", "error"}
                and type(result.get("v")) is int
                and result.get("v") == PROTOCOL_VERSION
                and result.get("error") == "unavailable"
            ):
                raise KeyUnavailable("Key service could not provide the storage key.")
            if (
                set(result) != {"v", "key"}
                or type(result.get("v")) is not int
                or result.get("v") != PROTOCOL_VERSION
            ):
                raise KeyServiceError("Key service response is invalid.")
            encoded = result.get("key")
            if not isinstance(encoded, str):
                raise KeyServiceError("Key service response is invalid.")
            try:
                key = encoded.encode("ascii")
            except UnicodeError:
                raise KeyServiceError("Key service response is invalid.") from None
            return _validate_key(key)
        except KeyServiceError:
            raise
        except (OSError, TimeoutError):
            raise KeyUnavailable("Key service could not provide the storage key.") from None
        finally:
            if connection is not None:
                connection.close()


def _send_frame(connection: socket.socket, payload: bytes, limit: int, timeout: float) -> None:
    if not payload or len(payload) > limit:
        raise KeyServiceError("Key service message is invalid.")
    frame = struct.pack("!H", len(payload)) + payload
    try:
        connection.settimeout(timeout)
        connection.sendall(frame)
    except (OSError, TimeoutError):
        raise KeyUnavailable("Key service could not provide the storage key.") from None


def _receive_frame(connection: socket.socket, limit: int, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout

    def receive_exact(length: int) -> bytes:
        content = bytearray()
        while len(content) < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise KeyUnavailable("Key service could not provide the storage key.")
            connection.settimeout(remaining)
            try:
                chunk = connection.recv(length - len(content))
            except (OSError, TimeoutError):
                raise KeyUnavailable("Key service could not provide the storage key.") from None
            if not chunk:
                raise KeyUnavailable("Key service could not provide the storage key.")
            content.extend(chunk)
        return bytes(content)

    size = struct.unpack("!H", receive_exact(2))[0]
    if size == 0 or size > limit:
        raise KeyServiceError("Key service message is invalid.")
    return receive_exact(size)


class _Registry(Protocol):
    def retrieve(self, uid: int, store_id: str) -> bytes: ...


def _valid_account_fingerprint(value: object) -> str:
    if not isinstance(value, str) or not _HEX_64.fullmatch(value):
        raise KeyServiceError("Account identity is malformed.")
    return value


class DirectoryKeyRegistry:
    """Private persistent key registry with separate root-only admin methods."""

    def __init__(
        self,
        state_dir: Path,
        service_uid: int,
        *,
        identity_for_uid: Callable[[int], str] = account_fingerprint,
        admin_authorizer: Callable[[], bool] | None = None,
        _test_directory_trust: bool = False,
    ) -> None:
        self.state_dir = Path(state_dir)
        if type(service_uid) is not int or service_uid <= 0 or service_uid >= 2**32 - 1:
            raise KeyServiceError("Dedicated service account identifier is invalid.")
        self.service_uid = service_uid
        self.identity_for_uid = identity_for_uid
        self.admin_authorizer = admin_authorizer or (lambda: os.geteuid() == 0)
        self._test_directory_trust = _test_directory_trust
        descriptor = self._validate_state_directory()
        os.close(descriptor)

    @classmethod
    def for_test(
        cls,
        state_dir: Path,
        service_uid: int,
        *,
        identity_for_uid: Callable[[int], str],
        admin_authorizer: Callable[[], bool],
    ) -> DirectoryKeyRegistry:
        """Create a registry with explicit fixture-only identity and admin trust."""
        return cls(
            state_dir,
            service_uid,
            identity_for_uid=identity_for_uid,
            admin_authorizer=admin_authorizer,
            _test_directory_trust=True,
        )

    def _validate_state_directory(self) -> int:
        if not _NOFOLLOW or not _DIRECTORY:
            raise KeyServiceError("Safe key registry operations are unavailable.")
        descriptor: int | None = None
        try:
            if self._test_directory_trust:
                descriptor = os.open(
                    self.state_dir,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                )
            else:
                parts = _safe_absolute_path(self.state_dir)
                parent_fd = _open_root_directory_chain(parts[:-1])
                try:
                    descriptor = os.open(
                        parts[-1],
                        os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                finally:
                    os.close(parent_fd)
            metadata = os.fstat(descriptor)
        except OSError:
            if descriptor is not None:
                os.close(descriptor)
            raise KeyServiceError("Cannot safely open key registry.") from None
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != self.service_uid
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            os.close(descriptor)
            raise KeyServiceError("Key registry directory is unsafe.")
        return descriptor

    def _record_name(self, uid: int, store_id: str, suffix: str) -> str:
        if type(uid) is not int or uid < 0:
            raise KeyServiceError("User identifier is invalid.")
        return f"{uid}-{_canonical_uuid(store_id)}{suffix}"

    def _lock(self) -> int:
        directory_fd = self._validate_state_directory()
        descriptor: int | None = None
        try:
            try:
                descriptor = os.open(
                    ".registry.lock",
                    os.O_RDWR | os.O_CREAT | _NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
                metadata = os.fstat(descriptor)
                if metadata.st_uid != self.service_uid and os.geteuid() == 0:
                    os.fchown(descriptor, self.service_uid, -1)
                    metadata = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != self.service_uid
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                ):
                    raise KeyServiceError("Key registry lock is unsafe.")
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except KeyServiceError:
                raise
            except OSError:
                raise KeyServiceError("Cannot lock key registry.") from None
            result = descriptor
            descriptor = None
            return result
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory_fd)

    def _read_named(self, name: str, *, allow_missing: bool = False) -> bytes | None:
        directory_fd = self._validate_state_directory()
        descriptor: int | None = None
        try:
            try:
                descriptor = os.open(
                    name,
                    os.O_RDONLY | _NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                if allow_missing:
                    return None
                raise KeyUnavailable("Key service could not provide the storage key.") from None
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != self.service_uid
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise KeyUnavailable("Key service could not provide the storage key.")
            content = bytearray()
            while len(content) <= _MAX_RECORD_BYTES:
                chunk = os.read(descriptor, min(512, _MAX_RECORD_BYTES + 1 - len(content)))
                if not chunk:
                    return bytes(content)
                content.extend(chunk)
            raise KeyUnavailable("Key service could not provide the storage key.")
        except (OSError, KeyServiceError):
            raise KeyUnavailable("Key service could not provide the storage key.") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory_fd)

    def _read_record(self, uid: int, store_id: str) -> tuple[bytes, str]:
        name = self._record_name(uid, store_id, ".json")
        content = self._read_named(name)
        assert content is not None
        data = _json_bytes(content, limit=_MAX_RECORD_BYTES)
        expected = {"schema", "uid", "store_id", "account_fingerprint", "key"}
        if (
            set(data) != expected
            or type(data.get("schema")) is not int
            or data.get("schema") != 1
            or type(data.get("uid")) is not int
            or data.get("uid") != uid
            or data.get("store_id") != store_id
        ):
            raise KeyUnavailable("Key service could not provide the storage key.")
        fingerprint = _valid_account_fingerprint(data.get("account_fingerprint"))
        key_text = data.get("key")
        if not isinstance(key_text, str):
            raise KeyUnavailable("Key service could not provide the storage key.")
        try:
            key = key_text.encode("ascii")
            _validate_key(key)
        except (UnicodeError, KeyServiceError):
            raise KeyUnavailable("Key service could not provide the storage key.") from None
        return key, fingerprint

    def _record_bytes(self, uid: int, store_id: str, key: bytes, fingerprint: str) -> bytes:
        return json.dumps(
            {
                "schema": 1,
                "uid": uid,
                "store_id": store_id,
                "account_fingerprint": fingerprint,
                "key": _validate_key(key).decode("ascii"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii") + b"\n"

    def _write_immutable(self, name: str, content: bytes) -> bool:
        directory_fd = self._validate_state_directory()
        temporary = f".envman-key-{os.urandom(16).hex()}.tmp"
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            if os.geteuid() == 0:
                os.fchown(descriptor, self.service_uid, -1)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != self.service_uid
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise KeyServiceError("Key registry record is unsafe.")
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                return False
            os.fsync(directory_fd)
            return True
        except KeyServiceError:
            raise
        except OSError:
            raise KeyServiceError("Cannot safely persist key registry record.") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            os.close(directory_fd)

    def _unlink_named(self, name: str) -> None:
        directory_fd = self._validate_state_directory()
        try:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                return
            os.fsync(directory_fd)
        except OSError:
            raise KeyServiceError("Cannot safely update key registry.") from None
        finally:
            os.close(directory_fd)

    def _require_admin(self) -> None:
        try:
            authorized = self.admin_authorizer()
        except BaseException:
            authorized = False
        if authorized is not True:
            raise KeyServiceError("Key registry administration requires root.")

    def enroll(self, uid: int, store_id: str, key: bytes) -> bool:
        """Admin-only immutable enrollment; exact repeated enrollment is a no-op."""
        self._require_admin()
        identifier = _canonical_uuid(store_id)
        _validate_key(key)
        try:
            fingerprint = _valid_account_fingerprint(self.identity_for_uid(uid))
        except KeyServiceError:
            raise KeyServiceError("Current account identity is unavailable.") from None
        lock_fd = self._lock()
        try:
            record_name = self._record_name(uid, identifier, ".json")
            retired_name = self._record_name(uid, identifier, ".retired")
            retired = self._read_named(retired_name, allow_missing=True)
            existing = self._read_named(record_name, allow_missing=True)
            if retired is not None:
                self._validate_retired_record(retired)
                raise KeyServiceError("Retired store identifiers cannot be enrolled again.")
            if existing is not None and retired is None:
                try:
                    old_key, old_fingerprint = self._read_record(uid, identifier)
                except KeyServiceError:
                    raise KeyServiceError("Existing enrollment is malformed; retire it first.") from None
                if old_key == key and old_fingerprint == fingerprint:
                    return False
                raise KeyServiceError("Existing enrollment is immutable; retire it first.")
            if existing is not None:
                raise KeyServiceError("Retired enrollment must be reconciled before re-enrollment.")
            record = self._record_bytes(uid, identifier, key, fingerprint)
            created = self._write_immutable(record_name, record)
            if not created:
                old_key, old_fingerprint = self._read_record(uid, identifier)
                if old_key != key or old_fingerprint != fingerprint:
                    raise KeyServiceError("Concurrent enrollment created a different key.")
            return created
        finally:
            os.close(lock_fd)

    def retire(self, uid: int, store_id: str) -> bool:
        """Admin-only retirement; a tombstone denies retrieval before cleanup."""
        self._require_admin()
        identifier = _canonical_uuid(store_id)
        if type(uid) is not int or uid < 0:
            raise KeyServiceError("User identifier is invalid.")
        lock_fd = self._lock()
        try:
            record_name = self._record_name(uid, identifier, ".json")
            retired_name = self._record_name(uid, identifier, ".retired")
            tombstone = b'{"schema":1,"retired":true}\n'
            created = self._write_immutable(retired_name, tombstone)
            retired = self._read_named(retired_name)
            assert retired is not None
            self._validate_retired_record(retired)
            self._unlink_named(record_name)
            return created
        finally:
            os.close(lock_fd)

    @staticmethod
    def _validate_retired_record(content: bytes) -> None:
        data = _json_bytes(content, limit=128)
        if data != {"schema": 1, "retired": True}:
            raise KeyServiceError("Key registry retirement record is malformed.")

    def retrieve(self, uid: int, store_id: str) -> bytes:
        """Return key only when UID, store, and enrolled passwd identity match."""
        identifier = _canonical_uuid(store_id)
        if type(uid) is not int or uid < 0:
            raise KeyUnavailable("Key service could not provide the storage key.")
        try:
            if self._read_named(self._record_name(uid, identifier, ".retired"), allow_missing=True) is not None:
                raise KeyUnavailable("Key service could not provide the storage key.")
            key, enrolled_identity = self._read_record(uid, identifier)
            current_identity = _valid_account_fingerprint(self.identity_for_uid(uid))
        except KeyServiceError:
            raise KeyUnavailable("Key service could not provide the storage key.") from None
        if current_identity != enrolled_identity:
            raise KeyUnavailable("Key service could not provide the storage key.")
        return key


def _parse_request(content: bytes) -> str:
    data = _json_bytes(content, limit=MAX_REQUEST_BYTES)
    if set(data) != {"v", "store_id"} or type(data.get("v")) is not int or data.get("v") != PROTOCOL_VERSION:
        raise KeyServiceError("Key service request is invalid.")
    return _canonical_uuid(data.get("store_id"))


def _response(key: bytes | None) -> bytes:
    if key is None:
        content = {"v": PROTOCOL_VERSION, "error": "unavailable"}
    else:
        content = {"v": PROTOCOL_VERSION, "key": _validate_key(key).decode("ascii")}
    return json.dumps(content, sort_keys=True, separators=(",", ":")).encode("ascii")


class KeyServiceServer:
    """Bounded retrieval-only server for an already authenticated listener."""

    def __init__(
        self,
        listener: socket.socket,
        registry: _Registry,
        *,
        max_clients: int = MAX_ACTIVE_CLIENTS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if listener.family != socket.AF_UNIX or listener.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
            raise KeyServiceError("Key service listener is not a Unix stream socket.")
        if listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 1:
            raise KeyServiceError("Key service listener is not accepting connections.")
        if (
            type(max_clients) is not int
            or not 1 <= max_clients <= MAX_ACTIVE_CLIENTS
            or type(timeout) not in (int, float)
            or not 0 < timeout <= 5
        ):
            raise KeyServiceError("Key service limits are invalid.")
        self.listener = listener
        self.registry = registry
        self.max_clients = max_clients
        self.timeout = timeout
        self._slots = threading.BoundedSemaphore(max_clients)
        self._stopping = threading.Event()
        self._threads: set[threading.Thread] = set()
        self._threads_lock = threading.Lock()

    def _serve_connection(self, connection: socket.socket) -> None:
        try:
            try:
                connection.settimeout(self.timeout)
                peer = peer_credentials(connection)
                request = _parse_request(_receive_frame(connection, MAX_REQUEST_BYTES, self.timeout))
                try:
                    key = self.registry.retrieve(peer.uid, request)
                except KeyServiceError:
                    key = None
                response = _response(key)
            except Exception:
                # Registry and transport errors stay secret-free and release
                # their bounded worker slot even when a filesystem call fails.
                response = _response(None)
            try:
                _send_frame(connection, response, MAX_RESPONSE_BYTES, self.timeout)
            except Exception:
                pass
        finally:
            try:
                connection.close()
            except OSError:
                pass
            self._slots.release()
            with self._threads_lock:
                self._threads.discard(threading.current_thread())

    def serve_forever(self) -> None:
        self.listener.settimeout(0.2)
        while not self._stopping.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stopping.is_set():
                    break
                raise KeyServiceError("Key service listener failed.") from None
            if not self._slots.acquire(blocking=False):
                connection.close()
                continue
            thread = threading.Thread(
                target=self._serve_connection,
                args=(connection,),
                daemon=True,
                name="envman-key-client",
            )
            with self._threads_lock:
                self._threads.add(thread)
                try:
                    thread.start()
                except RuntimeError:
                    self._threads.discard(thread)
                    self._slots.release()
                    connection.close()

    def close(self) -> None:
        self._stopping.set()
        try:
            self.listener.close()
        except OSError:
            pass
        with self._threads_lock:
            threads = tuple(self._threads)
        for thread in threads:
            thread.join(timeout=self.timeout + 0.2)


def validate_systemd_listener(
    listener: socket.socket,
    endpoint: ServiceEndpoint,
    environ: dict[str, str] | None = None,
) -> None:
    """Validate exact systemd activation contract and protected socket path."""
    environment = os.environ if environ is None else environ
    if environment.get("LISTEN_PID") != str(os.getpid()) or environment.get("LISTEN_FDS") != "1":
        raise KeyServiceError("Expected one systemd-activated key service listener.")
    if listener.fileno() != 3:
        raise KeyServiceError("Systemd key service listener descriptor is invalid.")
    if (
        listener.family != socket.AF_UNIX
        or listener.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
        or listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 1
    ):
        raise KeyServiceError("Systemd key service listener is invalid.")
    try:
        bound_path = listener.getsockname()
    except OSError:
        raise KeyServiceError("Systemd key service listener is invalid.") from None
    if bound_path != str(endpoint.socket_path):
        raise KeyServiceError("Systemd key service listener path is untrusted.")
    metadata = _verify_protected_socket_path(endpoint)
    if metadata.st_uid != 0 or not endpoint.allow_root_peer:
        raise KeyServiceError("Systemd key service socket ownership is untrusted.")


def _systemd_listener(endpoint: ServiceEndpoint) -> socket.socket:
    descriptor = 3
    try:
        listener = socket.socket(fileno=descriptor)
    except OSError:
        raise KeyServiceError("Systemd key service listener is unavailable.") from None
    try:
        validate_systemd_listener(listener, endpoint)
    except KeyServiceError:
        listener.close()
        raise
    return listener


def _read_admin_key(fd: int) -> bytes:
    content = _read_bounded(fd, 44, timeout=2.0)
    return _validate_key(content)


def _require_root() -> None:
    if os.geteuid() != 0:
        raise KeyServiceError("Key registry administration requires root.")


def _same_path(left: Path, right: Path) -> bool:
    return str(left) == str(right)


def _run_serve(args: argparse.Namespace) -> int:
    endpoint = ServiceEndpoint.from_system_config()
    if os.geteuid() != endpoint.service_uid:
        raise KeyServiceError("Key service must run under its dedicated service account.")
    if not _same_path(Path(args.state_dir), endpoint.state_dir) or not _same_path(Path(args.socket), endpoint.socket_path):
        raise KeyServiceError("Key service arguments do not match administrator configuration.")
    if not args.socket_activation:
        raise KeyServiceError("Key service requires systemd socket activation.")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    registry = DirectoryKeyRegistry(endpoint.state_dir, endpoint.service_uid)
    listener = _systemd_listener(endpoint)
    server = KeyServiceServer(listener, registry)

    def stop(_signum: int, _frame: object) -> None:
        server.close()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.close()
    return 0


def _run_admin_enroll(args: argparse.Namespace) -> int:
    _require_root()
    endpoint = ServiceEndpoint.from_system_config()
    state_dir = Path(args.state_dir) if args.state_dir else endpoint.state_dir
    if not _same_path(state_dir, endpoint.state_dir):
        raise KeyServiceError("Key registry path does not match administrator configuration.")
    key = _read_admin_key(args.key_fd)
    registry = DirectoryKeyRegistry(endpoint.state_dir, endpoint.service_uid)
    created = registry.enroll(args.uid, args.store_id, key)
    print("enrolled" if created else "already-enrolled")
    return 0


def _run_admin_retire(args: argparse.Namespace) -> int:
    _require_root()
    endpoint = ServiceEndpoint.from_system_config()
    state_dir = Path(args.state_dir) if args.state_dir else endpoint.state_dir
    if not _same_path(state_dir, endpoint.state_dir):
        raise KeyServiceError("Key registry path does not match administrator configuration.")
    registry = DirectoryKeyRegistry(endpoint.state_dir, endpoint.service_uid)
    retired = registry.retire(args.uid, args.store_id)
    print("retired" if retired else "already-retired")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Envman local storage key service")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve retrieval requests on an activated socket")
    serve.add_argument("--state-dir", required=True)
    serve.add_argument("--socket", required=True)
    serve.add_argument("--socket-activation", action="store_true")
    serve.set_defaults(run=_run_serve)

    enroll = commands.add_parser("admin-enroll", help="enroll one storage key from a private file descriptor")
    enroll.add_argument("--uid", type=int, required=True)
    enroll.add_argument("--store-id", required=True)
    enroll.add_argument("--key-fd", type=int, required=True)
    enroll.add_argument("--state-dir")
    enroll.set_defaults(run=_run_admin_enroll)

    retire = commands.add_parser("admin-retire", help="retire one user storage key")
    retire.add_argument("--uid", type=int, required=True)
    retire.add_argument("--store-id", required=True)
    retire.add_argument("--state-dir")
    retire.set_defaults(run=_run_admin_retire)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except KeyServiceError as error:
        print(f"envman-key-service: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("envman-key-service: operation failed safely", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # `python -I /root-owned/runtime/_key_service.py` excludes the working
    # directory. Only this exact root-owned runtime directory is added back.
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
