"""Synthetic Linux namespace/chroot integration fixture; never run on the host.

The unittest launcher creates a mapped user/mount namespace first. Imports occur
before chroot; all service state and /etc contents are disposable synthetic data.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import tempfile
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptography.fernet import Fernet
from envman._key_service import (
    DirectoryKeyRegistry,
    KeyServiceClient,
    KeyServiceError,
    _run_serve,
)


def main() -> None:
    # Requiring the namespace marker and mapped uid prevents an accidental host
    # invocation. The fixture cannot dispatch before its launcher establishes it.
    if os.getuid() != 0 or os.environ.get("ENVMAN_NAMESPACE_FIXTURE") != "1":
        raise RuntimeError("run only through test_key_service_namespace.py")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        root.chmod(0o755)
        for name in ("etc/envman", "run/envman-keys", "var/lib/envman-keys"):
            (root / name).mkdir(parents=True, mode=0o755)
        (root / "etc/passwd").write_text(
            "root:x:0:0:root:/root:/bin/false\n"
            "envman-keys:x:1:1:service:/nonexistent:/bin/false\n"
            "fixture-a:x:2:2:fixture:/home/a:/bin/false\n"
            "fixture-b:x:3:3:fixture:/home/b:/bin/false\n"
        )
        state = root / "var/lib/envman-keys"
        state.chmod(0o700)
        os.chown(state, 1, 1)
        (root / "etc/envman/key-service.json").write_text(json.dumps({
            "schema": 1, "state_dir": "/var/lib/envman-keys",
            "socket_path": "/run/envman-keys/key-service.sock",
            "service_uid": 1, "allow_root_peer": True,
        }))
        for path in root.rglob("*"):
            if path.is_dir() and path != state:
                path.chmod(0o755)
            elif path.is_file():
                path.chmod(0o644)
        # A fork confines chroot to this child and leaves parent cleanup intact.
        child = os.fork()
        if child == 0:
            try:
                os.chroot(root)
                os.chdir("/")
                exercise()
                os._exit(0)
            except BaseException:
                traceback.print_exc()
                os._exit(1)
        _, status = os.waitpid(child, 0)
        if os.waitstatus_to_exitcode(status) != 0:
            raise RuntimeError("namespace service integration failed")
    print("PASS real cross-UID, production endpoint trust, and inherited listener; simulated systemd activation")


def exercise() -> None:
    registry = DirectoryKeyRegistry(Path("/var/lib/envman-keys"), 1)
    own, other = str(uuid.uuid4()), str(uuid.uuid4())
    own_key, other_key = Fernet.generate_key(), Fernet.generate_key()
    registry.enroll(2, own, own_key)
    registry.enroll(3, other, other_key)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind("/run/envman-keys/key-service.sock")
    Path("/run/envman-keys/key-service.sock").chmod(0o666)
    listener.listen(16)
    server = os.fork()
    if server == 0:
        if listener.fileno() != 3:
            os.dup2(listener.fileno(), 3)
            listener.close()
        os.setgroups([])
        os.setgid(1)
        os.setuid(1)
        os.environ["LISTEN_PID"] = str(os.getpid())
        os.environ["LISTEN_FDS"] = "1"
        result = _run_serve(argparse.Namespace(
            state_dir="/var/lib/envman-keys", socket="/run/envman-keys/key-service.sock",
            socket_activation=True,
        ))
        os._exit(result)
    listener.close()
    try:
        client_pid = os.fork()
        if client_pid == 0:
            try:
                os.setgroups([])
                os.setgid(2)
                os.setuid(2)
                client = KeyServiceClient.from_system_config()
                assert client.get_key(own) == own_key
                try:
                    client.get_key(other)
                    raise AssertionError("cross-UID key disclosed")
                except KeyServiceError:
                    pass
                # System config is validated through real descriptor walks.
                assert Path("/etc/envman/key-service.json").stat().st_uid == 0
                os._exit(0)
            except BaseException:
                traceback.print_exc()
                os._exit(1)
        _, status = os.waitpid(client_pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        os.kill(server, signal.SIGTERM)
        os.waitpid(server, 0)


if __name__ == "__main__":
    main()
