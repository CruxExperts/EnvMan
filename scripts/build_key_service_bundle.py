#!/usr/bin/env python3
"""Build an offline administrator-installable key-service tree; never install it."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from envman._retained_loader import install_retained_runtime

NOTICE = (
    "Copyright © 2026 Crux Experts LLC\nhttps://www.cruxexperts.com/\n"
    "Private asset. Property of Crux Experts LLC. Use, reproduction, modification, "
    "distribution, or publication without prior written permission is prohibited.\n"
    "This notice applies to the generated provisioning assets. Envman software "
    "and third-party packages retain their original licenses and metadata; "
    "see runtime/LICENSE.envman and the package dist-info directories.\n"
)

SERVICE = """[Unit]
Description=Envman local storage key service
Requires=envman-key-service.socket
After=envman-key-service.socket

[Service]
Type=simple
User=envman-keys
Group=envman-keys
ExecStart=/usr/bin/python3.12 -I -B /usr/local/lib/envman-key-service/runtime/_key_service.py serve --state-dir /var/lib/envman-keys --socket /run/envman-keys/key-service.sock --socket-activation
StateDirectory=envman-keys
StateDirectoryMode=0700
UMask=0077
NoNewPrivileges=yes
CapabilityBoundingSet=
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=yes
ReadOnlyPaths=/var/lib/envman-keys
RestrictAddressFamilies=AF_UNIX
RestrictNamespaces=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallArchitectures=native
LimitCORE=0
LimitNOFILE=64
TasksMax=16
MemoryMax=96M
TimeoutStartSec=10
TimeoutStopSec=5
"""

SOCKET = """[Unit]
Description=Envman local storage key socket

[Socket]
ListenStream=/run/envman-keys/key-service.sock
SocketUser=root
SocketGroup=root
SocketMode=0666
DirectoryMode=0755
Accept=no
RemoveOnStop=yes
Service=envman-key-service.service
Backlog=16

[Install]
WantedBy=sockets.target
"""


def build(output: Path, service_uid: int) -> None:
    """Create a fresh tree without overwriting an existing bundle or host paths."""
    if type(service_uid) is not int or service_uid <= 0 or service_uid >= 2**32 - 1:
        raise ValueError("service UID must identify a dedicated non-root account")
    if not output.is_absolute():
        raise ValueError("output must be an absolute path")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    utility = output / ".runtime-build"
    utility.mkdir(mode=0o700)
    try:
        loader = install_retained_runtime(utility)
        runtime = output / "runtime"
        loader.parent.rename(runtime)
        for name in ("_key_provider.py", "_key_service.py"):
            shutil.copyfile(ROOT / "src" / "envman" / name, runtime / name)
        shutil.copyfile(ROOT / "LICENSE", runtime / "LICENSE.envman")
        # Retained packages are deliberately private. Administrator provisioning
        # gives the service read access while keeping every executable root-owned.
        for path in [runtime, *runtime.rglob("*")]:
            if path.is_symlink():
                raise ValueError("runtime contains a symlink")
            path.chmod(0o755 if path.is_dir() else 0o644)
    finally:
        shutil.rmtree(utility)
    config = {
        "schema": 1,
        "state_dir": "/var/lib/envman-keys",
        "socket_path": "/run/envman-keys/key-service.sock",
        "service_uid": service_uid,
        "allow_root_peer": True,
    }
    (output / "key-service.json").write_text(json.dumps(config, sort_keys=True) + "\n")
    (output / "envman-key-service.service").write_text(SERVICE)
    (output / "envman-key-service.socket").write_text(SOCKET)
    (output / "envman-keys.conf").write_text(
        'u envman-keys - "Envman storage key service" /var/lib/envman-keys /usr/sbin/nologin\n'
    )
    (output / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    manifest = {
        "schema": 1,
        "version": (ROOT / "VERSION").read_text().strip(),
        "notice": NOTICE,
        "files": {
            str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(output.rglob("*")) if path.is_file()
        },
    }
    (output / "bundle-manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--service-uid", required=True, type=int)
    args = parser.parse_args()
    try:
        build(args.output, args.service_uid)
    except (OSError, ValueError) as exc:
        print(f"key-service bundle: {exc}", file=sys.stderr)
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
