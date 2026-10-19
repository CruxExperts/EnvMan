"""Adversarial wire traffic uses real sockets and explicitly injected test trust."""

from __future__ import annotations

import os
import socket
import struct
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from cryptography.fernet import Fernet
from envman._key_service import (
    MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, KeyServiceClient, KeyServiceError,
    KeyServiceServer, ServiceEndpoint, validate_systemd_listener,
)


def closed_reply(connection: socket.socket) -> bytes:
    """Collect a bounded reply without assuming stream packet boundaries."""
    result = bytearray()
    while len(result) <= MAX_RESPONSE_BYTES + 2:
        part = connection.recv(MAX_RESPONSE_BYTES + 3 - len(result))
        if not part:
            return bytes(result)
        result.extend(part)
    raise AssertionError("server reply exceeds the protocol bound")


class KeyServiceProtocolTests(unittest.TestCase):
    def test_hostile_requests_and_saturated_clients_recover_without_key_disclosure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.sock"
            key = Fernet.generate_key()
            store_id = str(uuid.uuid4())

            class Registry:
                def retrieve(self, uid: int, requested: str) -> bytes:
                    if uid != os.getuid() or requested != store_id:
                        raise KeyServiceError("unavailable")
                    return key

            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(path))
            listener.listen(16)
            server = KeyServiceServer(listener, Registry(), max_clients=2, timeout=0.1)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                for payload in (
                    b'{"v":1,"uid":0,"store_id":"' + store_id.encode() + b'"}',
                    b'{"v":true,"store_id":"' + store_id.encode() + b'"}',
                    b'{"v":1,"v":1,"store_id":"' + store_id.encode() + b'"}',
                    b'\xff', b'[]', b'{}', b'{' ,
                ):
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                        connection.settimeout(1)
                        connection.connect(str(path))
                        connection.sendall(struct.pack("!H", len(payload)) + payload)
                        response = closed_reply(connection)
                        self.assertNotIn(key, response)
                        self.assertIn(b"unavailable", response)
                for size in (0, MAX_REQUEST_BYTES + 1, 65535):
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                        connection.settimeout(1)
                        connection.connect(str(path))
                        connection.sendall(struct.pack("!H", size))
                        self.assertNotIn(key, closed_reply(connection))
                held = [socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) for _ in range(8)]
                started = time.monotonic()
                try:
                    for connection in held:
                        connection.settimeout(1)
                        connection.connect(str(path))
                    for connection in held:
                        try:
                            response = connection.recv(MAX_RESPONSE_BYTES + 2)
                        except ConnectionResetError:
                            response = b""
                        self.assertNotIn(key, response)
                finally:
                    for connection in held:
                        connection.close()
                self.assertLess(time.monotonic() - started, 2)
                client = KeyServiceClient(ServiceEndpoint.for_test(
                    path, state_dir=Path(directory), service_uid=os.getuid(),
                ))
                self.assertEqual(client.get_key(store_id), key)
                with self.assertRaises(KeyServiceError):
                    validate_systemd_listener(listener, client.endpoint, {"LISTEN_PID": "0", "LISTEN_FDS": "1"})
            finally:
                server.close()
                thread.join(2)

    def test_hostile_server_oversized_response_fails_within_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(path))
            listener.listen(1)

            def hostile() -> None:
                connection, _ = listener.accept()
                with connection:
                    connection.recv(512)
                    connection.sendall(struct.pack("!H", MAX_RESPONSE_BYTES + 1))

            thread = threading.Thread(target=hostile)
            thread.start()
            client = KeyServiceClient(ServiceEndpoint.for_test(
                path, state_dir=Path(directory), service_uid=os.getuid(),
            ), timeout=0.1)
            try:
                started = time.monotonic()
                with self.assertRaises(KeyServiceError):
                    client.get_key(str(uuid.uuid4()))
                self.assertLess(time.monotonic() - started, 1)
            finally:
                listener.close()
                thread.join(1)


if __name__ == "__main__":
    unittest.main()
