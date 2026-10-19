"""Resolve Envman's storage key from its selected local provider.

Missing provider metadata keeps the historical per-user file-key behavior.
Service selection is explicit and never falls back to that file key.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

if __package__:
    from ._secure_store import SecureStoreError, atomic_write_private, load_or_create_file_key, safe_read
else:  # retained runtime is executed with -I from its own root-owned directory
    from _secure_store import (  # type: ignore[import-not-found]
        SecureStoreError,
        atomic_write_private,
        load_or_create_file_key,
        safe_read,
    )


PROVIDER_METADATA_NAME = "storage-provider.json"
PROVIDER_SCHEMA = 1
MAX_PROVIDER_METADATA_BYTES = 4096


class StorageKeyProviderError(SecureStoreError):
    """Raised when provider selection or retrieval is unsafe or unavailable."""


@dataclass(frozen=True)
class ProviderSelection:
    """The selected key source and optional service-store identity."""

    provider: str
    store_id: str | None = None

    def as_metadata(self) -> dict[str, object]:
        if self.provider == "file":
            return {"schema": PROVIDER_SCHEMA, "provider": "file"}
        if self.provider == "service" and self.store_id is not None:
            return {
                "schema": PROVIDER_SCHEMA,
                "provider": "service",
                "store_id": self.store_id,
            }
        raise StorageKeyProviderError("Storage provider metadata is invalid.")


class KeyServiceClient(Protocol):
    def get_key(self, store_id: str) -> bytes: ...


def provider_metadata_path(config_dir: Path) -> Path:
    """Return the per-store provider selection path below the config directory."""
    return Path(config_dir) / "envman" / PROVIDER_METADATA_NAME


def _read_optional_metadata(path: Path) -> bytes | None:
    """Read private metadata while distinguishing absence from unsafe input."""
    parent = path.parent
    try:
        parent_metadata = parent.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise StorageKeyProviderError("Cannot safely inspect provider metadata directory.") from None
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or stat.S_ISLNK(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.getuid()
    ):
        raise StorageKeyProviderError("Provider metadata directory is unsafe.")
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise StorageKeyProviderError("Cannot safely inspect provider metadata.") from None
    if stat.S_IMODE(parent_metadata.st_mode) != 0o700:
        raise StorageKeyProviderError("Provider metadata directory is unsafe.")
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise StorageKeyProviderError("Provider metadata is not a regular file.")
    try:
        return safe_read(path, MAX_PROVIDER_METADATA_BYTES, expected_mode=0o600)
    except SecureStoreError as error:
        raise StorageKeyProviderError(str(error)) from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _validate_store_id(value: object) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise StorageKeyProviderError("Storage provider metadata is invalid.")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise StorageKeyProviderError("Storage provider metadata is invalid.") from None
    if str(parsed) != value:
        raise StorageKeyProviderError("Storage provider metadata is invalid.")
    return value


def _validate_storage_key(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != 44:
        raise StorageKeyProviderError("Storage key service returned an invalid key.")
    try:
        decoded = base64.b64decode(value, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise StorageKeyProviderError("Storage key service returned an invalid key.") from None
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded) != value:
        raise StorageKeyProviderError("Storage key service returned an invalid key.")
    return value


def read_provider(config_dir: Path) -> ProviderSelection:
    """Read provider selection; absent metadata selects the existing file key."""
    content = _read_optional_metadata(provider_metadata_path(config_dir))
    if content is None:
        return ProviderSelection("file")
    try:
        metadata = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise StorageKeyProviderError("Storage provider metadata is malformed.") from None
    if not isinstance(metadata, dict):
        raise StorageKeyProviderError("Storage provider metadata is malformed.")
    if type(metadata.get("schema")) is not int or metadata.get("schema") != PROVIDER_SCHEMA:
        raise StorageKeyProviderError("Storage provider metadata version is unsupported.")
    provider = metadata.get("provider")
    if provider == "file" and set(metadata) == {"schema", "provider"}:
        return ProviderSelection("file")
    if provider == "service" and set(metadata) == {"schema", "provider", "store_id"}:
        return ProviderSelection("service", _validate_store_id(metadata.get("store_id")))
    raise StorageKeyProviderError("Storage provider metadata is invalid.")


def _canonical_metadata(selection: ProviderSelection) -> bytes:
    return json.dumps(
        selection.as_metadata(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def provider_fingerprint(config_dir: Path) -> str:
    """Return a stable identity for stale-writer checks, including absent=file."""
    selection = read_provider(config_dir)
    return hashlib.sha256(_canonical_metadata(selection)).hexdigest()


def write_provider(config_dir: Path, provider: str, store_id: str | None = None) -> None:
    """Atomically select a provider after its key is ready and verified."""
    if provider == "file" and store_id is None:
        selection = ProviderSelection("file")
    elif provider == "service" and store_id is not None:
        selection = ProviderSelection("service", _validate_store_id(store_id))
    else:
        raise StorageKeyProviderError("Storage provider selection is invalid.")
    try:
        atomic_write_private(
            provider_metadata_path(config_dir),
            _canonical_metadata(selection) + b"\n",
        )
    except SecureStoreError as error:
        raise StorageKeyProviderError(str(error)) from None


def resolve_storage_key(
    config_dir: Path,
    state_dir: Path,
    *,
    create: bool = False,
    service_client: KeyServiceClient | None = None,
) -> bytes:
    """Retrieve the selected key without fallback across an explicit provider."""
    if type(create) is not bool:
        raise StorageKeyProviderError("Storage-key creation flag is invalid.")
    selection = read_provider(config_dir)
    if selection.provider == "file":
        try:
            return load_or_create_file_key(
                Path(state_dir) / "envman" / "storage.key",
                create=create,
            )
        except SecureStoreError as error:
            raise StorageKeyProviderError(str(error)) from None

    if selection.provider != "service" or selection.store_id is None:
        raise StorageKeyProviderError("Storage provider metadata is invalid.")
    if create:
        raise StorageKeyProviderError("A service storage key cannot be created by the client.")
    try:
        if service_client is None:
            if __package__:
                from ._key_service import KeyServiceClient
            else:
                from _key_service import KeyServiceClient  # type: ignore[import-not-found]

            service_client = KeyServiceClient.from_system_config()
        key = service_client.get_key(selection.store_id)
    except (OSError, ValueError, SecureStoreError) as error:
        raise StorageKeyProviderError(str(error)) from None
    return _validate_storage_key(key)
